"""Reusable metrics and database access for the F1 dashboard."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable

import pandas as pd

from f1_intelligence.paths import DEFAULT_DATABASE_PATH


CORE_TABLES = ("circuits", "races", "drivers", "constructors", "status", "results")
OPTIONAL_TABLES = (
    "constructor_results",
    "constructor_standings",
    "driver_standings",
    "pit_stops",
    "weather_tyre",
    "lap_times",
    "qualifying",
)
REQUIRED_COLUMNS = {
    "circuits": {"circuitId", "name", "country"},
    "races": {"raceId", "year", "round", "name", "date", "circuitId"},
    "drivers": {"driverId", "forename", "surname", "nationality"},
    "constructors": {"constructorId", "name"},
    "status": {"statusId", "status"},
    "results": {
        "raceId",
        "driverId",
        "constructorId",
        "positionOrder",
        "points",
        "statusId",
    },
    "constructor_results": {"raceId", "constructorId", "points"},
    "constructor_standings": {"raceId", "constructorId", "points"},
    "driver_standings": {"raceId", "driverId", "points"},
    "pit_stops": {"raceId", "driverId", "stop", "milliseconds"},
    "weather_tyre": {"year", "Compound", "lap", "milliseconds"},
    "lap_times": {"raceId", "milliseconds"},
    "qualifying": {"raceId", "driverId", "constructorId", "position"},
}


def load_tables(
    database: Path = DEFAULT_DATABASE_PATH,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Read and validate known tables without modifying the SQLite database."""
    database = database.resolve()
    if not database.is_file():
        raise FileNotFoundError(
            f"Analytical database not found: {database}"
        )
    tables: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    uri = f"{database.as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            check_results = [row[0] for row in connection.execute("PRAGMA quick_check")]
            if check_results != ["ok"]:
                raise ValueError(
                    f"SQLite integrity check failed for {database}: "
                    f"{'; '.join(check_results[:5])}"
                )
            existing = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            absent_core = set(CORE_TABLES) - existing
            if absent_core:
                raise ValueError(
                    f"Database is missing required analytical tables: "
                    f"{sorted(absent_core)}"
                )
            for name in (*CORE_TABLES, *OPTIONAL_TABLES):
                if name not in existing:
                    missing.append(name)
                    continue
                columns = {
                    row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')
                }
                absent_columns = REQUIRED_COLUMNS[name] - columns
                if absent_columns:
                    raise ValueError(
                        f"Database table '{name}' is missing required columns: "
                        f"{sorted(absent_columns)}"
                    )
                tables[name] = pd.read_sql_query(
                    f'SELECT * FROM "{name}"', connection
                )
    except sqlite3.DatabaseError as exc:
        raise ValueError(
            f"Unable to read analytical SQLite database at {database}: {exc}"
        ) from exc
    return tables, missing


def race_results(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Join each race-entry fact to its single race, driver, team and status records."""
    results = tables["results"]
    races = tables["races"]
    drivers = tables["drivers"]
    constructors = tables["constructors"]
    status = tables["status"]
    if races["raceId"].duplicated().any() or drivers["driverId"].duplicated().any():
        raise ValueError("Race and driver dimensions must have unique identifiers")
    if constructors["constructorId"].duplicated().any() or status["statusId"].duplicated().any():
        raise ValueError("Constructor and status dimensions must have unique identifiers")
    merged = results.merge(
        races[["raceId", "year", "round", "name", "date", "circuitId"]].rename(
            columns={"name": "grand_prix"}
        ),
        on="raceId",
        how="left",
        validate="many_to_one",
    )
    if "circuits" in tables:
        merged = merged.merge(
            tables["circuits"][["circuitId", "name", "country"]].rename(
                columns={"name": "circuit", "country": "country"}
            ),
            on="circuitId",
            how="left",
            validate="many_to_one",
        )
    merged = merged.merge(
        drivers[["driverId", "forename", "surname", "nationality"]],
        on="driverId",
        how="left",
        validate="many_to_one",
    )
    merged = merged.merge(
        constructors[["constructorId", "name"]].rename(columns={"name": "constructor"}),
        on="constructorId",
        how="left",
        validate="many_to_one",
    )
    merged = merged.merge(status[["statusId", "status"]], on="statusId", how="left", validate="many_to_one")
    if len(merged) != len(results):
        raise ValueError("Dimension enrichment changed the race-entry row count")
    merged["driver"] = (merged["forename"].fillna("") + " " + merged["surname"].fillna("")).str.strip()
    merged["finish_position"] = pd.to_numeric(merged["positionOrder"], errors="coerce")
    merged["points"] = pd.to_numeric(merged["points"], errors="coerce")
    merged["season"] = pd.to_numeric(merged["year"], errors="coerce").astype("Int64")
    return merged


def apply_filters(
    frame: pd.DataFrame,
    *,
    years: tuple[int, int] | None = None,
    drivers: Iterable[str] = (),
    constructors: Iterable[str] = (),
    countries: Iterable[str] = (),
    statuses: Iterable[str] = (),
    circuits: Iterable[str] = (),
) -> pd.DataFrame:
    """Filter a result-grain frame only on columns actually present in that frame."""
    filtered = frame
    if years and "year" in filtered:
        filtered = filtered[filtered["year"].between(*years)]
    for column, values in (
        ("driver", drivers),
        ("constructor", constructors),
        ("country", countries),
        ("status", statuses),
        ("circuit", circuits),
    ):
        selected = list(values)
        if selected and column in filtered:
            filtered = filtered[filtered[column].isin(selected)]
    return filtered.copy()


def driver_performance(frame: pd.DataFrame) -> pd.DataFrame:
    """Summarize race entries; podiums/wins count classified positions, not events."""
    if frame.empty:
        return pd.DataFrame(
            columns=["driver", "points", "wins", "podiums", "average_finish", "entries"]
        )
    summary = (
        frame.groupby("driver", as_index=False, dropna=False)
        .agg(
            points=("points", "sum"),
            wins=("finish_position", lambda values: int((values == 1).sum())),
            podiums=("finish_position", lambda values: int(values.between(1, 3).sum())),
            average_finish=("finish_position", "mean"),
            entries=("raceId", "size"),
        )
        .sort_values(["points", "wins", "driver"], ascending=[False, False, True])
    )
    return summary


def constructor_performance(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return official constructor championship points by season from constructor_results."""
    if "constructor_results" not in tables:
        return pd.DataFrame(columns=["constructor", "year", "points"])
    facts = tables["constructor_results"].merge(
        tables["races"][["raceId", "year"]], on="raceId", how="left", validate="many_to_one"
    ).merge(
        tables["constructors"][["constructorId", "name"]],
        on="constructorId",
        how="left",
        validate="many_to_one",
    )
    return (
        facts.groupby(["name", "year"], as_index=False)
        .agg(points=("points", "sum"))
        .rename(columns={"name": "constructor"})
        .sort_values(["year", "points"], ascending=[True, False])
    )


def classify_finish(status: pd.Series) -> pd.Series:
    """Classify official status labels; 'Finished' and '+N Lap(s)' count as classified."""
    normalized = status.fillna("").astype(str).str.strip()
    return normalized.eq("Finished") | normalized.str.contains(r"\+\s*\d+\s*Lap", case=False, regex=True)


def reliability_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Calculate classified-finish rate using race entries as its denominator."""
    if frame.empty:
        return pd.DataFrame(columns=["status", "entries", "classified_finishes"])
    finished = classify_finish(frame["status"])
    result = frame.assign(classified_finish=finished)
    return (
        result.groupby("status", dropna=False, as_index=False)
        .agg(entries=("raceId", "size"), classified_finishes=("classified_finish", "sum"))
        .sort_values("entries", ascending=False)
    )


def country_race_counts(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Count unique scheduled Grands Prix by host country using circuit metadata."""
    if "circuits" not in tables:
        return pd.DataFrame(columns=["country", "races"])
    return (
        tables["races"].merge(
            tables["circuits"][["circuitId", "country"]],
            on="circuitId",
            how="left",
            validate="many_to_one",
        )
        .groupby("country", as_index=False)
        .agg(races=("raceId", "nunique"))
        .sort_values("races", ascending=False)
    )


def pit_stop_summary(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Enrich stop events; team is attributed only for unique driver-race result keys."""
    if "pit_stops" not in tables:
        return pd.DataFrame()
    stops = tables["pit_stops"].merge(
        tables["races"][["raceId", "year", "name"]],
        on="raceId",
        how="left",
        validate="many_to_one",
    ).merge(
        tables["drivers"][["driverId", "forename", "surname"]],
        on="driverId",
        how="left",
        validate="many_to_one",
    )
    race_driver_counts = (
        tables["results"].groupby(["raceId", "driverId"], as_index=False)
        .size()
        .rename(columns={"size": "result_rows"})
    )
    unique_pairs = race_driver_counts.loc[race_driver_counts["result_rows"] == 1, ["raceId", "driverId"]]
    constructor_map = (
        tables["results"]
        .merge(unique_pairs, on=["raceId", "driverId"], how="inner", validate="many_to_one")
        [["raceId", "driverId", "constructorId"]]
        .merge(
            tables["constructors"][["constructorId", "name"]].rename(
                columns={"name": "constructor"}
            ),
            on="constructorId",
            how="left",
            validate="many_to_one",
        )
    )
    before = len(stops)
    stops = stops.merge(
        constructor_map,
        on=["raceId", "driverId"],
        how="left",
        validate="many_to_one",
    )
    if len(stops) != before:
        raise ValueError("Team attribution changed the pit-stop event row count")
    stops["duration_ms"] = pd.to_numeric(stops["milliseconds"], errors="coerce")
    stops["driver"] = (stops["forename"].fillna("") + " " + stops["surname"].fillna("")).str.strip()
    return stops


def tyre_summary(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Summarize observed tyre-compound laps without joining to a different data grain."""
    if "weather_tyre" not in tables:
        return pd.DataFrame()
    frame = tables["weather_tyre"]
    return (
        frame.groupby(["year", "Compound"], dropna=False, as_index=False)
        .agg(
            laps=("lap", "size"),
            mean_lap_ms=("milliseconds", "mean"),
            mean_air_temp=("AirTemp", "mean"),
            mean_track_temp=("TrackTemp", "mean"),
            wet_laps=("Rainfall", "sum"),
        )
        .sort_values(["year", "Compound"])
    )
