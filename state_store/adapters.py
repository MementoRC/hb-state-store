"""Adapters presenting the strategy-framework linked-order store shapes.

Local Protocol copies mirror strategy_framework.linked_orders.protocols (LinkedGroupStore,
GroupIdHighWaterStore, GroupIdAllocator); nothing from strategy_framework is imported.
`GroupId` is a plain `int` alias in SF as well, and 0 is a valid id.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from state_store._common import check_int
from state_store.errors import CounterOverflowError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from state_store.protocols import DurableCounter, RecordStore

GroupId = int


@runtime_checkable
class LinkedGroupStore[TRecord](Protocol):
    @property
    def durable(self) -> bool: ...

    def save(self, record: TRecord) -> None: ...

    def load_all(self) -> Sequence[TRecord]: ...

    def delete(self, group_id: GroupId) -> None: ...


@runtime_checkable
class GroupIdHighWaterStore(Protocol):
    def load_group_id_hwm(self) -> GroupId | None: ...

    def save_group_id_hwm(self, group_id: GroupId) -> None: ...


@runtime_checkable
class GroupIdAllocator(Protocol):
    async def reserve_group_id(self) -> GroupId: ...


class LinkedGroupStoreAdapter[TRecord]:
    """Group records in a RecordStore collection, keyed by `str(group_id)`.

    The codec (`to_dict`/`from_dict`) is injected by the composition layer.
    """

    def __init__(
        self,
        store: RecordStore,
        *,
        to_dict: Callable[[TRecord], dict[str, Any]],
        from_dict: Callable[[dict[str, Any]], TRecord],
        group_id_of: Callable[[TRecord], GroupId],
        collection: str = "linked_groups",
    ) -> None:
        self._store = store
        self._to_dict = to_dict
        self._from_dict = from_dict
        self._group_id_of = group_id_of
        self._collection = collection

    @property
    def durable(self) -> bool:
        return self._store.durable

    def save(self, record: TRecord) -> None:
        key = str(self._group_id_of(record))
        self._store.save(self._collection, key, self._to_dict(record))

    def load_all(self) -> Sequence[TRecord]:
        return [self._from_dict(d) for d in self._store.load_all(self._collection).values()]

    def delete(self, group_id: GroupId) -> None:
        self._store.delete(self._collection, str(group_id))


class GroupIdHighWaterAdapter:
    """High-water mark over a DurableCounter (max-only, durable before return)."""

    def __init__(self, counter: DurableCounter, *, name: str = "linked_group_id") -> None:
        self._counter = counter
        self._name = name
        self.group_id_hwm_durable: bool = bool(getattr(counter, "durable", False))

    def load_group_id_hwm(self) -> GroupId | None:
        return self._counter.load(self._name)

    def save_group_id_hwm(self, group_id: GroupId) -> None:
        self._counter.advance_to(self._name, group_id)


class GroupIdAllocatorAdapter:
    """Reserves group ids from a DurableCounter off the event loop; errors propagate."""

    def __init__(
        self,
        counter: DurableCounter,
        *,
        name: str = "linked_group_id",
        max_group_id: int | None = None,
    ) -> None:
        self._counter = counter
        self._name = name
        if max_group_id is not None:
            check_int(max_group_id, "max_group_id")
        self._max = max_group_id

    async def reserve_group_id(self) -> GroupId:
        value = await asyncio.to_thread(self._counter.reserve, self._name, 1)
        if self._max is not None and value > self._max:
            raise CounterOverflowError(f"group id {value} exceeds max_group_id {self._max}")
        return value
