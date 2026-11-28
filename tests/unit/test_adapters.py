"""Adapters over DurableCounter / RecordStore and their SF structural conformance."""

import inspect
from dataclasses import asdict, dataclass

import pytest

from state_store import MemoryStateStore, SqliteStateStore, adapters
from state_store.adapters import (
    GroupIdAllocatorAdapter,
    GroupIdHighWaterAdapter,
    LinkedGroupStoreAdapter,
)
from tests import sf_vendored_protocols as sf


def test_state_store_views_type_hints_resolve_at_runtime():
    import typing

    hints = typing.get_type_hints(adapters.StateStoreViews)
    assert set(hints) == {"records", "counters"}


@dataclass
class Rec:
    group_id: int
    note: str


def make_store_adapter(backing, **kwargs):
    return LinkedGroupStoreAdapter(
        backing,
        to_dict=asdict,
        from_dict=lambda d: Rec(**d),
        group_id_of=lambda r: r.group_id,
        **kwargs,
    )


@pytest.mark.unit
def test_group_store_round_trip():
    backing = MemoryStateStore()
    a = make_store_adapter(backing.records)
    assert a.durable is False
    a.save(Rec(1, "x"))
    a.save(Rec(2, "y"))
    a.save(Rec(1, "z"))
    assert sorted(a.load_all(), key=lambda r: r.group_id) == [Rec(1, "z"), Rec(2, "y")]
    assert backing.records.load("linked_groups", "1") == {"group_id": 1, "note": "z"}
    a.delete(1)
    a.delete(1)
    assert a.load_all() == [Rec(2, "y")]


@pytest.mark.unit
def test_group_store_custom_collection_and_durable(tmp_path):
    with SqliteStateStore(tmp_path / "s.db") as backing:
        a = make_store_adapter(backing.records, collection="mine")
        assert a.durable is True
        a.save(Rec(5, "n"))
        assert backing.records.load_all("mine") == {"5": {"group_id": 5, "note": "n"}}
        assert backing.records.load_all("linked_groups") == {}


@pytest.mark.unit
def test_hwm_adapter():
    backing = MemoryStateStore()
    hwm = GroupIdHighWaterAdapter(backing.counters)
    assert hwm.load_group_id_hwm() is None
    hwm.save_group_id_hwm(7)
    hwm.save_group_id_hwm(3)
    assert hwm.load_group_id_hwm() == 7
    assert backing.counters.load("linked_group_id") == 7
    other = GroupIdHighWaterAdapter(backing.counters, name="n2")
    assert other.load_group_id_hwm() is None


@pytest.mark.unit
async def test_allocator_adapter():
    backing = MemoryStateStore()
    alloc = GroupIdAllocatorAdapter(backing.counters)
    assert await alloc.reserve_group_id() == 1
    assert await alloc.reserve_group_id() == 2
    GroupIdHighWaterAdapter(backing.counters).save_group_id_hwm(50)
    assert await alloc.reserve_group_id() == 51


@pytest.mark.unit
def test_hwm_durable_attribute_follows_view(tmp_path):
    assert GroupIdHighWaterAdapter(MemoryStateStore().counters).group_id_hwm_durable is False
    with SqliteStateStore(tmp_path / "s.db") as backing:
        assert GroupIdHighWaterAdapter(backing.counters).group_id_hwm_durable is True


@pytest.mark.unit
def test_hwm_adapter_reads_counter_durable_directly():
    class Fake:
        durable = True

    assert GroupIdHighWaterAdapter(Fake()).group_id_hwm_durable is True  # type: ignore[arg-type]
    with pytest.raises(AttributeError):
        GroupIdHighWaterAdapter(object())  # type: ignore[arg-type]


@pytest.mark.unit
def test_counter_protocol_requires_durable():
    from state_store import DurableCounter

    assert isinstance(inspect.getattr_static(DurableCounter, "durable"), property)


@pytest.mark.unit
async def test_allocator_overflow_does_not_consume_ids():
    from state_store import CounterOverflowError

    backing = MemoryStateStore()
    alloc = GroupIdAllocatorAdapter(backing.counters, max_group_id=2)
    assert await alloc.reserve_group_id() == 1
    assert await alloc.reserve_group_id() == 2
    for _ in range(3):
        with pytest.raises(CounterOverflowError):
            await alloc.reserve_group_id()
    assert backing.counters.load("linked_group_id") == 2


@pytest.mark.unit
async def test_allocator_max_group_id_inclusive():
    from state_store import CounterOverflowError

    alloc = GroupIdAllocatorAdapter(MemoryStateStore().counters, max_group_id=2)
    assert await alloc.reserve_group_id() == 1
    assert await alloc.reserve_group_id() == 2
    with pytest.raises(CounterOverflowError):
        await alloc.reserve_group_id()


@pytest.mark.unit
@pytest.mark.parametrize("bad", [True, 2.0, "5"])
def test_allocator_max_group_id_type_checked(bad):
    with pytest.raises(TypeError):
        GroupIdAllocatorAdapter(MemoryStateStore().counters, max_group_id=bad)


@pytest.mark.unit
async def test_allocator_zero_hwm_then_reserve_is_one():
    backing = MemoryStateStore()
    GroupIdHighWaterAdapter(backing.counters).save_group_id_hwm(0)
    assert GroupIdHighWaterAdapter(backing.counters).load_group_id_hwm() == 0
    assert await GroupIdAllocatorAdapter(backing.counters).reserve_group_id() == 1


@pytest.mark.unit
async def test_allocator_fails_closed(tmp_path):
    backing = SqliteStateStore(tmp_path / "s.db")
    alloc = GroupIdAllocatorAdapter(backing.counters)
    backing.close()
    with pytest.raises(Exception, match="closed"):
        await alloc.reserve_group_id()


@pytest.mark.unit
def test_structural_conformance_runtime():
    backing = MemoryStateStore()
    store = make_store_adapter(backing.records)
    hwm = GroupIdHighWaterAdapter(backing.counters)
    alloc = GroupIdAllocatorAdapter(backing.counters)
    assert isinstance(store, adapters.LinkedGroupStore)
    assert isinstance(hwm, adapters.GroupIdHighWaterStore)
    assert isinstance(alloc, adapters.GroupIdAllocator)
    assert isinstance(store, sf.LinkedGroupStore)
    assert isinstance(hwm, sf.GroupIdHighWaterStore)
    assert isinstance(alloc, sf.GroupIdAllocator)


def _shape(func):
    sig = inspect.signature(func)
    params = [
        (p.name, p.kind, p.default is inspect.Parameter.empty) for p in sig.parameters.values()
    ]
    return params, inspect.iscoroutinefunction(func)


def _members(proto):
    return [n for n, _ in inspect.getmembers(proto, callable) if not n.startswith("_")]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("vendored", "local", "impl"),
    [
        (sf.LinkedGroupStore, adapters.LinkedGroupStore, LinkedGroupStoreAdapter),
        (sf.GroupIdHighWaterStore, adapters.GroupIdHighWaterStore, GroupIdHighWaterAdapter),
        (sf.GroupIdAllocator, adapters.GroupIdAllocator, GroupIdAllocatorAdapter),
    ],
)
def test_signatures_match_vendored_sf(vendored, local, impl):
    names = _members(vendored)
    assert names
    assert _members(local) == names
    for name in names:
        expected = _shape(getattr(vendored, name))
        assert _shape(getattr(local, name)) == expected
        assert _shape(getattr(impl, name)) == expected


@pytest.mark.unit
def test_durable_is_a_property_everywhere():
    for cls in (sf.LinkedGroupStore, adapters.LinkedGroupStore, LinkedGroupStoreAdapter):
        assert isinstance(inspect.getattr_static(cls, "durable"), property)
