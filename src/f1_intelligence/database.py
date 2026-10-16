"""Build a validated SQLite database from the project's local Kaggle data."""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from pathlib import Path

import pandas as pd

LOGGER = logging.getLogger(__name__)

HISTORICAL_TABLES = {
    "circuits": {"primary_key": ("circuitId",)},
    "constructors": {"primary_key": ("constructorId",)},
    "drivers": {"primary_key": ("driverId",)},
    "seasons": {"primary_key": ("year",)},
    "status": {"primary_key": ("statusId",)},
    "races": {
        "primary_key": ("raceId",),
        "foreign_keys": {
            "circuitId": ("circuits", "circuitId"),
        },
    },
    "constructor_results": {
        "primary_key": ("constructorResultsId",),
        "foreign_keys": {
            "raceId": ("races", "raceId"),
            "constructorId": ("constructors", "constructorId"),
        },
    },
    "constructor_standings": {
        "primary_key": ("constructorStandingsId",),
        "foreign_keys": {
            "raceId": ("races", "raceId"),
            "constructorId": ("constructors", "constructorId"),
        },
    },
    "driver_standings": {
        "primary_key": ("driverStandingsId",),
        "foreign_keys": {
            "raceId": ("races", "raceId"),
            "driverId": ("drivers", "driverId"),
        },
    },
    "qualifying": {
        "primary_key": ("qualifyId",),
        "foreign_keys": {
            "raceId": ("races", "raceId"),
            "driverId": ("drivers", "driverId"),
            "constructorId": ("constructors", "constructorId"),
        },
    },
    "results": {
        "primary_key": ("resultId",),
        "foreign_keys": {
            "raceId": ("races", "raceId"),
            "driverId": ("drivers", "driverId"),
            "constructorId": ("constructors", "constructorId"),
            "statusId": ("status", "statusId"),
        },
    },
    "sprint_results": {
        "primary_key": ("resultId",),
        "foreign_keys": {
            "raceId": ("races", "raceId"),
            "driverId": ("drivers", "driverId"),
            "constructorId": ("constructors", "constructorId"),
            "statusId": ("status", "statusId"),
        },
    },
    "lap_times": {
        "primary_key": ("raceId", "driverId", "lap"),
        "foreign_keys": {
            "raceId": ("races", "raceId"),
            "driverId": ("drivers", "driverId"),
        },
    },
    "pit_stops": {
        "primary_key": ("raceId", "driverId", "stop"),
        "foreign_keys": {
            "raceId": ("races", "raceId"),
            "driverId": ("drivers", "driverId"),
        },
    },
}
REQUIRED_COLUMNS = {
    "circuits": {"circuitId", "name", "country"},
    "constructors": {"constructorId", "name"},
    "drivers": {"driverId", "forename", "surname"},
    "seasons": {"year"},
    "status": {"statusId", "status"},
    "races": {"raceId", "year", "round", "circuitId", "name", "date"},
    "constructor_results": {"raceId", "constructorId", "points"},
    "constructor_standings": {"raceId", "constructorId", "points"},
    "driver_standings": {"raceId", "driverId", "points"},
    "qualifying": {"raceId", "driverId", "constructorId", "position"},
    "results": {
        "raceId",
        "driverId",
        "constructorId",
        "positionOrder",
        "points",
        "statusId",
    },
    "sprint_results": {"raceId", "driverId", "constructorId", "positionOrder"},
    "lap_times": {"raceId", "driverId", "lap", "milliseconds"},
    "pit_stops": {"raceId", "driverId", "stop", "milliseconds"},
}
OPTIONAL_TABLES = {"constructor_results", "constructor_standings", "driver_standings",
                   "qualifying", "sprint_results", "lap_times", "pit_stops"}


class DatabaseBuildError(RuntimeError):
    """Raised when source data cannot safely be loaded into SQLite."""


def _quote(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        raise DatabaseBuildError(f"Unsafe SQL identifier in source schema: {identifier!r}")
    return f'"{identifier}"'


def _read_source(path: Path) -> pd.DataFrame:
    try:
        if path.suffix.lower() == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path, low_memory=False, na_values=["\\N"])
    except (OSError, ValueError, ImportError) as exc:
        raise DatabaseBuildError(f"Unable to read source dataset {path}: {exc}") from exc


def _validate_primary_key(table: str, frame: pd.DataFrame) -> None:
    keys = HISTORICAL_TABLES[table]["primary_key"]
    missing = set(keys) - set(frame.columns)
    if missing:
        raise DatabaseBuildError(f"{table} is missing primary-key columns: {sorted(missing)}")
    if frame[list(keys)].isna().any(axis=None):
        raise DatabaseBuildError(f"{table} has null values in primary key {keys}")
    duplicates = frame.duplicated(list(keys), keep=False)
    if duplicates.any():
        examples = frame.loc[duplicates, list(keys)].head(3).to_dict("records")
        raise DatabaseBuildError(f"{table} has duplicate primary keys {keys}: {examples}")


def build_database(
    raw_root: Path,
    database_path: Path,
    *,
    include_weather: bool = True,
) -> dict[str, int]:
    """Atomically replace the analytical database after source and FK validation."""
    historical_root = raw_root / "historical_f1"
    frames: dict[str, pd.DataFrame] = {}
    for table in HISTORICAL_TABLES:
        source = historical_root / f"{table}.csv"
        if not source.is_file():
            if table in OPTIONAL_TABLES:
                LOGGER.warning("Optional source table unavailable: %s", source)
                continue
            raise DatabaseBuildError(f"Required source table is missing: {source}")
        frame = _read_source(source)
        missing = REQUIRED_COLUMNS[table] - set(frame.columns)
        if missing:
            raise DatabaseBuildError(f"{source} is missing required columns: {sorted(missing)}")
        _validate_primary_key(table, frame)
        frames[table] = frame

    weather_path = raw_root / "weather_tyre" / "f1_all.parquet"
    if include_weather and weather_path.is_file():
        weather = _read_source(weather_path)
        required = {"raceId", "driverId", "lap", "year", "Compound"}
        if missing := required - set(weather.columns):
            raise DatabaseBuildError(
                f"{weather_path} is missing required columns: {sorted(missing)}"
            )
        weather_key = ["raceId", "driverId", "lap"]
        duplicates = weather.duplicated(weather_key, keep=False)
        if duplicates.any():
            raise DatabaseBuildError(
                "weather_tyre contains duplicate (raceId, driverId, lap) keys"
            )
        frames["weather_tyre"] = weather
    elif include_weather:
        LOGGER.warning("Optional weather/tyre data unavailable: %s", weather_path)

    for table, frame in frames.items():
        for column, (parent, parent_column) in HISTORICAL_TABLES.get(
            table, {}
        ).get("foreign_keys", {}).items():
            if parent not in frames:
                raise DatabaseBuildError(f"{table}.{column} requires missing table {parent}")
            known = set(frames[parent][parent_column].dropna())
            invalid = frame[column].notna() & ~frame[column].isin(known)
            if invalid.any():
                samples = frame.loc[invalid, column].drop_duplicates().head(5).tolist()
                raise DatabaseBuildError(
                    f"{table}.{column} has {int(invalid.sum())} values absent from "
                    f"{parent}.{parent_column}: {samples}"
                )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = database_path.with_name(f".{database_path.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    counts: dict[str, int] = {}
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temporary)
        with connection:
            connection.execute("PRAGMA foreign_keys = ON")
            for table, frame in frames.items():
                definitions = []
                for column, dtype in frame.dtypes.items():
                    if pd.api.types.is_integer_dtype(dtype):
                        sql_type = "INTEGER"
                    elif pd.api.types.is_numeric_dtype(dtype):
                        sql_type = "REAL"
                    else:
                        sql_type = "TEXT"
                    definitions.append(f"{_quote(column)} {sql_type}")
                if table in HISTORICAL_TABLES:
                    definition = HISTORICAL_TABLES[table]
                    definitions.append(
                        "PRIMARY KEY (" + ", ".join(_quote(key) for key in definition["primary_key"]) + ")"
                    )
                    for column, (parent, parent_column) in definition.get("foreign_keys", {}).items():
                        definitions.append(
                            f"FOREIGN KEY ({_quote(column)}) REFERENCES "
                            f"{_quote(parent)} ({_quote(parent_column)})"
                        )
                else:
                    definitions.append(
                        "PRIMARY KEY (" + ", ".join(_quote(key) for key in ("raceId", "driverId", "lap")) + ")"
                    )
                connection.execute(
                    f"CREATE TABLE {_quote(table)} ({', '.join(definitions)})"
                )
                frame.to_sql(table, connection, if_exists="append", index=False, chunksize=5000)
                inserted = connection.execute(
                    f"SELECT COUNT(*) FROM {_quote(table)}"
                ).fetchone()[0]
                if inserted != len(frame):
                    raise DatabaseBuildError(
                        f"Row-count mismatch for {table}: source={len(frame)}, database={inserted}"
                    )
                counts[table] = inserted
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise DatabaseBuildError(f"SQLite foreign-key check failed: {violations[:5]}")
            connection.execute(
                "CREATE INDEX idx_results_race_position ON results(raceId, positionOrder)"
            )
            connection.execute("CREATE INDEX idx_results_driver ON results(driverId)")
            connection.execute("CREATE INDEX idx_races_year ON races(year, round)")
            if "weather_tyre" in frames:
                connection.execute(
                    "CREATE INDEX idx_weather_year_compound ON weather_tyre(year, Compound)"
                )
        connection.close()
        temporary.replace(database_path)
    except Exception:
        if connection is not None:
            connection.close()
        temporary.unlink(missing_ok=True)
        raise
    return counts
