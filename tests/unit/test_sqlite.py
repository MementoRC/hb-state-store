"""SqliteStateStore specifics: persistence, schema version, pragmas, lifecycle, COMMIT failure."""

import sqlite3

import pytest

from state_store import SchemaVersionError, SqliteStateStore, StateStoreError


@pytest.mark.unit
def test_state_persists_across_reopen(tmp_path):
    path = tmp_path / "s.db"
    with SqliteStateStore(path) as s:
        assert s.counters.reserve("c") == 1
        s.records.save("col", "k", {"v": 1})
    with SqliteStateStore(str(path)) as s:
        assert s.counters.load("c") == 1
        assert s.counters.reserve("c") == 2
        assert s.records.load("col", "k") == {"v": 1}


@pytest.mark.unit
def test_schema_created_at_version_one_and_reopen_is_idempotent(tmp_path):
    path = tmp_path / "s.db"
    SqliteStateStore(path).close()
    SqliteStateStore(path).close()
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(1,)]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"schema_version", "counters", "records"} <= tables
    finally:
        conn.close()


@pytest.mark.unit
def test_wal_and_full_sync(tmp_path):
    with SqliteStateStore(tmp_path / "s.db") as s:
        assert s._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert s._conn.execute("PRAGMA synchronous").fetchone()[0] == 2


@pytest.mark.unit
def test_schema_version_too_new_rejected(tmp_path):
    path = tmp_path / "s.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version(version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version(version) VALUES (99)")
    conn.commit()
    conn.close()
    with pytest.raises(SchemaVersionError) as info:
        SqliteStateStore(path)
    assert isinstance(info.value, StateStoreError)
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(99,)]
    finally:
        conn.close()


@pytest.mark.unit
def test_close_is_idempotent_and_blocks_use(tmp_path):
    s = SqliteStateStore(tmp_path / "s.db")
    s.close()
    s.close()
    with pytest.raises(sqlite3.ProgrammingError):
        s.counters.load("c")


class _CommitFails:
    """Connection proxy whose COMMIT raises, to simulate a failed commit."""

    def __init__(self, conn, rollback_fails=False):
        self._conn = conn
        self._rollback_fails = rollback_fails

    def execute(self, sql, *args):
        if sql == "COMMIT":
            raise sqlite3.OperationalError("disk I/O error")
        if sql == "ROLLBACK":
            self._conn.execute(sql)
            if self._rollback_fails:
                raise sqlite3.OperationalError("rollback failed too")
        return self._conn.execute(sql, *args)


@pytest.mark.unit
@pytest.mark.parametrize("rollback_fails", [False, True])
def test_failed_commit_rolls_back_and_original_error_propagates(tmp_path, rollback_fails):
    with SqliteStateStore(tmp_path / "s.db") as s:
        real = s._conn
        s._conn = _CommitFails(real, rollback_fails)
        with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
            s.counters.reserve("c")
        assert real.in_transaction is False
        s._conn = real
        assert s.counters.load("c") is None
        assert s.counters.reserve("c") == 1
