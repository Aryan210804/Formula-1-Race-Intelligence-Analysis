"""Export analysis tables with documented row grain for Tableau."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Sequence

import pandas as pd

from f1_intelligence.analytics import (
    constructor_performance,
    country_race_counts,
    load_tables,
    pit_stop_summary,
    race_results,
)
from f1_intelligence.paths import (
    DEFAULT_DATABASE_PATH,
    PROJECT_ROOT,
    resolve_project_path,
)

DICTIONARIES = {
    "race_summary": (
        "One row per historical Grand Prix. entries is the number of result rows; "
        "podium_finishes counts result rows with positionOrder 1-3.",
        "Source: races, results, circuits.",
    ),
    "driver_performance": (
        "One row per driver per season. Points are race-result points; wins and podiums "
        "count race entries at positions 1 and 1-3; average_finish uses positionOrder.",
        "Source: results, races, drivers.",
    ),
    "constructor_season_performance": (
        "One row per constructor per season. points are official per-race constructor_results "
        "points summed over the season, not driver result points.",
        "Source: constructor_results, races, constructors.",
    ),
    "circuit_country_summary": (
        "One row per host country. races counts unique scheduled Grand Prix raceIds.",
        "Source: races, circuits.",
    ),
    "reliability_summary": (
        "One row per season and official status label. classified_finishes counts 'Finished' "
        "or '+N Lap(s)' statuses; entry_count is the denominator.",
        "Source: results, races, status.",
    ),
    "pit_stop_summary": (
        "One row per season. stop_count counts actual historical stop events; duration_ms "
        "is the mean recorded pit-stop duration in milliseconds.",
        "Source: pit_stops, races.",
    ),
    "pit_stop_constructor_summary": (
        "One row per constructor per season. Only stops whose driver-race result maps "
        "uniquely to one constructor are counted; ambiguous team links are excluded.",
        "Source: pit_stops, results, races, drivers, constructors.",
    ),
    "tyre_strategy_summary": (
        "One row per year and compound in the weather/tyre source. laps counts source rows; "
        "mean_lap_ms is the mean observed lap time; weather values are sample means.",
        "Source: weather_tyre. This is observational and is not joined to historical results.",
    ),
}


def _write_extract(directory: Path, name: str, frame: pd.DataFrame) -> None:
    frame.to_csv(directory / f"{name}.csv", index=False, encoding="utf-8")
    (directory / f"{name}.data_dictionary.md").write_text(
        f"# {name}\n\n"
        f"**Row grain:** {DICTIONARIES[name][0]}\n\n"
        f"**Columns:** {', '.join(frame.columns) if len(frame.columns) else 'None'}\n\n"
        f"**Missing values:** preserved as empty CSV fields; no zero imputation.\n\n"
        f"**Source:** {DICTIONARIES[name][1]}\n",
        encoding="utf-8",
    )


def export_tableau_data(database: Path, output: Path) -> dict[str, int]:
    tables, _missing = load_tables(database)
    output.mkdir(parents=True, exist_ok=True)
    results = race_results(tables)
    race_level = (
        results.groupby(["raceId", "year", "round", "grand_prix", "date"], as_index=False)
        .agg(
            entries=("driverId", "size"),
            podium_finishes=("finish_position", lambda s: int(s.between(1, 3).sum())),
        )
    )
    driver_season = (
        results.groupby(["driver", "year"], as_index=False, dropna=False)
        .agg(
            points=("points", "sum"),
            wins=("finish_position", lambda s: int((s == 1).sum())),
            podiums=("finish_position", lambda s: int(s.between(1, 3).sum())),
            average_finish=("finish_position", "mean"),
            entries=("raceId", "size"),
        )
    )
    extracts = {
        "race_summary": race_level,
        "driver_performance": driver_season,
        "constructor_season_performance": constructor_performance(tables),
        "circuit_country_summary": country_race_counts(tables),
    }
    categorized = results.assign(
        classified_finish=(
            results["status"].eq("Finished")
            | results["status"].str.contains(r"\+\s*\d+\s*Lap", case=False, regex=True)
        )
    )
    extracts["reliability_summary"] = (
        categorized.groupby(["year", "status"], dropna=False, as_index=False)
        .agg(
            entry_count=("raceId", "size"),
            classified_finishes=("classified_finish", "sum"),
        )
    )
    if "pit_stops" in tables:
        pit = tables["pit_stops"].merge(
            tables["races"][["raceId", "year"]], on="raceId", how="left", validate="many_to_one"
        )
        pit["duration_ms"] = pd.to_numeric(pit["milliseconds"], errors="coerce")
        extracts["pit_stop_summary"] = (
            pit.groupby("year", as_index=False)
            .agg(
                stop_count=("stop", "size"),
                mean_duration_ms=("duration_ms", "mean"),
                median_duration_ms=("duration_ms", "median"),
            )
        )
        linked_stops = pit_stop_summary(tables).dropna(subset=["constructor"])
        extracts["pit_stop_constructor_summary"] = (
            linked_stops.groupby(["year", "constructor"], as_index=False)
            .agg(
                stop_count=("stop", "size"),
                mean_duration_ms=("duration_ms", "mean"),
                median_duration_ms=("duration_ms", "median"),
            )
        )
    if "weather_tyre" in tables:
        weather = tables["weather_tyre"]
        extracts["tyre_strategy_summary"] = (
            weather.groupby(["year", "Compound"], dropna=False, as_index=False)
            .agg(
                laps=("lap", "size"),
                mean_lap_ms=("milliseconds", "mean"),
                mean_air_temp=("AirTemp", "mean"),
                mean_track_temp=("TrackTemp", "mean"),
                mean_humidity=("Humidity", "mean"),
                wet_laps=("Rainfall", "sum"),
            )
        )
    for name, frame in extracts.items():
        _write_extract(output, name, frame)
    return {name: len(frame) for name, frame in extracts.items()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "data" / "exports" / "tableau"
    )
    args = parser.parse_args(argv)
    database_path = resolve_project_path(args.database)
    output_path = resolve_project_path(args.output)
    try:
        counts = export_tableau_data(database_path, output_path)
    except (FileNotFoundError, ValueError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    for name, count in counts.items():
        print(f"{name}: {count:,} rows")
    print(f"Tableau extracts written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
