"""SqliteStateStore specifics: persistence, schema version, pragmas, lifecycle, COMMIT failure."""

import os
import sqlite3
import stat
import sys

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


@pytest.mark.unit
def test_memory_path_is_not_durable():
    with SqliteStateStore(":memory:") as s:
        assert s.durable is False
        assert s.counters.durable is False
        assert s.records.durable is False
        assert s.counters.reserve("c") == 1


@pytest.mark.unit
def test_file_path_is_durable(tmp_path):
    with SqliteStateStore(tmp_path / "d.db") as s:
        assert s.durable is True
        assert s.counters.durable is True
        assert s.records.durable is True


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_new_db_file_is_owner_only(tmp_path):
    path = tmp_path / "perm.db"
    SqliteStateStore(path).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    for suffix in ("-wal", "-shm"):
        side = tmp_path / f"perm.db{suffix}"
        if side.exists():
            assert stat.S_IMODE(side.stat().st_mode) == 0o600


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_existing_db_file_mode_untouched(tmp_path):
    path = tmp_path / "pre.db"
    path.touch()
    path.chmod(0o640)
    SqliteStateStore(path).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


@pytest.mark.unit
@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs os.fork")
def test_fork_child_gets_fresh_connection_and_lock(tmp_path):
    path = tmp_path / "f.db"
    s = SqliteStateStore(path)
    assert s.counters.reserve("c") == 1
    parent_conn = s._conn
    pid = os.fork()
    if pid == 0:
        code = 1
        try:
            code = 0 if s.counters.reserve("c") == 2 and s._conn is not parent_conn else 3
        finally:
            os._exit(code)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert s._conn is parent_conn
    assert s.counters.reserve("c") == 3
    s.close()


class _RollbackFails:
    """Connection proxy where the body fails and ROLLBACK itself raises."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *args):
        if sql == "ROLLBACK":
            raise sqlite3.OperationalError("rollback failed")
        return self._conn.execute(sql, *args)

    def close(self):
        self._conn.close()


@pytest.mark.unit
def test_body_error_with_failed_rollback_resets_connection(tmp_path):
    with SqliteStateStore(tmp_path / "s.db") as s:
        real = s._conn
        s._conn = _RollbackFails(real)
        with pytest.raises(ValueError, match="boom"), s._txn():
            raise ValueError("boom")
        assert s._conn is not real
        assert s._conn.in_transaction is False
        assert s.counters.reserve("c") == 1
        assert s._conn.execute("PRAGMA synchronous").fetchone()[0] == 2


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
            return None
        return self._conn.execute(sql, *args)

    def close(self):
        self._conn.close()


@pytest.mark.unit
@pytest.mark.parametrize("rollback_fails", [False, True])
def test_failed_commit_rolls_back_and_original_error_propagates(tmp_path, rollback_fails):
    with SqliteStateStore(tmp_path / "s.db") as s:
        real = s._conn
        proxy = _CommitFails(real, rollback_fails)
        s._conn = proxy
        with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
            s.counters.reserve("c")
        if rollback_fails:
            assert s._conn is not proxy
            assert s._conn.in_transaction is False
        else:
            assert real.in_transaction is False
            s._conn = real
        assert s.counters.load("c") is None
        assert s.counters.reserve("c") == 1
