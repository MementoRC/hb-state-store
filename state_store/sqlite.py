"""SQLite-backed durable counters and records (WAL, synchronous=FULL)."""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from state_store._common import (
    AsyncStoreMixin,
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


class SqliteStateStore(AsyncStoreMixin):
    """Durable DurableCounter + RecordStore in one sqlite file; safe across threads/processes."""

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
            self._conn.execute("COMMIT")

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

    # --- DurableCounter -------------------------------------------------

    def load(self, name: str) -> int | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
        return None if row is None else int(row[0])

    def _upsert_counter(self, conn: sqlite3.Connection, name: str, value: int) -> None:
        conn.execute(
            "INSERT INTO counters (name, value) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            (name, value),
        )

    def _current(self, conn: sqlite3.Connection, name: str) -> int | None:
        row = conn.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
        return None if row is None else int(row[0])

    def advance_to(self, name: str, value: int) -> int:
        check_bounds(value)
        with self._txn() as conn:
            current = self._current(conn, name)
            if current is not None and current >= value:
                return current
            self._upsert_counter(conn, name, value)
            return value

    def reserve(self, name: str, floor: int = 0) -> int:
        with self._txn() as conn:
            value = next_value(self._current(conn, name), floor)
            self._upsert_counter(conn, name, value)
            return value

    # --- RecordStore ----------------------------------------------------

    def save(self, collection: str, key: str, record: dict[str, Any]) -> None:
        data = encode_record(record)
        with self._txn() as conn:
            conn.execute(
                "INSERT INTO records (collection, key, data) VALUES (?, ?, ?) "
                "ON CONFLICT(collection, key) DO UPDATE SET data=excluded.data",
                (collection, key, data),
            )

    def load_record(self, collection: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM records WHERE collection=? AND key=?", (collection, key)
            ).fetchone()
        return None if row is None else decode_record(row[0])

    def load_all(self, collection: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, data FROM records WHERE collection=? ORDER BY key", (collection,)
            ).fetchall()
        return {key: decode_record(data) for key, data in rows}

    def delete(self, collection: str, key: str) -> None:
        with self._txn() as conn:
            conn.execute("DELETE FROM records WHERE collection=? AND key=?", (collection, key))
