"""Smoke tests for hb-state-store: verifies the package imports and version is set."""

import json
import re
from pathlib import Path

import pytest

import state_store
from state_store import __version__


@pytest.mark.unit
def test_package_importable() -> None:
    """Package imports without error."""
    assert state_store is not None


@pytest.mark.unit
def test_version() -> None:
    """__version__ equals the "." entry of .release-please-manifest.json and is X.Y.Z."""
    manifest = Path(__file__).resolve().parents[1] / ".release-please-manifest.json"
    expected = json.loads(manifest.read_text(encoding="utf-8"))["."]
    assert __version__ == expected
    assert re.match(r"^\d+\.\d+\.\d+$", __version__)
