"""Durable counters and record store (SQLite) for hummingbot sub-packages."""

from state_store.__about__ import __version__
from state_store.adapters import (
    GroupIdAllocatorAdapter,
    GroupIdHighWaterAdapter,
    LinkedGroupStateAdapter,
    LinkedGroupStoreAdapter,
    StateStoreViews,
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
    "LinkedGroupStateAdapter",
    "LinkedGroupStoreAdapter",
    "MemoryStateStore",
    "RecordSerializationError",
    "RecordStore",
    "SchemaVersionError",
    "SqliteStateStore",
    "StateStoreError",
    "StateStoreViews",
    "__version__",
]
