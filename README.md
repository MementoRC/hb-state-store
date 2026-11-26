# hb-state-store

[![CI](https://github.com/MementoRC/hb-state-store/actions/workflows/ci.yml/badge.svg)](https://github.com/MementoRC/hb-state-store/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Stdlib-only persistent state store (sqlite3 + file lock) for hummingbot sub-packages.

## Overview

`state_store` is an L0 leaf under ADR 0001 with zero runtime dependencies: it uses only
the Python standard library, never imports `hummingbot`, and never imports another
sub-package.

## API

Two structural Protocols, both implemented by `SqliteStateStore(path)` (durable: WAL,
`synchronous=FULL`, `BEGIN IMMEDIATE`, safe across threads and processes on one host) and
`MemoryStateStore()` (tests only, `durable=False`):

- `DurableCounter`: `load(name) -> int | None`, `advance_to(name, value) -> int` (max-only),
  `reserve(name, floor=0) -> int` (returns `max(current + 1, floor)`, persisted before return;
  the first reserve of an unset counter returns `max(1, floor)`). Negative values raise
  `ValueError`; values above `2**63 - 1` raise `CounterOverflowError`.
- `RecordStore`: `save(collection, key, record)`, `load_record(collection, key)`,
  `load_all(collection)`, `delete(collection, key)` (idempotent), `durable`. Records must be
  JSON-serialisable (`allow_nan=False`); otherwise `RecordSerializationError` is raised before
  any write. The record getter is `load_record` because `load(name)` is the counter getter and
  one class implements both protocols.
- Errors: `StateStoreError` > `SchemaVersionError` (on-disk schema newer than the code),
  `CounterOverflowError`, `RecordSerializationError`.

**Sync vs async**: the synchronous API is canonical. The async variants (`areserve`,
`aadvance_to`, `aload_counter`, `asave`, `aload`, `aload_all`, `adelete`) are thin
`asyncio.to_thread` wrappers over it.

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
    store, to_dict=encode_group, from_dict=decode_group, group_id_of=lambda r: r.group_id
)
hwm = GroupIdHighWaterAdapter(store)  # hwm.group_id_hwm_durable is True for sqlite
allocator = GroupIdAllocatorAdapter(store, max_group_id=2**31 - 1)  # await allocator.reserve_group_id()
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
  state_store/        # package (stdlib only)
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
