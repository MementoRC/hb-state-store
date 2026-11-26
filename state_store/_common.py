"""Shared helpers: record codec, counter validation, async wrappers."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from state_store.errors import CounterOverflowError, RecordSerializationError

INT64_MAX = 2**63 - 1


def encode_record(record: dict[str, Any]) -> str:
    """Serialise to JSON text, raising RecordSerializationError before any write."""
    try:
        return json.dumps(record, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RecordSerializationError(f"record is not JSON-serialisable: {exc}") from exc


def decode_record(text: str) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(text))


def check_non_negative(value: int) -> None:
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


class AsyncStoreMixin:
    """Async wrappers (asyncio.to_thread) over the canonical sync API."""

    def load(self, name: str) -> int | None:
        raise NotImplementedError

    def advance_to(self, name: str, value: int) -> int:
        raise NotImplementedError

    def reserve(self, name: str, floor: int = 0) -> int:
        raise NotImplementedError

    def save(self, collection: str, key: str, record: dict[str, Any]) -> None:
        raise NotImplementedError

    def load_record(self, collection: str, key: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def load_all(self, collection: str) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    def delete(self, collection: str, key: str) -> None:
        raise NotImplementedError

    async def areserve(self, name: str, floor: int = 0) -> int:
        return await asyncio.to_thread(self.reserve, name, floor)

    async def aadvance_to(self, name: str, value: int) -> int:
        return await asyncio.to_thread(self.advance_to, name, value)

    async def aload_counter(self, name: str) -> int | None:
        return await asyncio.to_thread(self.load, name)

    async def asave(self, collection: str, key: str, record: dict[str, Any]) -> None:
        await asyncio.to_thread(self.save, collection, key, record)

    async def aload(self, collection: str, key: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.load_record, collection, key)

    async def aload_all(self, collection: str) -> dict[str, dict[str, Any]]:
        return await asyncio.to_thread(self.load_all, collection)

    async def adelete(self, collection: str, key: str) -> None:
        await asyncio.to_thread(self.delete, collection, key)
