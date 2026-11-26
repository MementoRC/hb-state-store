"""Shared helpers: record codec, counter validation, async wrappers."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from state_store.errors import CounterOverflowError, RecordSerializationError

INT64_MAX = 2**63 - 1


def _check_keys(obj: object) -> None:
    """Reject non-str dict keys at any depth (json would silently coerce them)."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise RecordSerializationError(f"record key {key!r} is not a str")
            _check_keys(value)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _check_keys(item)


def encode_record(record: dict[str, Any]) -> str:
    """Serialise to JSON text, raising RecordSerializationError before any write."""
    try:
        _check_keys(record)
        return json.dumps(record, allow_nan=False)
    except RecursionError as exc:
        raise RecordSerializationError("record is too deeply nested or circular") from exc
    except (TypeError, ValueError) as exc:
        raise RecordSerializationError(f"record is not JSON-serialisable: {exc}") from exc


def decode_record(text: str) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(text))


def check_int(value: object, what: str = "counter value") -> int:
    """Reject bool and non-int (bool is an int subclass)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{what} must be an int, got {type(value).__name__}")
    return value


def check_non_negative(value: int) -> None:
    check_int(value)
    if value < 0:
        raise ValueError(f"negative counter value not allowed: {value}")


def check_bounds(value: int) -> int:
    check_non_negative(value)
    if value > INT64_MAX:
        raise CounterOverflowError(f"counter value {value} exceeds {INT64_MAX}")
    return value


def next_value(current: int | None, floor: int) -> int:
    """max(current + 1, floor) with the first value being max(1, floor)."""
    check_non_negative(floor)
    return check_bounds(max(1 if current is None else current + 1, floor))


class AsyncCounterMixin:
    """Async wrappers (asyncio.to_thread) over the canonical sync counter API."""

    def load(self, name: str) -> int | None:
        raise NotImplementedError

    def advance_to(self, name: str, value: int) -> int:
        raise NotImplementedError

    def reserve(self, name: str, floor: int = 0) -> int:
        raise NotImplementedError

    async def aload(self, name: str) -> int | None:
        return await asyncio.to_thread(self.load, name)

    async def aadvance_to(self, name: str, value: int) -> int:
        return await asyncio.to_thread(self.advance_to, name, value)

    async def areserve(self, name: str, floor: int = 0) -> int:
        return await asyncio.to_thread(self.reserve, name, floor)


class AsyncRecordMixin:
    """Async wrappers (asyncio.to_thread) over the canonical sync record API."""

    def save(self, collection: str, key: str, record: dict[str, Any]) -> None:
        raise NotImplementedError

    def load(self, collection: str, key: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def load_all(self, collection: str) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    def delete(self, collection: str, key: str) -> None:
        raise NotImplementedError

    async def asave(self, collection: str, key: str, record: dict[str, Any]) -> None:
        await asyncio.to_thread(self.save, collection, key, record)

    async def aload(self, collection: str, key: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.load, collection, key)

    async def aload_all(self, collection: str) -> dict[str, dict[str, Any]]:
        return await asyncio.to_thread(self.load_all, collection)

    async def adelete(self, collection: str, key: str) -> None:
        await asyncio.to_thread(self.delete, collection, key)
