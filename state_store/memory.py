"""In-memory store for tests. Not durable."""

from __future__ import annotations

import threading
from typing import Any

from state_store._common import (
    AsyncStoreMixin,
    check_bounds,
    decode_record,
    encode_record,
    next_value,
)


class MemoryStateStore(AsyncStoreMixin):
    """DurableCounter + RecordStore held in memory (`durable` is False)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._records: dict[str, dict[str, str]] = {}

    @property
    def durable(self) -> bool:
        return False

    def load(self, name: str) -> int | None:
        with self._lock:
            return self._counters.get(name)

    def advance_to(self, name: str, value: int) -> int:
        check_bounds(value)
        with self._lock:
            result = max(self._counters.get(name, value), value)
            self._counters[name] = result
            return result

    def reserve(self, name: str, floor: int = 0) -> int:
        with self._lock:
            value = next_value(self._counters.get(name), floor)
            self._counters[name] = value
            return value

    def save(self, collection: str, key: str, record: dict[str, Any]) -> None:
        data = encode_record(record)
        with self._lock:
            self._records.setdefault(collection, {})[key] = data

    def load_record(self, collection: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._records.get(collection, {}).get(key)
        return None if data is None else decode_record(data)

    def load_all(self, collection: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            items = dict(self._records.get(collection, {}))
        return {key: decode_record(data) for key, data in sorted(items.items())}

    def delete(self, collection: str, key: str) -> None:
        with self._lock:
            self._records.get(collection, {}).pop(key, None)
