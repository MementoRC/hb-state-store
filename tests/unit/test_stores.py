"""Behaviour shared by MemoryStateStore and SqliteStateStore views."""

import pytest

from state_store import (
    CounterOverflowError,
    DurableCounter,
    MemoryStateStore,
    RecordSerializationError,
    RecordStore,
    SqliteStateStore,
    StateStoreError,
)

INT64_MAX = 2**63 - 1


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        yield MemoryStateStore()
    else:
        s = SqliteStateStore(tmp_path / "s.db")
        yield s
        s.close()


@pytest.fixture
def counters(store):
    return store.counters


@pytest.fixture
def records(store):
    return store.records


@pytest.mark.unit
def test_views_conform_and_store_is_not_both(store):
    assert isinstance(store.counters, DurableCounter)
    assert isinstance(store.records, RecordStore)
    assert not isinstance(store, RecordStore)


@pytest.mark.unit
def test_durable_flags(store):
    expected = isinstance(store, SqliteStateStore)
    assert store.durable is expected
    assert store.counters.durable is expected
    assert store.records.durable is expected


@pytest.mark.unit
def test_error_hierarchy():
    assert issubclass(CounterOverflowError, StateStoreError)
    assert issubclass(RecordSerializationError, StateStoreError)


@pytest.mark.unit
def test_views_share_one_store(store):
    store.counters.reserve("c")
    store.records.save("col", "k", {"v": 1})
    assert store.counters.load("c") == 1
    assert store.records.load("col", "k") == {"v": 1}


@pytest.mark.unit
def test_counter_unset_until_used(counters):
    assert counters.load("c") is None


@pytest.mark.unit
def test_first_reserve_is_one(counters):
    assert counters.reserve("c") == 1
    assert counters.load("c") == 1


@pytest.mark.unit
def test_reserve_floor(counters):
    assert counters.reserve("c", 10) == 10
    assert counters.reserve("c", 3) == 11
    assert counters.reserve("c") == 12
    assert counters.reserve("c", 100) == 100


@pytest.mark.unit
def test_reserve_floor_zero_on_unset_returns_one(counters):
    assert counters.reserve("c", 0) == 1


@pytest.mark.unit
def test_counters_are_independent(counters):
    counters.reserve("a")
    counters.reserve("a")
    assert counters.reserve("b") == 1


@pytest.mark.unit
def test_advance_to_never_goes_backwards(counters):
    assert counters.advance_to("c", 5) == 5
    assert counters.advance_to("c", 3) == 5
    assert counters.load("c") == 5
    assert counters.advance_to("c", 9) == 9
    assert counters.reserve("c") == 10


@pytest.mark.unit
def test_advance_to_zero_sets_counter(counters):
    assert counters.advance_to("c", 0) == 0
    assert counters.load("c") == 0
    assert counters.reserve("c") == 1


@pytest.mark.unit
def test_negative_values_rejected(counters):
    with pytest.raises(ValueError, match="negative"):
        counters.advance_to("c", -1)
    with pytest.raises(ValueError, match="negative"):
        counters.reserve("c", -1)
    assert counters.load("c") is None


@pytest.mark.unit
@pytest.mark.parametrize("bad", [True, False, 1.5, "3", None])
def test_non_int_values_rejected(counters, bad):
    with pytest.raises(TypeError):
        counters.advance_to("c", bad)
    with pytest.raises(TypeError):
        counters.reserve("c", bad)
    assert counters.load("c") is None


@pytest.mark.unit
def test_overflow_rejected_and_store_still_usable(counters):
    assert counters.advance_to("c", INT64_MAX) == INT64_MAX
    with pytest.raises(CounterOverflowError):
        counters.reserve("c")
    with pytest.raises(CounterOverflowError):
        counters.advance_to("c", INT64_MAX + 1)
    with pytest.raises(CounterOverflowError):
        counters.reserve("other", INT64_MAX + 1)
    assert counters.load("c") == INT64_MAX
    assert counters.reserve("other") == 1


@pytest.mark.unit
def test_record_round_trip(records):
    record = {"a": 1, "b": [1, 2, {"c": None}], "u": "café ☃", "f": 1.5}
    records.save("col", "k", record)
    assert records.load("col", "k") == record
    assert records.load("col", "missing") is None
    assert records.load("other", "k") is None


@pytest.mark.unit
def test_save_is_upsert(records):
    records.save("col", "k", {"v": 1})
    records.save("col", "k", {"v": 2})
    assert records.load_all("col") == {"k": {"v": 2}}


@pytest.mark.unit
def test_load_all_scoped_to_collection(records):
    records.save("one", "a", {"x": 1})
    records.save("one", "b", {"x": 2})
    records.save("two", "a", {"x": 3})
    assert records.load_all("one") == {"a": {"x": 1}, "b": {"x": 2}}
    assert records.load_all("two") == {"a": {"x": 3}}
    assert records.load_all("none") == {}


@pytest.mark.unit
def test_delete_is_idempotent(records):
    records.save("col", "k", {"v": 1})
    records.delete("col", "k")
    records.delete("col", "k")
    records.delete("col", "never")
    assert records.load("col", "k") is None


@pytest.mark.unit
def test_records_are_copied(records):
    record = {"nested": {"v": 1}}
    records.save("col", "k", record)
    record["nested"]["v"] = 99
    loaded = records.load("col", "k")
    assert loaded == {"nested": {"v": 1}}
    loaded["nested"]["v"] = 42
    assert records.load("col", "k") == {"nested": {"v": 1}}


BAD_RECORDS = [
    {"s": {1, 2}},
    {"n": float("nan")},
    {"i": float("inf")},
    {"o": object()},
    {1: "int key"},
    {"nested": {2: "x"}},
    {"in_list": [{"ok": 1}, {3: "x"}]},
    {"in_tuple": ({None: 1},)},
]


@pytest.mark.unit
@pytest.mark.parametrize("bad", BAD_RECORDS)
def test_non_json_record_rejected_without_write(records, bad):
    records.save("col", "k", {"ok": True})
    with pytest.raises(RecordSerializationError):
        records.save("col", "k", bad)
    with pytest.raises(RecordSerializationError):
        records.save("col", "new", bad)
    assert records.load_all("col") == {"k": {"ok": True}}


@pytest.mark.unit
def test_circular_record_rejected(records):
    record = {}
    record["self"] = record
    with pytest.raises(RecordSerializationError):
        records.save("col", "k", record)
    assert records.load_all("col") == {}


@pytest.mark.unit
def test_circular_list_record_rejected(records):
    loop = []
    loop.append(loop)
    with pytest.raises(RecordSerializationError):
        records.save("col", "k", {"loop": loop})


@pytest.mark.unit
def test_too_deeply_nested_record_rejected(records):
    deep = {}
    cursor = deep
    for _ in range(5000):
        cursor["n"] = {}
        cursor = cursor["n"]
    with pytest.raises(RecordSerializationError):
        records.save("col", "k", deep)
    assert records.load_all("col") == {}


@pytest.mark.unit
async def test_async_counter_wrappers(counters):
    assert await counters.aload("c") is None
    assert await counters.areserve("c") == 1
    assert await counters.areserve("c", 7) == 7
    assert await counters.aadvance_to("c", 3) == 7
    assert await counters.aload("c") == 7


@pytest.mark.unit
async def test_async_record_wrappers(records):
    await records.asave("col", "k", {"v": 1})
    assert await records.aload("col", "k") == {"v": 1}
    assert await records.aload_all("col") == {"k": {"v": 1}}
    await records.adelete("col", "k")
    assert await records.aload("col", "k") is None


@pytest.mark.unit
def test_memory_close_is_noop():
    MemoryStateStore().close()
