"""Shared fixtures for the test suite."""

from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    """Return the repository root for tests that need project files."""
    return Path(__file__).resolve().parents[1]
