"""Exception hierarchy for state_store."""


class StateStoreError(Exception):
    """Base class for all state_store errors."""


class SchemaVersionError(StateStoreError):
    """The on-disk schema version is newer than this code supports."""


class CounterOverflowError(StateStoreError):
    """A counter value would exceed 2**63 - 1."""


class RecordSerializationError(StateStoreError):
    """A record is not JSON-serialisable."""
