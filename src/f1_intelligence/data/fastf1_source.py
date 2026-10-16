"""Thin, lazy-loaded adapter around FastF1's supported public API."""

from pathlib import Path
from typing import Any


class FastF1Source:
    """Configure FastF1 caching and expose schedule/session retrieval."""

    def __init__(self, cache_path: Path) -> None:
        try:
            import fastf1
        except ImportError as exc:
            raise RuntimeError(
                "FastF1 is required for ingestion. Install the project with "
                '`python -m pip install -e ".[dev]"`.'
            ) from exc
        cache_path.mkdir(parents=True, exist_ok=True)
        fastf1.Cache.enable_cache(str(cache_path))
        self._fastf1: Any = fastf1

    def get_event_schedule(self, season: int) -> Any:
        """Fetch the official event schedule for a season, excluding tests."""
        return self._fastf1.get_event_schedule(season, include_testing=False)

    def get_session(self, season: int, event_round: int, session_code: str) -> Any:
        """Create a FastF1 session handle for an event round and session code."""
        return self._fastf1.get_session(season, event_round, session_code)
