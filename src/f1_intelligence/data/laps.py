"""Lap timing and source-backed pit-stop extraction."""

from typing import Any

import pandas as pd


def extract_laps(session: Any) -> pd.DataFrame:
    """Copy available lap timing fields from the loaded FastF1 session."""
    laps = session.laps
    if not isinstance(laps, pd.DataFrame):
        raise TypeError("FastF1 lap timing data is not tabular")
    return laps.copy()


def extract_pit_stops(laps: pd.DataFrame) -> pd.DataFrame:
    """Select laps with source pit-in or pit-out timestamps, if supplied."""
    pit_columns = [
        column for column in ("PitInTime", "PitOutTime") if column in laps.columns
    ]
    if not pit_columns:
        return pd.DataFrame(columns=list(laps.columns))
    available = laps[pit_columns].notna().any(axis=1)
    return laps.loc[available].copy()
