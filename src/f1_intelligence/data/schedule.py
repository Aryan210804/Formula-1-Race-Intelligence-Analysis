"""Season schedule retrieval and event selection."""

from typing import Any

import pandas as pd

from f1_intelligence.data.retry import RequestController


def get_season_schedule(
    source: Any, controller: RequestController, season: int
) -> pd.DataFrame:
    """Retrieve a season schedule and exclude pre-season testing events."""
    schedule = controller.call(
        lambda: source.get_event_schedule(season),
        f"schedule retrieval for season {season}",
    )
    if not isinstance(schedule, pd.DataFrame):
        raise TypeError(f"FastF1 returned a non-tabular schedule for {season}")
    return schedule.copy()


def select_event(schedule: pd.DataFrame, event_selector: str) -> pd.Series:
    """Select one event by exact name (case-insensitive) or round number."""
    selector = event_selector.strip()
    if not selector:
        raise ValueError("Event selection cannot be empty")
    if selector.isdecimal():
        if "RoundNumber" not in schedule:
            raise ValueError("Schedule has no RoundNumber column")
        matches = schedule.loc[
            pd.to_numeric(schedule["RoundNumber"], errors="coerce") == int(selector)
        ]
    else:
        if "EventName" not in schedule:
            raise ValueError("Schedule has no EventName column")
        matches = schedule.loc[
            schedule["EventName"].astype(str).str.casefold()
            == selector.casefold()
        ]
    if len(matches) != 1:
        raise ValueError(
            f"Event selector {event_selector!r} matched {len(matches)} events"
        )
    return matches.iloc[0]
