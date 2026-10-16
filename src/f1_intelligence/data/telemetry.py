"""Optional session telemetry extraction."""

from typing import Any

import pandas as pd


def extract_telemetry(session: Any) -> pd.DataFrame:
    """Copy telemetry for loaded laps; availability varies by session."""
    telemetry = session.laps.get_telemetry()
    if not isinstance(telemetry, pd.DataFrame):
        raise TypeError("FastF1 telemetry is not tabular")
    return telemetry.copy()
