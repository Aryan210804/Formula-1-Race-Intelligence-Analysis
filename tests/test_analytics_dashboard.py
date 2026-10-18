"""Known-value checks for analytical metrics and safe data joins."""

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import f1_intelligence.analytics as analytics
from scripts.build_database import main as build_database_main
from scripts.export_tableau_data import export_tableau_data
from scripts.inspect_datasets import inspect_datasets
from f1_intelligence.analytics import load_tables
from f1_intelligence.analytics import (
    apply_filters,
    classify_finish,
    driver_performance,
    pit_stop_summary,
    race_results,
    tyre_summary,
)
from f1_intelligence.database import DatabaseBuildError, build_database
from f1_intelligence.paths import (
    DEFAULT_DATABASE_PATH,
    PROJECT_ROOT,
    resolve_project_path,
)


def _create_core_schema(connection: sqlite3.Connection) -> None:
    schemas = {
        "circuits": "circuitId INTEGER, name TEXT, country TEXT",
        "races": "raceId INTEGER, year INTEGER, round INTEGER, name TEXT, date TEXT, circuitId INTEGER",
        "drivers": "driverId INTEGER, forename TEXT, surname TEXT, nationality TEXT",
        "constructors": "constructorId INTEGER, name TEXT",
        "status": "statusId INTEGER, status TEXT",
        "results": "raceId INTEGER, driverId INTEGER, constructorId INTEGER, positionOrder INTEGER, points REAL, statusId INTEGER",
    }
    for table, columns in schemas.items():
        connection.execute(f'CREATE TABLE "{table}" ({columns})')


@pytest.fixture
def tables():
    return {
        "circuits": pd.DataFrame(
            [{"circuitId": 10, "name": "Test Circuit", "country": "Testland"}]
        ),
        "races": pd.DataFrame(
            [
                {"raceId": 1, "year": 2020, "round": 1, "name": "Test GP", "date": "2020-01-01", "circuitId": 10},
                {"raceId": 2, "year": 2020, "round": 2, "name": "Second GP", "date": "2020-02-01", "circuitId": 10},
            ]
        ),
        "drivers": pd.DataFrame(
            [
                {"driverId": 1, "forename": "A", "surname": "One", "nationality": "A"},
                {"driverId": 2, "forename": "B", "surname": "Two", "nationality": "B"},
            ]
        ),
        "constructors": pd.DataFrame(
            [{"constructorId": 1, "name": "Team"}]
        ),
        "status": pd.DataFrame(
            [
                {"statusId": 1, "status": "Finished"},
                {"statusId": 2, "status": "+1 Lap"},
                {"statusId": 3, "status": "Engine"},
            ]
        ),
        "results": pd.DataFrame(
            [
                {"resultId": 1, "raceId": 1, "driverId": 1, "constructorId": 1, "positionOrder": 1, "points": 25, "statusId": 1},
                {"resultId": 2, "raceId": 1, "driverId": 2, "constructorId": 1, "positionOrder": 2, "points": 18, "statusId": 1},
                {"resultId": 3, "raceId": 2, "driverId": 1, "constructorId": 1, "positionOrder": 4, "points": 12, "statusId": 2},
                {"resultId": 4, "raceId": 2, "driverId": 2, "constructorId": 1, "positionOrder": 9, "points": 2, "statusId": 3},
            ]
        ),
        "pit_stops": pd.DataFrame(
            [
                {"raceId": 1, "driverId": 1, "stop": 1, "milliseconds": 25000},
                {"raceId": 1, "driverId": 2, "stop": 1, "milliseconds": 26000},
            ]
        ),
    }


def test_dimension_joins_preserve_each_race_entry_and_calculate_driver_metrics(tables):
    joined = race_results(tables)
    assert len(joined) == len(tables["results"]) == 4
    assert joined["country"].eq("Testland").all()
    metrics = driver_performance(joined).set_index("driver")
    assert metrics.loc["A One", ["points", "wins", "podiums", "entries"]].to_dict() == {
        "points": 37.0,
        "wins": 1,
        "podiums": 1,
        "entries": 2,
    }
    assert metrics.loc["B Two", "podiums"] == 1


def test_filtering_changes_only_selected_dimensions(tables):
    joined = race_results(tables)
    selected = apply_filters(joined, years=(2020, 2020), drivers=["A One"], countries=["Testland"])
    assert selected["resultId"].tolist() == [1, 3]


def test_classified_finish_definition():
    status = pd.Series(["Finished", "+1 Lap", "+12 Laps", "Engine", None])
    assert classify_finish(status).tolist() == [True, True, True, False, False]


def test_dimension_duplicate_is_rejected(tables):
    tables["drivers"] = pd.concat([tables["drivers"], tables["drivers"].iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="unique identifiers"):
        race_results(tables)


def test_pit_stop_team_attribution_preserves_event_grain(tables):
    pit = pit_stop_summary(tables)
    assert len(pit) == len(tables["pit_stops"])
    assert pit["constructor"].eq("Team").all()
    tables["results"] = pd.concat(
        [tables["results"], tables["results"].iloc[[0]]], ignore_index=True
    )
    ambiguous = pit_stop_summary(tables)
    assert len(ambiguous) == len(tables["pit_stops"])
    assert pd.isna(ambiguous.loc[ambiguous["driverId"] == 1, "constructor"]).all()


def test_inventory_database_tables_keep_relational_constraints(project_root):
    path = project_root / "data" / "processed" / "f1_intelligence.db"
    if not path.is_file():
        pytest.skip("Build the analytical database to run the integration check")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 26759
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    loaded, missing = load_tables(path)
    results = race_results(loaded)
    assert len(results) == 26759
    assert results["year"].min() == 1950
    assert results["year"].max() == 2024
    assert not driver_performance(results).empty
    assert not pit_stop_summary(loaded).empty
    assert not tyre_summary(loaded).empty
    assert not missing


def test_default_database_path_and_relative_paths_use_repository_root(
    project_root: Path,
) -> None:
    assert PROJECT_ROOT == project_root
    assert DEFAULT_DATABASE_PATH == (
        project_root / "data" / "processed" / "f1_intelligence.db"
    )
    assert resolve_project_path(Path("data/processed/custom.db")) == (
        project_root / "data" / "processed" / "custom.db"
    )


def test_load_tables_reports_missing_database_with_resolved_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError) as error:
        load_tables(missing)
    assert str(missing.resolve()) in str(error.value)


def test_load_tables_rejects_corrupt_database(tmp_path: Path) -> None:
    database = tmp_path / "corrupt.db"
    database.write_text("not a SQLite database", encoding="utf-8")

    with pytest.raises(ValueError, match="Unable to read analytical SQLite database"):
        load_tables(database)


def test_load_tables_rejects_missing_required_tables(tmp_path: Path) -> None:
    database = tmp_path / "incomplete.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE results (raceId INTEGER)")

    with pytest.raises(ValueError, match="missing required analytical tables"):
        load_tables(database)


def test_load_tables_closes_connection_when_validation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "incomplete.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE results (raceId INTEGER)")
    original_connect = sqlite3.connect
    opened = []

    class TrackedConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection
            self.closed = False

        def close(self) -> None:
            self.closed = True
            self.connection.close()

        def __getattr__(self, name: str):
            return getattr(self.connection, name)

    def track_connection(*args: Any, **kwargs: Any) -> TrackedConnection:
        tracked = TrackedConnection(original_connect(*args, **kwargs))
        opened.append(tracked)
        return tracked

    monkeypatch.setattr(analytics.sqlite3, "connect", track_connection)

    with pytest.raises(ValueError, match="missing required analytical tables"):
        load_tables(database)

    assert len(opened) == 1
    assert opened[0].closed


def test_load_tables_rejects_missing_required_columns(tmp_path: Path) -> None:
    database = tmp_path / "incompatible.db"
    with sqlite3.connect(database) as connection:
        _create_core_schema(connection)
        connection.execute("ALTER TABLE results RENAME COLUMN raceId TO event_id")

    with pytest.raises(ValueError, match="table 'results' is missing required columns"):
        load_tables(database)


def test_database_build_failure_preserves_existing_database(tmp_path: Path) -> None:
    database = tmp_path / "existing.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE keep (value TEXT)")
        connection.execute("INSERT INTO keep VALUES ('existing')")
    original = database.read_bytes()

    with pytest.raises(DatabaseBuildError, match="Required source table is missing"):
        build_database(tmp_path / "raw", database)

    assert database.read_bytes() == original


def test_database_build_cli_defaults_are_rooted_independent_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: dict[str, Path] = {}

    def fake_build(
        raw_root: Path, database_path: Path, *, include_weather: bool
    ) -> dict[str, int]:
        received["raw_root"] = raw_root
        received["database"] = database_path
        assert include_weather
        return {"results": 1}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scripts.build_database.build_database", fake_build)

    assert build_database_main([]) == 0
    assert received == {
        "raw_root": PROJECT_ROOT / "data" / "raw",
        "database": DEFAULT_DATABASE_PATH,
    }


def test_dataset_inspection_reports_file_shape_and_missing_values(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    pd.DataFrame({"raceId": [1, 2], "year": [2020, 2021], "optional": [None, "x"]}).to_csv(
        raw / "races.csv", index=False
    )
    report = inspect_datasets(raw)
    assert len(report) == 1
    sheet = report[0]["sheets"][0]
    assert (sheet["rows"], sheet["columns"], sheet["duplicate_rows"]) == (2, 3, 0)
    assert sheet["missing"]["optional"]["count"] == 1
    assert ["raceId"] in sheet["candidate_unique_keys"]
    assert sheet["date_ranges"]["year"] == {"min": 2020, "max": 2021}


def test_optional_database_tables_are_reported(tmp_path):
    database = tmp_path / "minimal.db"
    with sqlite3.connect(database) as connection:
        _create_core_schema(connection)
    tables, missing = load_tables(database)
    assert len(tables) == 6
    assert "pit_stops" in missing and "weather_tyre" in missing


def test_tableau_exports_preserve_expected_grains_and_dictionaries(tmp_path, tables):
    database = tmp_path / "analytics.db"
    with sqlite3.connect(database) as connection:
        for name in ("circuits", "races", "drivers", "constructors", "status", "results", "pit_stops"):
            tables[name].to_sql(name, connection, index=False)
        pd.DataFrame(
            [
                {"constructorResultsId": 1, "raceId": 1, "constructorId": 1, "points": 43},
                {"constructorResultsId": 2, "raceId": 2, "constructorId": 1, "points": 14},
            ]
        ).to_sql("constructor_results", connection, index=False)
        pd.DataFrame(
            [
                {"year": 2021, "Compound": "SOFT", "lap": 1, "milliseconds": 90000, "AirTemp": 25.0, "TrackTemp": 31.0, "Humidity": 50.0, "Rainfall": 0.0},
                {"year": 2021, "Compound": "MEDIUM", "lap": 2, "milliseconds": 91000, "AirTemp": 25.0, "TrackTemp": 31.0, "Humidity": 50.0, "Rainfall": 0.0},
            ]
        ).to_sql("weather_tyre", connection, index=False)
    output = tmp_path / "tableau"
    counts = export_tableau_data(database, output)
    assert counts["race_summary"] == 2
    assert counts["driver_performance"] == 2
    assert counts["pit_stop_constructor_summary"] == 1
    assert counts["tyre_strategy_summary"] == 2
    assert pd.read_csv(output / "race_summary.csv")["entries"].tolist() == [2, 2]
    assert (output / "race_summary.data_dictionary.md").is_file()
