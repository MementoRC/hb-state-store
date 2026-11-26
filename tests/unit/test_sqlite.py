"""SqliteStateStore specifics: persistence, schema versioning, pragmas, lifecycle."""

import sqlite3

import pytest

from state_store import SchemaVersionError, SqliteStateStore, StateStoreError


@pytest.mark.unit
def test_state_persists_across_reopen(tmp_path):
    path = tmp_path / "s.db"
    with SqliteStateStore(path) as s:
        assert s.reserve("c") == 1
        s.save("col", "k", {"v": 1})
    with SqliteStateStore(str(path)) as s:
        assert s.load("c") == 1
        assert s.reserve("c") == 2
        assert s.load_record("col", "k") == {"v": 1}


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
    # the file is untouched and the lock released
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
        s.load("c")
