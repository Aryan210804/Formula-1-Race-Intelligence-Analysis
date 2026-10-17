"""Known-value checks for analytical metrics and safe data joins."""

import sqlite3

import pandas as pd
import pytest

from f1_intelligence.analytics import load_tables, normalize_database_url
from f1_intelligence.analytics import (
    apply_filters,
    classify_finish,
    driver_performance,
    pit_stop_summary,
    race_results,
    reliability_summary,
)
from scripts.export_tableau_data import export_tableau_data
from scripts.inspect_datasets import inspect_datasets
from scripts.sync_database import sync_database


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


def test_reliability_summary_counts_entries_and_classified_finishes(tables):
    summary = reliability_summary(race_results(tables)).set_index("status")
    assert summary.loc["Finished", ["entries", "classified_finishes"]].to_dict() == {
        "entries": 2,
        "classified_finishes": 2,
    }
    assert summary.loc["Engine", ["entries", "classified_finishes"]].to_dict() == {
        "entries": 1,
        "classified_finishes": 0,
    }


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
        for table in ("circuits", "races", "drivers", "constructors", "status", "results"):
            connection.execute(f'CREATE TABLE "{table}" (value INTEGER)')
    tables, missing = load_tables(database)
    assert len(tables) == 6
    assert "pit_stops" in missing and "weather_tyre" in missing


def test_load_tables_accepts_sqlalchemy_database_url(tmp_path, tables):
    database = tmp_path / "analytics.db"
    with sqlite3.connect(database) as connection:
        for name, frame in tables.items():
            frame.to_sql(name, connection, index=False)
    database_url = f"sqlite:///{database.as_posix()}"

    loaded, missing = load_tables(database_url)

    assert len(loaded["results"]) == len(tables["results"])
    assert "weather_tyre" in missing


def test_sync_database_copies_all_tables_and_can_refresh_destination(tmp_path, tables):
    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    with sqlite3.connect(source) as connection:
        for name, frame in tables.items():
            frame.to_sql(name, connection, index=False)
    destination_url = f"sqlite:///{destination.as_posix()}"

    counts = sync_database(source, destination_url)
    with sqlite3.connect(source) as connection:
        connection.execute("DELETE FROM results")
    refreshed_counts = sync_database(source, destination_url)
    loaded, _ = load_tables(destination_url)

    assert counts["results"] == 4
    assert refreshed_counts["results"] == 0
    assert loaded["results"].empty


def test_sync_database_refuses_to_replace_unrelated_destination_tables(tmp_path, tables):
    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    with sqlite3.connect(source) as connection:
        for name, frame in tables.items():
            frame.to_sql(name, connection, index=False)
    with sqlite3.connect(destination) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('keep')")

    with pytest.raises(ValueError, match="unrelated tables"):
        sync_database(source, f"sqlite:///{destination.as_posix()}")

    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM unrelated").fetchone() == ("keep",)


def test_normalize_database_url_uses_psycopg_driver():
    assert normalize_database_url(
        "postgresql://user:password@host:5432/database"
    ) == "postgresql+psycopg://user:password@host:5432/database"


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
