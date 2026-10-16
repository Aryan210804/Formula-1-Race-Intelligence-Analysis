"""Weather observation extraction."""

from typing import Any

import pandas as pd


def extract_weather(session: Any) -> pd.DataFrame:
    """Copy FastF1 weather observations when the session provides them."""
    weather = session.weather_data
    if not isinstance(weather, pd.DataFrame):
        raise TypeError("FastF1 weather observations are not tabular")
    return weather.copy()
