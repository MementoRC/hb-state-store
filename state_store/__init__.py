"""Stdlib-only persistent state store (sqlite3) for hummingbot sub-packages."""

from state_store.__about__ import __version__
from state_store.adapters import (
    GroupIdAllocatorAdapter,
    GroupIdHighWaterAdapter,
    LinkedGroupStoreAdapter,
)
from state_store.errors import (
    CounterOverflowError,
    RecordSerializationError,
    SchemaVersionError,
    StateStoreError,
)
from state_store.memory import MemoryStateStore
from state_store.protocols import DurableCounter, RecordStore
from state_store.sqlite import SqliteStateStore

__all__ = [
    "CounterOverflowError",
    "DurableCounter",
    "GroupIdAllocatorAdapter",
    "GroupIdHighWaterAdapter",
    "LinkedGroupStoreAdapter",
    "MemoryStateStore",
    "RecordSerializationError",
    "RecordStore",
    "SchemaVersionError",
    "SqliteStateStore",
    "StateStoreError",
    "__version__",
]
