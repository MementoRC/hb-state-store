"""Storage protocols satisfied structurally by the concrete stores."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DurableCounter(Protocol):
    """Named, monotonic integer counters. A counter is unset until first reserve/advance."""

    def load(self, name: str) -> int | None:
        """Current value, or None if never set."""
        ...

    def advance_to(self, name: str, value: int) -> int:
        """Persist max(current, value) and return it. Never moves backwards."""
        ...

    def reserve(self, name: str, floor: int = 0) -> int:
        """Atomically return max(current + 1, floor), persisted before returning."""
        ...


@runtime_checkable
class RecordStore(Protocol):
    """Upsert-by-key store of JSON-serialisable records in namespaced collections."""

    @property
    def durable(self) -> bool: ...

    def save(self, collection: str, key: str, record: dict[str, Any]) -> None: ...

    def load(self, collection: str, key: str) -> dict[str, Any] | None: ...

    def load_all(self, collection: str) -> dict[str, dict[str, Any]]: ...

    def delete(self, collection: str, key: str) -> None:
        """Idempotent."""
        ...
