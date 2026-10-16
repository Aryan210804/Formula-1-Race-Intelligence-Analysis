"""Incremental, resumable FastF1 session ingestion."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from f1_intelligence.data.laps import extract_laps, extract_pit_stops
from f1_intelligence.data.persistence import (
    dataset_directory,
    write_dataset,
)
from f1_intelligence.data.results import extract_results
from f1_intelligence.data.retry import RequestController
from f1_intelligence.data.schedule import get_season_schedule
from f1_intelligence.data.settings import (
    ALLOWED_SCOPES,
    ALLOWED_SESSIONS,
    IngestionSettings,
)
from f1_intelligence.data.telemetry import extract_telemetry
from f1_intelligence.data.weather import extract_weather

LOGGER = logging.getLogger(__name__)
SUPPORTED_SESSIONS = ALLOWED_SESSIONS


@dataclass
class IngestionReport:
    """Outcomes from a bounded ingestion run."""

    planned: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        """Whether one or more dataset extractions failed."""
        return bool(self.failed)

    def extend(self, other: "IngestionReport") -> None:
        """Append outcomes from another session or season."""
        self.planned.extend(other.planned)
        self.completed.extend(other.completed)
        self.skipped.extend(other.skipped)
        self.failed.extend(other.failed)


def ingest_schedule(
    season: int,
    source: Any,
    settings: IngestionSettings,
    controller: RequestController,
) -> pd.DataFrame:
    """Fetch and persist the season schedule in raw and processed locations."""
    settings.validate_season(season)
    schedule = get_season_schedule(source, controller, season)
    write_dataset(
        raw_root=settings.fastf1_raw_data,
        processed_root=settings.processed_data / "fastf1",
        season=season,
        event_round=None,
        event_name="schedule",
        session="",
        dataset="schedule",
        frame=schedule,
    )
    return schedule


def ingest_session(
    *,
    season: int,
    event: pd.Series | dict[str, Any],
    session_code: str,
    scope: tuple[str, ...],
    source: Any,
    settings: IngestionSettings,
    controller: RequestController,
    resume: bool = False,
    dry_run: bool = False,
) -> IngestionReport:
    """Ingest one event session, isolating failures by requested dataset."""
    settings.validate_season(season)
    session_code = session_code.strip().upper()
    if session_code not in SUPPORTED_SESSIONS:
        raise ValueError(
            f"Unsupported session code {session_code!r}; choose from "
            f"{', '.join(sorted(SUPPORTED_SESSIONS))}"
        )
    unknown_scope = set(scope) - ALLOWED_SCOPES
    if not scope or unknown_scope:
        raise ValueError(
            f"Invalid extraction scope: {', '.join(sorted(unknown_scope)) or 'empty'}"
        )
    event_data = event.to_dict() if isinstance(event, pd.Series) else dict(event)
    event_name = str(event_data.get("EventName") or "Unknown event")
    event_round = _round_number(event_data.get("RoundNumber"))
    if event_round is None:
        raise ValueError(f"Event {event_name!r} has no valid RoundNumber")

    dataset_names = _dataset_names(session_code, scope)
    report = IngestionReport()
    manifest_path = _manifest_path(settings, season, event_round, event_name, session_code)
    manifest = _read_manifest(manifest_path)
    pending: list[str] = []
    for dataset in dataset_names:
        processed_path = _processed_path(
            settings, season, event_round, event_name, session_code, dataset
        )
        prior = manifest.get("datasets", {}).get(dataset, {})
        if (
            resume
            and prior.get("status") == "success"
            and processed_path.is_file()
        ):
            report.skipped.append(_label(season, event_name, session_code, dataset))
        else:
            pending.append(dataset)
    if not pending or dry_run:
        if dry_run:
            report.planned.extend(
                _label(season, event_name, session_code, item) for item in pending
            )
        return report

    groups: dict[str, tuple[tuple[str, ...], dict[str, bool], Callable[[Any], dict[str, pd.DataFrame]]]] = {
        "results": (
            tuple(name for name in pending if name in {"results", "qualifying_results"}),
            {"laps": False, "telemetry": False, "weather": False},
            lambda loaded: {
                _dataset_names(session_code, ("results",))[0]: extract_results(loaded)
            },
        ),
        "laps": (
            tuple(name for name in pending if name in {"laps", "pit_stops"}),
            {"laps": True, "telemetry": False, "weather": False},
            _extract_lap_datasets,
        ),
        "weather": (
            tuple(name for name in pending if name == "weather"),
            {"laps": True, "telemetry": False, "weather": True},
            lambda loaded: {"weather": extract_weather(loaded)},
        ),
        "telemetry": (
            tuple(name for name in pending if name == "telemetry"),
            {"laps": True, "telemetry": True, "weather": False},
            lambda loaded: {"telemetry": extract_telemetry(loaded)},
        ),
    }
    for group_name, (datasets, load_flags, extractor) in groups.items():
        if not datasets:
            continue
        label = f"{season} {event_name} {session_code} {group_name}"
        try:
            # FastF1 sessions load once; separate handles keep optional data failures isolated.
            session = controller.call(
                lambda: source.get_session(season, event_round, session_code),
                f"{label} session initialization",
            )
            controller.call(
                lambda flags=load_flags: session.load(
                    **flags, messages=False
                ),
                f"{label} FastF1 load",
            )
            extracted = extractor(session)
        except Exception as exc:
            LOGGER.exception("%s extraction failed", label)
            for dataset in datasets:
                _record_outcome(
                    report,
                    manifest,
                    manifest_path,
                    dataset,
                    "failed",
                    str(exc),
                    season,
                    event_name,
                    session_code,
                )
            continue

        for dataset in datasets:
            frame = extracted.get(dataset)
            if frame is None or frame.empty:
                _record_outcome(
                    report,
                    manifest,
                    manifest_path,
                    dataset,
                    "skipped",
                    "No source records were available for this dataset",
                    season,
                    event_name,
                    session_code,
                )
                continue
            try:
                extra = (
                    {"derivation": "FastF1 lap PitInTime/PitOutTime observations"}
                    if dataset == "pit_stops"
                    else None
                )
                write_dataset(
                    raw_root=settings.fastf1_raw_data,
                    processed_root=settings.processed_data / "fastf1",
                    season=season,
                    event_round=event_round,
                    event_name=event_name,
                    session=session_code,
                    dataset=dataset,
                    frame=frame,
                    extra_metadata=extra,
                )
                _record_outcome(
                    report,
                    manifest,
                    manifest_path,
                    dataset,
                    "success",
                    None,
                    season,
                    event_name,
                    session_code,
                )
            except Exception as exc:
                LOGGER.exception("%s persistence failed", label)
                _record_outcome(
                    report,
                    manifest,
                    manifest_path,
                    dataset,
                    "failed",
                    str(exc),
                    season,
                    event_name,
                    session_code,
                )
    return report


def ingest_season(
    *,
    season: int,
    source: Any,
    settings: IngestionSettings,
    controller: RequestController,
    sessions: tuple[str, ...] | None = None,
    scope: tuple[str, ...] | None = None,
    resume: bool = False,
    dry_run: bool = False,
) -> IngestionReport:
    """Ingest configured sessions for every championship event in a season."""
    settings.validate_season(season)
    schedule = get_season_schedule(source, controller, season)
    if not dry_run:
        write_dataset(
            raw_root=settings.fastf1_raw_data,
            processed_root=settings.processed_data / "fastf1",
            season=season,
            event_round=None,
            event_name="schedule",
            session="",
            dataset="schedule",
            frame=schedule,
        )
    report = IngestionReport()
    if "RoundNumber" not in schedule:
        raise ValueError(f"Season {season} schedule has no RoundNumber column")
    events = schedule.loc[
        pd.to_numeric(schedule["RoundNumber"], errors="coerce") > 0
    ]
    if events.empty:
        raise ValueError(f"Season {season} schedule contains no championship events")
    for _, event in events.iterrows():
        for session_code in sessions or settings.sessions:
            event_report = ingest_session(
                season=season,
                event=event,
                session_code=session_code,
                scope=scope or settings.download_scope,
                source=source,
                settings=settings,
                controller=controller,
                resume=resume,
                dry_run=dry_run,
            )
            report.extend(event_report)
    return report


def _extract_lap_datasets(session: Any) -> dict[str, pd.DataFrame]:
    laps = extract_laps(session)
    return {"laps": laps, "pit_stops": extract_pit_stops(laps)}


def _dataset_names(session_code: str, scope: tuple[str, ...]) -> list[str]:
    names: list[str] = []
    for dataset in scope:
        if dataset == "results":
            if session_code == "Q":
                name = "qualifying_results"
            elif session_code == "R":
                name = "results"
            else:
                name = "session_results"
        else:
            name = dataset
        if name not in names:
            names.append(name)
    return names


def _round_number(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _session_directory(
    settings: IngestionSettings,
    season: int,
    event_round: int,
    event_name: str,
    session_code: str,
) -> Path:
    return dataset_directory(
        settings.processed_data / "fastf1",
        season,
        event_round,
        event_name,
        session_code,
    )


def _processed_path(
    settings: IngestionSettings,
    season: int,
    event_round: int,
    event_name: str,
    session_code: str,
    dataset: str,
) -> Path:
    return _session_directory(
        settings, season, event_round, event_name, session_code
    ) / f"{dataset}.json"


def _manifest_path(
    settings: IngestionSettings,
    season: int,
    event_round: int,
    event_name: str,
    session_code: str,
) -> Path:
    return _session_directory(
        settings, season, event_round, event_name, session_code
    ) / "manifest.json"


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as manifest_file:
            data = json.load(manifest_file)
    except FileNotFoundError:
        return {"datasets": {}}
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Cannot read ingestion manifest %s: %s", path, exc)
        return {"datasets": {}}
    return data if isinstance(data, dict) else {"datasets": {}}


def _record_outcome(
    report: IngestionReport,
    manifest: dict[str, Any],
    manifest_path: Path,
    dataset: str,
    status: str,
    error: str | None,
    season: int,
    event_name: str,
    session_code: str,
) -> None:
    label = _label(season, event_name, session_code, dataset)
    manifest.setdefault("datasets", {})[dataset] = {
        "status": status,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }
    manifest["season"] = season
    manifest["event"] = event_name
    manifest["session"] = session_code
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = manifest_path.with_name(".manifest.json.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(manifest, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
        temporary_path.replace(manifest_path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise
    if status == "success":
        report.completed.append(label)
    elif status == "failed":
        LOGGER.error("%s failed: %s", label, error)
        report.failed.append(label)
    else:
        LOGGER.info("%s skipped: %s", label, error)
        report.skipped.append(label)


def _label(season: int, event_name: str, session_code: str, dataset: str) -> str:
    return f"{season} {event_name} {session_code} {dataset}"
