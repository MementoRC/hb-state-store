"""Spec section 5 acceptance: SIGKILL durability, concurrency, crash-safe records."""

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from state_store import SqliteStateStore

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="SIGKILL semantics are POSIX")

RESERVE_LOOP = """
import sys
from state_store import SqliteStateStore
s = SqliteStateStore(sys.argv[1])
while True:
    print(s.reserve("c"), flush=True)
"""

RESERVE_N = """
import sys
from state_store import SqliteStateStore
s = SqliteStateStore(sys.argv[1])
print(",".join(str(s.reserve("c")) for _ in range(int(sys.argv[2]))))
"""

SAVE_LOOP = """
import sys
from state_store import SqliteStateStore
s = SqliteStateStore(sys.argv[1])
a = {"id": "A", "blob": "a" * 500_000}
b = {"id": "B", "blob": "b" * 500_000}
while True:
    for rec in (a, b):
        s.save("col", "k", rec)
        print("x", flush=True)
"""


def _spawn(code: str, *args: str) -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.Popen(
        [sys.executable, "-c", code, *args],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
        cwd=ROOT,
    )


def _kill_after_lines(proc: subprocess.Popen[str], count: int) -> list[str]:
    assert proc.stdout is not None
    lines = [proc.stdout.readline() for _ in range(count)]
    proc.send_signal(signal.SIGKILL)
    rest, _ = proc.communicate()
    lines.extend(rest.splitlines(keepends=True))
    return [ln for ln in lines if ln.endswith("\n")]


@posix_only
def test_sigkill_durability(tmp_path):
    path = tmp_path / "s.db"
    proc = _spawn(RESERVE_LOOP, str(path))
    lines = _kill_after_lines(proc, 30)
    values = [int(ln) for ln in lines]
    assert len(values) >= 30
    assert values == sorted(set(values))

    with SqliteStateStore(path) as s:
        persisted = s.load("c")
        assert persisted is not None
        assert max(values) <= persisted
        nxt = s.reserve("c")
        assert nxt > persisted
        assert s.load("c") >= persisted


def test_concurrent_processes_get_distinct_values(tmp_path):
    path = tmp_path / "s.db"
    SqliteStateStore(path).close()
    procs = [_spawn(RESERVE_N, str(path), "1000") for _ in range(4)]
    values: list[int] = []
    for proc in procs:
        out, _ = proc.communicate(timeout=25)
        assert proc.returncode == 0
        values.extend(int(v) for v in out.strip().split(","))
    assert len(values) == 4000
    assert len(set(values)) == 4000
    with SqliteStateStore(path) as s:
        assert s.load("c") == max(values) == 4000


@posix_only
def test_record_save_is_crash_safe(tmp_path):
    path = tmp_path / "s.db"
    proc = _spawn(SAVE_LOOP, str(path))
    _kill_after_lines(proc, 6)
    with SqliteStateStore(path) as s:
        rec = s.load_record("col", "k")
    assert rec is not None
    assert rec in (
        {"id": "A", "blob": "a" * 500_000},
        {"id": "B", "blob": "b" * 500_000},
    )
