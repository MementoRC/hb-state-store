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
        "CREATE TABLE counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)",
        "CREATE TABLE records ("
        "collection TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL, "
        "PRIMARY KEY (collection, key))",
    ),
)
SCHEMA_VERSION = len(_MIGRATIONS)


class SqliteStateStore:
    """One sqlite file exposing `.counters` (DurableCounter) and `.records` (RecordStore).

    Both views share the store's single connection and lock; safe across threads and processes.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(os.fspath(path), check_same_thread=False, isolation_level=None)
        try:
            self._conn.execute("PRAGMA busy_timeout=30000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._migrate()
        except BaseException:
            self._conn.close()
            raise
        self.counters = SqliteCounters(self)
        self.records = SqliteRecords(self)

    @property
    def durable(self) -> bool:
        return True

    def close(self) -> None:
        with self._lock:
            self._conn.close()

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
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            try:
                self._conn.execute("COMMIT")
            except BaseException:
                with contextlib.suppress(sqlite3.Error):
                    self._conn.execute("ROLLBACK")
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
        return True

    def load(self, name: str) -> int | None:
        with self._store._lock:
            return _current(self._store._conn, name)

    def advance_to(self, name: str, value: int) -> int:
        check_bounds(value)
        with self._store._txn() as conn:
            current = _current(conn, name)
            if current is not None and current >= value:
                return current
            _upsert_counter(conn, name, value)
            return value

    def reserve(self, name: str, floor: int = 0) -> int:
        with self._store._txn() as conn:
            value = next_value(_current(conn, name), floor)
            _upsert_counter(conn, name, value)
            return value


class SqliteRecords(AsyncRecordMixin):
    """RecordStore view over a SqliteStateStore."""

    def __init__(self, store: SqliteStateStore) -> None:
        self._store = store

    @property
    def durable(self) -> bool:
        return True

    def save(self, collection: str, key: str, record: dict[str, Any]) -> None:
        data = encode_record(record)
        with self._store._txn() as conn:
            conn.execute(
                "INSERT INTO records (collection, key, data) VALUES (?, ?, ?) "
                "ON CONFLICT(collection, key) DO UPDATE SET data=excluded.data",
                (collection, key, data),
            )

    def load(self, collection: str, key: str) -> dict[str, Any] | None:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT data FROM records WHERE collection=? AND key=?", (collection, key)
            ).fetchone()
        return None if row is None else decode_record(row[0])

    def load_all(self, collection: str) -> dict[str, dict[str, Any]]:
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT key, data FROM records WHERE collection=? ORDER BY key", (collection,)
            ).fetchall()
        return {key: decode_record(data) for key, data in rows}

    def delete(self, collection: str, key: str) -> None:
        with self._store._txn() as conn:
            conn.execute("DELETE FROM records WHERE collection=? AND key=?", (collection, key))
