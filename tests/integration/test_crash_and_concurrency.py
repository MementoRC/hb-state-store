"""Spec section 5 acceptance: SIGKILL durability, concurrency, crash-safe records."""

import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from state_store import SqliteStateStore

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="SIGKILL semantics are POSIX")

CYCLES = 3

RESERVE_LOOP = """
import sys
from state_store import SqliteStateStore
s = SqliteStateStore(sys.argv[1])
while True:
    print(s.counters.reserve("c"), flush=True)
"""

# Start barrier: signal ready, then block on stdin until the parent releases every child.
RESERVE_N = """
import sys, time
from state_store import SqliteStateStore
s = SqliteStateStore(sys.argv[1])
print("ready", flush=True)
sys.stdin.readline()
t0 = time.time()
values = [s.counters.reserve("c") for _ in range(int(sys.argv[2]))]
t1 = time.time()
print(t0, t1, ",".join(map(str, values)))
"""

SAVE_LOOP = """
import sys
from state_store import SqliteStateStore
s = SqliteStateStore(sys.argv[1])
a = {"id": "A", "blob": "a" * 500_000}
b = {"id": "B", "blob": "b" * 500_000}
while True:
    for rec in (a, b):
        s.records.save("col", "k", rec)
        print("x", flush=True)
"""


def _spawn(code: str, *args: str) -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.Popen(
        [sys.executable, "-c", code, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
        cwd=ROOT,
    )


def _kill_after_random_delay(proc: subprocess.Popen[str]) -> list[str]:
    """Wait for first output, then SIGKILL after a random delay; return complete lines."""
    assert proc.stdout is not None
    first = proc.stdout.readline()
    time.sleep(random.uniform(0.02, 0.25))
    proc.send_signal(signal.SIGKILL)
    rest, _ = proc.communicate()
    return [ln for ln in [first, *rest.splitlines(keepends=True)] if ln.endswith("\n")]


@posix_only
def test_sigkill_durability(tmp_path):
    path = tmp_path / "s.db"
    previous_persisted = 0
    previous_max = 0
    for _ in range(CYCLES):
        lines = _kill_after_random_delay(_spawn(RESERVE_LOOP, str(path)))
        values = [int(ln) for ln in lines]
        assert values
        assert values == sorted(set(values))
        assert min(values) > previous_max
        with SqliteStateStore(path) as s:
            persisted = s.counters.load("c")
        assert persisted is not None
        assert max(values) <= persisted
        assert persisted >= previous_persisted
        previous_persisted, previous_max = persisted, max(values)


def test_concurrent_processes_get_distinct_values(tmp_path):
    path = tmp_path / "s.db"
    SqliteStateStore(path).close()
    procs = [_spawn(RESERVE_N, str(path), "1000") for _ in range(4)]
    for proc in procs:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
    for proc in procs:  # release all children together
        assert proc.stdin is not None
        proc.stdin.write("go\n")
        proc.stdin.flush()

    values: list[int] = []
    intervals: list[tuple[float, float]] = []
    for proc in procs:
        out, _ = proc.communicate(timeout=25)
        assert proc.returncode == 0
        start, end, csv = out.strip().split(" ")
        intervals.append((float(start), float(end)))
        values.extend(int(v) for v in csv.split(","))

    assert len(values) == 4000
    assert len(set(values)) == 4000
    # Real contention: every child's window overlaps every other's.
    assert max(s for s, _ in intervals) < min(e for _, e in intervals)
    with SqliteStateStore(path) as s:
        assert s.counters.load("c") == max(values) == 4000


@posix_only
def test_record_save_is_crash_safe(tmp_path):
    path = tmp_path / "s.db"
    allowed = (
        {"id": "A", "blob": "a" * 500_000},
        {"id": "B", "blob": "b" * 500_000},
    )
    for _ in range(CYCLES):
        _kill_after_random_delay(_spawn(SAVE_LOOP, str(path)))
        with SqliteStateStore(path) as s:
            rec = s.records.load("col", "k")
        assert rec in allowed
