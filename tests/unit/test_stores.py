"""Behaviour shared by MemoryStateStore and SqliteStateStore."""

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


@pytest.mark.unit
def test_protocol_conformance(store):
    assert isinstance(store, DurableCounter)
    assert isinstance(store, RecordStore)


@pytest.mark.unit
def test_durable_flag(store):
    assert store.durable is isinstance(store, SqliteStateStore)


@pytest.mark.unit
def test_error_hierarchy():
    assert issubclass(CounterOverflowError, StateStoreError)
    assert issubclass(RecordSerializationError, StateStoreError)


@pytest.mark.unit
def test_counter_unset_until_used(store):
    assert store.load("c") is None


@pytest.mark.unit
def test_first_reserve_is_one(store):
    assert store.reserve("c") == 1
    assert store.load("c") == 1


@pytest.mark.unit
def test_reserve_floor(store):
    assert store.reserve("c", 10) == 10
    assert store.reserve("c", 3) == 11
    assert store.reserve("c") == 12
    assert store.reserve("c", 100) == 100


@pytest.mark.unit
def test_reserve_floor_zero_on_unset_returns_one(store):
    assert store.reserve("c", 0) == 1


@pytest.mark.unit
def test_counters_are_independent(store):
    store.reserve("a")
    store.reserve("a")
    assert store.reserve("b") == 1


@pytest.mark.unit
def test_advance_to_never_goes_backwards(store):
    assert store.advance_to("c", 5) == 5
    assert store.advance_to("c", 3) == 5
    assert store.load("c") == 5
    assert store.advance_to("c", 9) == 9
    assert store.reserve("c") == 10


@pytest.mark.unit
def test_advance_to_zero_sets_counter(store):
    assert store.advance_to("c", 0) == 0
    assert store.load("c") == 0
    assert store.reserve("c") == 1


@pytest.mark.unit
def test_negative_values_rejected(store):
    with pytest.raises(ValueError, match="negative"):
        store.advance_to("c", -1)
    with pytest.raises(ValueError, match="negative"):
        store.reserve("c", -1)
    assert store.load("c") is None


@pytest.mark.unit
def test_overflow_rejected_and_store_still_usable(store):
    assert store.advance_to("c", INT64_MAX) == INT64_MAX
    with pytest.raises(CounterOverflowError):
        store.reserve("c")
    with pytest.raises(CounterOverflowError):
        store.advance_to("c", INT64_MAX + 1)
    with pytest.raises(CounterOverflowError):
        store.reserve("other", INT64_MAX + 1)
    assert store.load("c") == INT64_MAX
    assert store.reserve("other") == 1


@pytest.mark.unit
def test_record_round_trip(store):
    record = {"a": 1, "b": [1, 2, {"c": None}], "u": "café ☃", "f": 1.5}
    store.save("col", "k", record)
    assert store.load_record("col", "k") == record
    assert store.load_record("col", "missing") is None
    assert store.load_record("other", "k") is None


@pytest.mark.unit
def test_save_is_upsert(store):
    store.save("col", "k", {"v": 1})
    store.save("col", "k", {"v": 2})
    assert store.load_all("col") == {"k": {"v": 2}}


@pytest.mark.unit
def test_load_all_scoped_to_collection(store):
    store.save("one", "a", {"x": 1})
    store.save("one", "b", {"x": 2})
    store.save("two", "a", {"x": 3})
    assert store.load_all("one") == {"a": {"x": 1}, "b": {"x": 2}}
    assert store.load_all("two") == {"a": {"x": 3}}
    assert store.load_all("none") == {}


@pytest.mark.unit
def test_delete_is_idempotent(store):
    store.save("col", "k", {"v": 1})
    store.delete("col", "k")
    store.delete("col", "k")
    store.delete("col", "never")
    assert store.load_record("col", "k") is None


@pytest.mark.unit
def test_records_are_copied(store):
    record = {"nested": {"v": 1}}
    store.save("col", "k", record)
    record["nested"]["v"] = 99
    loaded = store.load_record("col", "k")
    assert loaded == {"nested": {"v": 1}}
    loaded["nested"]["v"] = 42
    assert store.load_record("col", "k") == {"nested": {"v": 1}}


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad", [{"s": {1, 2}}, {"n": float("nan")}, {"i": float("inf")}, {"o": object()}]
)
def test_non_json_record_rejected_without_write(store, bad):
    store.save("col", "k", {"ok": True})
    with pytest.raises(RecordSerializationError):
        store.save("col", "k", bad)
    with pytest.raises(RecordSerializationError):
        store.save("col", "new", bad)
    assert store.load_all("col") == {"k": {"ok": True}}


@pytest.mark.unit
def test_circular_record_rejected(store):
    record = {}
    record["self"] = record
    with pytest.raises(RecordSerializationError):
        store.save("col", "k", record)


@pytest.mark.unit
async def test_async_wrappers(store):
    assert await store.aload_counter("c") is None
    assert await store.areserve("c") == 1
    assert await store.areserve("c", 7) == 7
    assert await store.aadvance_to("c", 3) == 7
    assert await store.aload_counter("c") == 7
    await store.asave("col", "k", {"v": 1})
    assert await store.aload("col", "k") == {"v": 1}
    assert await store.aload_all("col") == {"k": {"v": 1}}
    await store.adelete("col", "k")
    assert await store.aload("col", "k") is None
