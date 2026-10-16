"""Offline transformation, quality, and relational storage tests."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from f1_intelligence.storage.sqlite import SQLiteStore
from f1_intelligence.transformations.laps import normalize_laps, normalize_pit_stops
from f1_intelligence.transformations.runner import (
    TABLES,
    build_quality_report,
    transform_raw_data,
)


def _schedule() -> dict[str, Any]:
    return {
        "metadata": {
            "dataset": "schedule",
            "season": 2024,
            "event_round": None,
            "record_count": 1,
        },
        "records": [
            {
                "RoundNumber": 1,
                "Country": "Bahrain",
                "Location": "Sakhir",
                "OfficialEventName": "Formula 1 Bahrain Grand Prix 2024",
                "EventDate": "2024-03-02T00:00:00",
                "EventName": "Bahrain Grand Prix",
                "EventFormat": "conventional",
                "Session1": "Qualifying",
                "Session1DateUtc": "2024-03-01T16:00:00Z",
                "Session2": "Race",
                "Session2DateUtc": "2024-03-02T15:00:00Z",
            }
        ],
    }


def _result(
    driver_id: str | None,
    driver_number: str | None,
    position: int | None,
    status: str | None,
    team_id: str | None,
    q1: str | None = "P0DT0H1M30.000S",
) -> dict[str, Any]:
    return {
        "DriverId": driver_id,
        "DriverNumber": driver_number,
        "Abbreviation": driver_number,
        "FirstName": "Test",
        "LastName": driver_id or "",
        "FullName": f"Test {driver_id}" if driver_id else None,
        "TeamId": team_id,
        "TeamName": team_id,
        "Position": position,
        "ClassifiedPosition": str(position) if position else "",
        "GridPosition": None,
        "Points": None,
        "Status": status,
        "Time": None,
        "Laps": None,
        "Q1": q1,
        "Q2": None,
        "Q3": None,
    }


def _write_raw(root: Path, relative: str, payload: dict[str, Any]) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _fixture_raw(root: Path) -> Path:
    _write_raw(root, "season=2024/schedule.json", _schedule())
    result_records = [
        _result("verstappen", "1", 1, "Finished", "red_bull"),
        _result("leclerc", "16", None, "Did not start", "ferrari", q1=None),
        _result("sainz", "55", None, "Disqualified", "ferrari"),
        _result("perez", "11", None, "DNF", "red_bull"),
        _result("verstappen", "1", 2, "Finished", "red_bull"),
        _result("invalid", "99", 0, "DNF", "test_team"),
        _result(None, None, 4, None, None),
    ]
    _write_raw(
        root,
        "season=2024/round=01-bahrain/session=Q/qualifying_results.json",
        {
            "metadata": {
                "dataset": "qualifying_results",
                "season": 2024,
                "event_round": 1,
                "event_id": "2024:1",
                "event_name": "Bahrain Grand Prix",
                "session": "Q",
                "record_count": len(result_records),
            },
            "records": result_records,
        },
    )
    return root


def test_raw_transform_reports_invalid_records_and_preserves_source(
    tmp_path: Path,
) -> None:
    raw_root = _fixture_raw(tmp_path / "raw")
    raw_files = list(raw_root.rglob("*.json"))
    original = {path: path.read_bytes() for path in raw_files}

    bundle = transform_raw_data(raw_root)
    report = build_quality_report(bundle)

    assert len(bundle.tables["events"]) == 1
    assert len(bundle.tables["qualifying_results"]) == 4
    statuses = {row["driver_id"]: row["status_group"] for row in bundle.tables["qualifying_results"]}
    assert statuses == {
        "verstappen": "CLASSIFIED",
        "leclerc": "DNS",
        "sainz": "DSQ",
        "perez": "DNF",
    }
    assert bundle.tables["qualifying_results"][1]["q1_s"] is None
    assert bundle.tables["race_results"] == []
    assert len(bundle.rejected_records) == 3
    codes = {issue.code for issue in bundle.issues}
    assert "duplicate_result_key" in codes
    assert "invalid_position" in codes
    assert "missing_driver_identifier" in codes
    assert report["rejected_record_count"] == 3
    assert all(path.read_bytes() == content for path, content in original.items())


def test_lap_validation_catches_duplicates_invalid_numbers_and_times() -> None:
    issues = []
    records = [
        {"Driver": "VER", "LapNumber": 1, "LapTime": None, "Sector1Time": None},
        {"Driver": "VER", "LapNumber": 1, "LapTime": "not-a-time"},
        {"Driver": "VER", "LapNumber": 0, "LapTime": "P0DT0H1M30S"},
        {"Driver": "VER", "LapNumber": 2, "LapTime": "P0DT0H0M0S"},
    ]

    rows, rejected = normalize_laps(
        records, "2024:1", "R", "raw/laps.json", issues
    )

    assert len(rows) == 1
    assert rows[0]["lap_time_s"] is None
    assert len(rejected) == 3
    assert {issue.code for issue in issues} >= {
        "duplicate_lap_key",
        "invalid_lap_number",
        "invalid_lap_time",
        "impossible_lap_time",
    }


def test_pit_stop_observations_keep_source_times_without_invented_duration() -> None:
    issues = []
    rows, rejected = normalize_pit_stops(
        [
            {
                "Driver": "VER",
                "LapNumber": 12,
                "PitInTime": "P0DT0H20M0S",
                "PitOutTime": None,
            },
            {
                "Driver": "LEC",
                "LapNumber": 0,
                "PitInTime": None,
                "PitOutTime": "P0DT0H20M1S",
            },
        ],
        "2024:1",
        "R",
        "raw/pit_stops.json",
        issues,
    )

    assert rows == [
        {
            "event_id": "2024:1",
            "session_id": "2024:1:R",
            "driver_id": "VER",
            "lap_number": 12,
            "pit_in_time_s": 1200.0,
            "pit_out_time_s": None,
        }
    ]
    assert len(rejected) == 1
    assert "invalid_pit_observation_key" in {issue.code for issue in issues}


def test_required_source_column_and_count_anomalies_are_reported(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    _write_raw(
        raw_root,
        "season=2024/schedule.json",
        {
            "metadata": {"dataset": "schedule", "season": 2024, "record_count": 8},
            "records": [{"RoundNumber": 1}],
        },
    )
    report_path = tmp_path / "previous.json"
    report_path.write_text(
        json.dumps({"source_record_counts": {"2024:::schedule": 60}}),
        encoding="utf-8",
    )

    bundle = transform_raw_data(raw_root, previous_report=report_path)
    codes = {issue.code for issue in bundle.issues}
    assert "missing_required_columns" in codes
    assert "source_row_count_mismatch" in codes
    assert "suspicious_row_count_change" in codes
    assert bundle.tables["events"] == []
    assert bundle.rejected_records[0]["reason_codes"] == [
        "missing_required_columns"
    ]


def test_sqlite_rebuild_is_idempotent_and_enforces_relationships(
    tmp_path: Path,
) -> None:
    bundle = transform_raw_data(_fixture_raw(tmp_path / "raw"))
    store = SQLiteStore(tmp_path / "f1.sqlite3")
    issues = [issue.to_dict() for issue in bundle.issues]
    first = store.load_bundle(bundle.tables, bundle.rejected_records, issues)
    second = store.load_bundle(bundle.tables, bundle.rejected_records, issues)

    assert first == second
    counts = store.row_counts()
    assert counts["events"] == 1
    assert counts["qualifying_results"] == 4
    assert counts["race_results"] == 0
    assert counts["rejected_records"] == 3
    assert set(TABLES) <= set(counts)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT status_group FROM qualifying_results WHERE driver_id='leclerc'"
        ).fetchone()[0] == "DNS"
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO qualifying_results
                    (event_id, session_id, driver_id, position)
                VALUES ('2024:1', '2024:1:missing', 'leclerc', -1)
                """
            )


def test_sqlite_rejects_broken_fact_foreign_keys(tmp_path: Path) -> None:
    tables = {table: [] for table in TABLES}
    tables["qualifying_results"] = [
        {
            "event_id": "2024:99",
            "session_id": "2024:99:Q",
            "driver_id": "unknown",
        }
    ]

    with pytest.raises(RuntimeError, match="SQLite load failed"):
        SQLiteStore(tmp_path / "bad.sqlite3").load_bundle(tables, [], [])
