"""Storage abstraction for normalized analytical records."""

from typing import Any, Protocol


class DataStore(Protocol):
    """Interface implemented by local or remote analytical stores."""

    def load_bundle(
        self,
        tables: dict[str, list[dict[str, Any]]],
        rejected_records: list[dict[str, Any]],
        quality_issues: list[dict[str, Any]],
        *,
        rebuild: bool = True,
    ) -> dict[str, int]:
        """Persist one normalized bundle idempotently and report table counts."""
