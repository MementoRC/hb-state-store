"""SQLite-backed durable counters and records (WAL, synchronous=FULL)."""

from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from state_store._common import (
    AsyncCounterMixin,
    AsyncRecordMixin,
    check_bounds,
    check_str,
    decode_record,
    encode_record,
    next_value,
)
from state_store.errors import SchemaVersionError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

# Ordered migration steps; step N (1-based) upgrades schema version N-1 to N.
_MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        "CREATE TABLE counters (name TEXT NOT NULL PRIMARY KEY, value INTEGER NOT NULL)",
        "CREATE TABLE records ("
        "collection TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL, "
        "PRIMARY KEY (collection, key))",
    ),
)
SCHEMA_VERSION = len(_MIGRATIONS)
_MEMORY_PATH = ":memory:"


def _precreate_private(path: str) -> None:
    """Create a missing db file as 0o600 (SQLite gives -wal/-shm the main file's mode)."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return
    os.close(fd)


class SqliteStateStore:
    """One sqlite file exposing `.counters` (DurableCounter) and `.records` (RecordStore).

    Both views share the store's single connection and lock; safe across threads and processes.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = os.fspath(path)
        self._in_memory = self._path == _MEMORY_PATH
        if not self._in_memory:
            _precreate_private(self._path)
        self._lock = threading.Lock()
        self._pid = os.getpid()
        self._conn = self._open()
        try:
            self._migrate()
        except BaseException:
            self._conn.close()
            raise
        self.counters = SqliteCounters(self)
        self.records = SqliteRecords(self)

    @property
    def durable(self) -> bool:
        return not self._in_memory

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
        except BaseException:
            conn.close()
            raise
        return conn

    def _ensure_process(self) -> None:
        """After a fork, never reuse the parent's connection or lock: open fresh ones."""
        pid = os.getpid()
        if pid != self._pid:
            self._lock = threading.Lock()
            self._conn = self._open()
            self._pid = pid

    def _reset_connection(self) -> None:
        """Replace the connection so that no transaction can remain active."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()
        with contextlib.suppress(sqlite3.Error):
            self._conn = self._open()

    @contextmanager
    def _locked(self) -> Iterator[sqlite3.Connection]:
        self._ensure_process()
        with self._lock:
            yield self._conn

    def close(self) -> None:
        with self._locked() as conn:
            conn.close()

    def __enter__(self) -> SqliteStateStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Connection]:
        with self._locked() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    # Keep the original error; drop the connection so no transaction stays open.
                    self._reset_connection()
                raise

    def _migrate(self) -> None:
        with self._txn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            version = 0 if row is None else int(row[0])
            if version > SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"on-disk schema version {version} is newer than supported {SCHEMA_VERSION}"
                )
            if version == SCHEMA_VERSION:
                return
            for step in _MIGRATIONS[version:]:
                for statement in step:
                    conn.execute(statement)
            conn.execute("DELETE FROM schema_version")
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))


def _current(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
    return None if row is None else int(row[0])


def _upsert_counter(conn: sqlite3.Connection, name: str, value: int) -> None:
    conn.execute(
        "INSERT INTO counters (name, value) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
        (name, value),
    )


class SqliteCounters(AsyncCounterMixin):
    """DurableCounter view over a SqliteStateStore."""

    def __init__(self, store: SqliteStateStore) -> None:
        self._store = store

    @property
    def durable(self) -> bool:
        return self._store.durable

    def load(self, name: str) -> int | None:
        check_str(name, "counter name")
        with self._store._locked() as conn:
            return _current(conn, name)

    def advance_to(self, name: str, value: int) -> int:
        check_str(name, "counter name")
        check_bounds(value)
        with self._store._txn() as conn:
            current = _current(conn, name)
            if current is not None and current >= value:
                return current
            _upsert_counter(conn, name, value)
            return value

    def reserve(self, name: str, floor: int = 0, ceiling: int | None = None) -> int:
        check_str(name, "counter name")
        with self._store._txn() as conn:
            value = next_value(_current(conn, name), floor, ceiling)
            _upsert_counter(conn, name, value)
            return value


class SqliteRecords(AsyncRecordMixin):
    """RecordStore view over a SqliteStateStore."""

    def __init__(self, store: SqliteStateStore) -> None:
        self._store = store

    @property
    def durable(self) -> bool:
        return self._store.durable

    def save(self, collection: str, key: str, record: dict[str, Any]) -> None:
        check_str(collection, "collection")
        check_str(key, "key")
        data = encode_record(record)
        with self._store._txn() as conn:
            conn.execute(
                "INSERT INTO records (collection, key, data) VALUES (?, ?, ?) "
                "ON CONFLICT(collection, key) DO UPDATE SET data=excluded.data",
                (collection, key, data),
            )

    def load(self, collection: str, key: str) -> dict[str, Any] | None:
        check_str(collection, "collection")
        check_str(key, "key")
        with self._store._locked() as conn:
            row = conn.execute(
                "SELECT data FROM records WHERE collection=? AND key=?", (collection, key)
            ).fetchone()
        return None if row is None else decode_record(row[0])

    def load_all(self, collection: str) -> dict[str, dict[str, Any]]:
        check_str(collection, "collection")
        with self._store._locked() as conn:
            rows = conn.execute(
                "SELECT key, data FROM records WHERE collection=? ORDER BY key", (collection,)
            ).fetchall()
        return {key: decode_record(data) for key, data in rows}

    def delete(self, collection: str, key: str) -> None:
        check_str(collection, "collection")
        check_str(key, "key")
        with self._store._txn() as conn:
            conn.execute("DELETE FROM records WHERE collection=? AND key=?", (collection, key))
