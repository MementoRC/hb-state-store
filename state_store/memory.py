"""In-memory store for tests. Not durable."""

from __future__ import annotations

import threading
from typing import Any

from state_store._common import (
    AsyncCounterMixin,
    AsyncRecordMixin,
    check_bounds,
    check_str,
    decode_record,
    encode_record,
    next_value,
)


class MemoryStateStore:
    """In-memory `.counters` and `.records` views sharing one lock (`durable` is False)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._records: dict[str, dict[str, str]] = {}
        self.counters = MemoryCounters(self)
        self.records = MemoryRecords(self)

    @property
    def durable(self) -> bool:
        return False

    def close(self) -> None:
        """No-op; present for API parity with SqliteStateStore."""


class MemoryCounters(AsyncCounterMixin):
    def __init__(self, store: MemoryStateStore) -> None:
        self._store = store

    @property
    def durable(self) -> bool:
        return False

    def load(self, name: str) -> int | None:
        check_str(name, "counter name")
        with self._store._lock:
            return self._store._counters.get(name)

    def advance_to(self, name: str, value: int) -> int:
        check_str(name, "counter name")
        check_bounds(value)
        with self._store._lock:
            result = max(self._store._counters.get(name, value), value)
            self._store._counters[name] = result
            return result

    def reserve(self, name: str, floor: int = 0, ceiling: int | None = None) -> int:
        check_str(name, "counter name")
        with self._store._lock:
            value = next_value(self._store._counters.get(name), floor, ceiling)
            self._store._counters[name] = value
            return value


class MemoryRecords(AsyncRecordMixin):
    def __init__(self, store: MemoryStateStore) -> None:
        self._store = store

    @property
    def durable(self) -> bool:
        return False

    def save(self, collection: str, key: str, record: dict[str, Any]) -> None:
        check_str(collection, "collection")
        check_str(key, "key")
        data = encode_record(record)
        with self._store._lock:
            self._store._records.setdefault(collection, {})[key] = data

    def load(self, collection: str, key: str) -> dict[str, Any] | None:
        check_str(collection, "collection")
        check_str(key, "key")
        with self._store._lock:
            data = self._store._records.get(collection, {}).get(key)
        return None if data is None else decode_record(data)

    def load_all(self, collection: str) -> dict[str, dict[str, Any]]:
        check_str(collection, "collection")
        with self._store._lock:
            items = dict(self._store._records.get(collection, {}))
        return {key: decode_record(data) for key, data in sorted(items.items())}

    def delete(self, collection: str, key: str) -> None:
        check_str(collection, "collection")
        check_str(key, "key")
        with self._store._lock:
            self._store._records.get(collection, {}).pop(key, None)
