"""Offline tests for FastF1 ingestion and resumable persistence."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pandas as pd
import pytest

from f1_intelligence.data.pipeline import ingest_season, ingest_session
from f1_intelligence.data.retry import IngestionError, RequestController
from f1_intelligence.data.schedule import select_event
from f1_intelligence.data.settings import IngestionSettings


class FakeLaps(pd.DataFrame):
    """Small lap fixture with the FastF1 telemetry method shape."""

    @property
    def _constructor(self) -> type["FakeLaps"]:
        return FakeLaps

    def get_telemetry(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"Driver": ["VER"], "Time": [pd.Timedelta(seconds=1)], "Speed": [320]}
        )


class FakeSession:
    """Mock FastF1 session returning representative offline data."""

    def __init__(self, fail_telemetry: bool = False) -> None:
        self.fail_telemetry = fail_telemetry
        self.load_calls: list[dict[str, bool]] = []
        self.results = pd.DataFrame(
            {
                "DriverId": ["verstappen"],
                "DriverNumber": ["1"],
                "FullName": ["Max Verstappen"],
                "Position": [1],
                "Points": [None],
            }
        )
        self.laps = FakeLaps(
            {
                "DriverNumber": ["1", "1"],
                "LapNumber": [1, 2],
                "LapTime": [pd.Timedelta(90, unit="s"), pd.NaT],
                "PitInTime": [None, pd.Timedelta(180, unit="s")],
                "PitOutTime": [None, None],
            }
        )
        self.weather_data = pd.DataFrame(
            {"Time": [pd.Timedelta(10, unit="s")], "Rainfall": [False]}
        )

    def load(
        self,
        *,
        laps: bool,
        telemetry: bool,
        weather: bool,
        messages: bool,
    ) -> None:
        self.load_calls.append(
            {
                "laps": laps,
                "telemetry": telemetry,
                "weather": weather,
                "messages": messages,
            }
        )
        if telemetry and self.fail_telemetry:
            raise TimeoutError("telemetry endpoint timed out")


class FakeSource:
    """Source adapter that returns a fresh session per extraction group."""

    def __init__(self, fail_telemetry: bool = False) -> None:
        self.fail_telemetry = fail_telemetry
        self.session_calls: list[tuple[int, int, str]] = []
        self.sessions: list[FakeSession] = []
        self.schedule_calls: list[int] = []

    def get_event_schedule(self, season: int) -> pd.DataFrame:
        self.schedule_calls.append(season)
        return pd.DataFrame(
            {
                "RoundNumber": [0, 1],
                "EventName": ["Pre-Season Testing", "Australian Grand Prix"],
                "EventDate": ["2024-02-20", "2024-03-24"],
            }
        )

    def get_session(self, season: int, event_round: int, code: str) -> FakeSession:
        self.session_calls.append((season, event_round, code))
        session = FakeSession(self.fail_telemetry)
        self.sessions.append(session)
        return session


@pytest.fixture
def settings(tmp_path: Path) -> IngestionSettings:
    return IngestionSettings(
        project_root=tmp_path,
        raw_data=tmp_path / "data" / "raw",
        kaggle_raw_data=tmp_path / "data" / "raw" / "kaggle",
        fastf1_raw_data=tmp_path / "data" / "raw" / "fastf1",
        interim_data=tmp_path / "data" / "interim",
        processed_data=tmp_path / "data" / "processed",
        exports=tmp_path / "data" / "exports",
        fastf1_cache=tmp_path / ".cache",
        sqlite_database=tmp_path / "data" / "processed" / "f1.sqlite3",
        quality_reports=tmp_path / "data" / "processed" / "quality",
        logging_level="INFO",
        start_year=2018,
        end_year=2026,
        sessions=("Q", "R"),
        download_scope=("results", "laps"),
        historical_max_seasons=3,
        max_attempts=1,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        minimum_request_interval_seconds=0,
    )


@pytest.fixture
def event() -> dict[str, Any]:
    return {"RoundNumber": 1, "EventName": "Australian Grand Prix"}


def test_session_ingestion_writes_raw_processed_and_metadata(
    settings: IngestionSettings, event: dict[str, Any]
) -> None:
    source = FakeSource()
    report = ingest_session(
        season=2024,
        event=event,
        session_code="R",
        scope=("results", "laps", "pit_stops", "weather"),
        source=source,
        settings=settings,
        controller=RequestController(settings),
    )

    assert len(report.completed) == 4
    assert not report.failed
    base = (
        settings.processed_data
        / "fastf1"
        / "season=2024"
        / "round=01-australian-grand-prix"
        / "session=R"
    )
    result = json.loads((base / "results.json").read_text(encoding="utf-8"))
    assert result["metadata"]["source"] == "fastf1"
    assert result["metadata"]["season"] == 2024
    assert result["records"][0]["driver_key"] == "fastf1:2024:verstappen"
    assert result["records"][0]["Points"] is None
    pit_stops = json.loads((base / "pit_stops.json").read_text(encoding="utf-8"))
    assert len(pit_stops["records"]) == 1
    raw_result = json.loads(
        (
            settings.raw_data
            / "fastf1"
            / "season=2024"
            / "round=01-australian-grand-prix"
            / "session=R"
            / "results.json"
        ).read_text(encoding="utf-8")
    )
    assert "driver_key" not in raw_result["records"][0]


def test_rerun_replaces_snapshot_and_resume_skips_successes(
    settings: IngestionSettings, event: dict[str, Any]
) -> None:
    source = FakeSource()
    first = ingest_session(
        season=2024,
        event=event,
        session_code="R",
        scope=("results",),
        source=source,
        settings=settings,
        controller=RequestController(settings),
    )
    second = ingest_session(
        season=2024,
        event=event,
        session_code="R",
        scope=("results",),
        source=source,
        settings=settings,
        controller=RequestController(settings),
    )
    resumed = ingest_session(
        season=2024,
        event=event,
        session_code="R",
        scope=("results",),
        source=source,
        settings=settings,
        controller=RequestController(settings),
        resume=True,
    )

    assert len(first.completed) == len(second.completed) == 1
    assert len(resumed.skipped) == 1
    assert len(source.session_calls) == 2
    payload = json.loads(
        (
            settings.processed_data
            / "fastf1"
            / "season=2024"
            / "round=01-australian-grand-prix"
            / "session=R"
            / "results.json"
        ).read_text(encoding="utf-8")
    )
    assert len(payload["records"]) == 1


def test_optional_telemetry_failure_preserves_results_and_is_recorded(
    settings: IngestionSettings, event: dict[str, Any]
) -> None:
    source = FakeSource(fail_telemetry=True)
    report = ingest_session(
        season=2024,
        event=event,
        session_code="R",
        scope=("results", "telemetry"),
        source=source,
        settings=settings,
        controller=RequestController(settings),
    )

    base = (
        settings.processed_data
        / "fastf1"
        / "season=2024"
        / "round=01-australian-grand-prix"
        / "session=R"
    )
    assert (base / "results.json").is_file()
    assert not (base / "telemetry.json").exists()
    assert len(report.completed) == 1
    assert len(report.failed) == 1
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["datasets"]["results"]["status"] == "success"
    assert manifest["datasets"]["telemetry"]["status"] == "failed"
    assert "Australian Grand Prix R telemetry" in report.failed[0]


def test_dry_run_does_not_open_or_write_a_session(
    settings: IngestionSettings, event: dict[str, Any]
) -> None:
    source = FakeSource()
    report = ingest_session(
        season=2024,
        event=event,
        session_code="R",
        scope=("results",),
        source=source,
        settings=settings,
        controller=RequestController(settings),
        dry_run=True,
    )

    assert report.planned == ["2024 Australian Grand Prix R results"]
    assert not source.session_calls
    assert not settings.processed_data.exists()


def test_qualifying_results_use_a_distinct_dataset(
    settings: IngestionSettings, event: dict[str, Any]
) -> None:
    report = ingest_session(
        season=2024,
        event=event,
        session_code="Q",
        scope=("results",),
        source=FakeSource(),
        settings=settings,
        controller=RequestController(settings),
    )

    base = (
        settings.processed_data
        / "fastf1"
        / "season=2024"
        / "round=01-australian-grand-prix"
        / "session=Q"
    )
    assert len(report.completed) == 1
    assert (base / "qualifying_results.json").is_file()
    assert not (base / "results.json").exists()


def test_event_selection_accepts_round_and_exact_name() -> None:
    schedule = pd.DataFrame(
        {
            "RoundNumber": [1, 2],
            "EventName": ["Australian Grand Prix", "Chinese Grand Prix"],
        }
    )

    assert select_event(schedule, "1")["EventName"] == "Australian Grand Prix"
    assert select_event(schedule, "chinese grand prix")["RoundNumber"] == 2
    with pytest.raises(ValueError, match="matched 0 events"):
        select_event(schedule, "Australia")


def test_season_ingestion_persists_schedule_and_resume_is_incremental(
    settings: IngestionSettings,
) -> None:
    source = FakeSource()
    first = ingest_season(
        season=2024,
        source=source,
        settings=settings,
        controller=RequestController(settings),
        sessions=("R",),
        scope=("results",),
    )
    resumed = ingest_season(
        season=2024,
        source=source,
        settings=settings,
        controller=RequestController(settings),
        sessions=("R",),
        scope=("results",),
        resume=True,
    )

    schedule = (
        settings.processed_data / "fastf1" / "season=2024" / "schedule.json"
    )
    assert schedule.is_file()
    assert len(first.completed) == 1
    assert len(resumed.skipped) == 1
    assert len(source.schedule_calls) == 2
    assert len(source.session_calls) == 1


def test_retry_retries_timeout_but_not_data_errors(
    settings: IngestionSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = replace(
        settings, max_attempts=3, backoff_base_seconds=0, backoff_max_seconds=0
    )
    controller = RequestController(settings)
    monkeypatch.setattr("f1_intelligence.data.retry.time.sleep", lambda _: None)
    attempts = 0

    def flaky_operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary timeout")
        return "ready"

    assert controller.call(flaky_operation, "fixture request") == "ready"
    assert attempts == 2

    attempts = 0

    def invalid_data() -> None:
        nonlocal attempts
        attempts += 1
        raise ValueError("invalid source schema")

    with pytest.raises(IngestionError, match="invalid source schema"):
        controller.call(invalid_data, "invalid fixture")
    assert attempts == 1

    attempts = 0

    def temporary_service_error() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError(
                "https://example.invalid", 503, "unavailable", None, None
            )
        return "recovered"

    assert controller.call(temporary_service_error, "service fixture") == "recovered"
    assert attempts == 2

    attempts = 0

    def missing_resource() -> None:
        nonlocal attempts
        attempts += 1
        raise HTTPError("https://example.invalid", 404, "not found", None, None)

    with pytest.raises(IngestionError, match="404"):
        controller.call(missing_resource, "missing fixture")
    assert attempts == 1
