"""Smoke tests for hb-state-store: verifies the package imports and version is set."""

import pytest

import state_store
from state_store import __version__


@pytest.mark.unit
def test_package_importable() -> None:
    """Package imports without error."""
    assert state_store is not None


@pytest.mark.unit
def test_version() -> None:
    """__version__ is the bootstrap version."""
    assert __version__ == "0.0.0"
