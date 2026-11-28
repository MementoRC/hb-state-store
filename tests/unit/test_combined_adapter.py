"""LinkedGroupStateAdapter: one object satisfying both SF linked-order store protocols."""

import inspect
from dataclasses import asdict, dataclass

import pytest

from state_store import MemoryStateStore, SqliteStateStore
from state_store.adapters import LinkedGroupStateAdapter, StateStoreViews
from tests import sf_vendored_protocols as sf


@dataclass
class Rec:
    group_id: int
    note: str


def make(state, **kwargs):
    return LinkedGroupStateAdapter(
        state,
        to_dict=asdict,
        from_dict=lambda d: Rec(**d),
        group_id_of=lambda r: r.group_id,
        **kwargs,
    )


@pytest.mark.unit
def test_stores_satisfy_views_protocol(tmp_path):
    assert isinstance(MemoryStateStore(), StateStoreViews)
    with SqliteStateStore(tmp_path / "s.db") as s:
        assert isinstance(s, StateStoreViews)


@pytest.mark.unit
def test_satisfies_both_vendored_protocols():
    a = make(MemoryStateStore())
    assert isinstance(a, sf.LinkedGroupStore)
    assert isinstance(a, sf.GroupIdHighWaterStore)


@pytest.mark.unit
@pytest.mark.parametrize("proto", [sf.LinkedGroupStore, sf.GroupIdHighWaterStore])
def test_signatures_match_vendored(proto):
    def shape(func):
        params = inspect.signature(func).parameters.values()
        return [(p.name, p.kind, p.default is p.empty) for p in params]

    names = [n for n, _ in inspect.getmembers(proto, callable) if not n.startswith("_")]
    assert names
    for name in names:
        assert shape(getattr(LinkedGroupStateAdapter, name)) == shape(getattr(proto, name))
    assert isinstance(inspect.getattr_static(LinkedGroupStateAdapter, "durable"), property)


@pytest.mark.unit
def test_durable_follows_store(tmp_path):
    assert make(MemoryStateStore()).durable is False
    with SqliteStateStore(tmp_path / "s.db") as s:
        assert make(s).durable is True


@pytest.mark.unit
def test_record_round_trip():
    a = make(MemoryStateStore())
    a.save(Rec(1, "x"))
    a.save(Rec(2, "y"))
    a.save(Rec(1, "z"))
    assert sorted(a.load_all(), key=lambda r: r.group_id) == [Rec(1, "z"), Rec(2, "y")]
    a.delete(1)
    assert a.load_all() == [Rec(2, "y")]


@pytest.mark.unit
def test_hwm_max_only_and_none_initially():
    a = make(MemoryStateStore())
    assert a.load_group_id_hwm() is None
    a.save_group_id_hwm(7)
    a.save_group_id_hwm(3)
    assert a.load_group_id_hwm() == 7


@pytest.mark.unit
def test_durable_before_return(tmp_path):
    path = tmp_path / "s.db"
    store = SqliteStateStore(path)
    a = make(store)
    a.save_group_id_hwm(9)
    a.save(Rec(9, "n"))
    store.close()
    with SqliteStateStore(path) as reopened:
        b = make(reopened)
        assert b.load_group_id_hwm() == 9
        assert b.load_all() == [Rec(9, "n")]


@pytest.mark.unit
def test_no_group_id_hwm_durable_attribute():
    assert not hasattr(make(MemoryStateStore()), "group_id_hwm_durable")


@pytest.mark.unit
def test_shared_store_independent_names():
    state = MemoryStateStore()
    a = make(state, collection="mine", name="my_hwm")
    a.save(Rec(4, "n"))
    a.save_group_id_hwm(4)
    assert state.records.load_all("mine") == {"4": {"group_id": 4, "note": "n"}}
    assert state.records.load_all("linked_groups") == {}
    assert state.counters.load("my_hwm") == 4
    assert state.counters.load("linked_group_id") is None
