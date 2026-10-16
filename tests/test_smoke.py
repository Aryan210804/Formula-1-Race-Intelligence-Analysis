"""Offline smoke tests for the initial package bootstrap."""

import f1_intelligence
from f1_intelligence import analytics, data, exports, storage, transformations


def test_package_and_components_import() -> None:
    """The package and its initial component modules import without data access."""
    assert f1_intelligence.__version__ == "0.1.0"
    assert all(
        module is not None
        for module in (analytics, data, exports, storage, transformations)
    )
