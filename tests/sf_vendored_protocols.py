"""Vendored text copy of the strategy-framework linked_orders protocol signatures.

Source: strategy-framework `development` @ e57b3eb,
strategy_framework/linked_orders/protocols.py (LinkedGroupStore, GroupIdHighWaterStore,
GroupIdAllocator). UPDATE THIS FILE (and the adapters) whenever SF changes these protocols.
Copied by hand, with `GroupId` (a NewType over int there) and `GroupRecord`
replaced by plain types. NEVER import strategy_framework from state_store or its tests; when the
SF signatures change, update this file and the adapters together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

GroupId = int
GroupRecord = Any


@runtime_checkable
class LinkedGroupStore(Protocol):
    @property
    def durable(self) -> bool: ...

    def save(self, record: GroupRecord) -> None: ...

    def load_all(self) -> Sequence[GroupRecord]: ...

    def delete(self, group_id: GroupId) -> None: ...


@runtime_checkable
class GroupIdHighWaterStore(Protocol):
    def load_group_id_hwm(self) -> GroupId | None: ...

    def save_group_id_hwm(self, group_id: GroupId) -> None: ...


@runtime_checkable
class GroupIdAllocator(Protocol):
    async def reserve_group_id(self) -> GroupId: ...
