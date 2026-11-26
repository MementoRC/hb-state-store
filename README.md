# hb-state-store

[![CI](https://github.com/MementoRC/hb-state-store/actions/workflows/ci.yml/badge.svg)](https://github.com/MementoRC/hb-state-store/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Durable counters and record store (SQLite) for hummingbot sub-packages.

## Overview

`state_store` is an L0 leaf (ADR 0001): depends on no other hb-* package (no L0->L0, never
upward). External conda-forge dependencies are allowed but kept minimal; PyPI-only
dependencies are not.

hb-state-store currently needs no third-party runtime dependencies (it uses sqlite3 from the
standard library). It never imports `hummingbot`.

## API

Two structural Protocols, exposed as two views of one store: `store.counters`
(`DurableCounter`) and `store.records` (`RecordStore`). `SqliteStateStore(path)` is durable (WAL,
`synchronous=FULL`, `BEGIN IMMEDIATE`, safe across threads and processes on one host; the views
share one connection, lock and file; it has `close()` and is a context manager).
`SqliteStateStore(":memory:")` reports `durable=False`. A new database file is created with mode
`0o600` (owner-only) on POSIX before sqlite opens it, and SQLite gives the `-wal`/`-shm`
sidecars the same mode; an existing file's mode is left untouched. After `os.fork()` the child
transparently opens its own connection and lock.
`MemoryStateStore()` is for tests only (`durable=False`). The store itself is neither protocol,
because `load(name)` (counter) and `load(collection, key)` (record) clash on one object.

- `DurableCounter`: `load(name) -> int | None`, `advance_to(name, value) -> int` (max-only),
  `reserve(name, floor=0) -> int` (returns `max(current + 1, floor)`, persisted before return;
  the first reserve of an unset counter returns `max(1, floor)`; an optional `ceiling` raises
  `CounterOverflowError` without persisting when the next value would exceed it), and the
  `durable` property. Negative values raise `ValueError`; bool and non-int raise `TypeError`;
  values above `2**63 - 1` raise `CounterOverflowError`. Counter names, collections and keys
  must be `str` (`TypeError` otherwise).
- `RecordStore`: `save(collection, key, record)`, `load(collection, key)`,
  `load_all(collection)`, `delete(collection, key)` (idempotent), `durable`. Records must be
  JSON-serialisable `dict`s (non-dict roots are rejected) with `str` dict keys at every depth
  (`allow_nan=False`); otherwise
  `RecordSerializationError` is raised before any write.
- Errors: `StateStoreError` > `SchemaVersionError` (on-disk schema newer than the code),
  `CounterOverflowError`, `RecordSerializationError`.

**Sync vs async**: the synchronous API is canonical. Async variants are thin
`asyncio.to_thread` wrappers on each view: `counters.aload/aadvance_to/areserve` and
`records.asave/aload/aload_all/adelete`.

## Adapters for strategy-framework linked orders

`state_store.adapters` presents the strategy-framework `LinkedGroupStore`,
`GroupIdHighWaterStore` and `GroupIdAllocator` shapes without importing it. The record codec is
injected: the composition layer supplies `to_dict`/`from_dict` until strategy-framework ships one.

```python
from state_store import (
    GroupIdAllocatorAdapter, GroupIdHighWaterAdapter, LinkedGroupStoreAdapter, SqliteStateStore,
)

store = SqliteStateStore("state.db")
groups = LinkedGroupStoreAdapter(
    store.records, to_dict=encode_group, from_dict=decode_group, group_id_of=lambda r: r.group_id
)
hwm = GroupIdHighWaterAdapter(store.counters)  # hwm.group_id_hwm_durable == counters.durable
allocator = GroupIdAllocatorAdapter(store.counters, max_group_id=2**31 - 1)
# group_id = await allocator.reserve_group_id()
```

## Future work (out of scope for v0.1)

Postgres or other network backends, cross-host coordination, encryption, TTL/eviction, an
event log.

## Installation

This package is distributed through conda-forge channels and managed with pixi:

```bash
pixi add hb-state-store
```

## Development

```bash
# Clone and install the dev environment
git clone https://github.com/MementoRC/hb-state-store.git
cd hb-state-store
pixi install

# Run tests
pixi run test

# Run quality checks
pixi run quality

# Coverage (fail_under=90)
pixi run coverage

# Run the full check suite
pixi run check
```

## Layout

```
hb-state-store/
  state_store/        # package
    __about__.py      # version (managed by release-please)
    __init__.py
  tests/
  scripts/            # conda-first dependency gate
  pyproject.toml      # pixi manifest + tool config
  pixi.lock
```

## Branch Strategy

- `development`: active development branch (default for PRs)
- `main`: release tagging only; PRs to `main` must come from `development`
