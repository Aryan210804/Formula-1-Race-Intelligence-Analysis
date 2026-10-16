"""Race and qualifying classification extraction."""

from typing import Any

import pandas as pd


def extract_results(session: Any) -> pd.DataFrame:
    """Copy FastF1's session results without inventing missing classifications."""
    results = session.results
    if not isinstance(results, pd.DataFrame):
        raise TypeError("FastF1 session results are not tabular")
    return results.copy()
