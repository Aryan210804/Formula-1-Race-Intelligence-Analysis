"""Build analysis-ready records and quality findings from raw FastF1 JSON."""

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from f1_intelligence.transformations.common import (
    QualityIssue, add_issue, source_text,
)
from f1_intelligence.transformations.events import (
    normalize_events, normalize_scheduled_sessions,
)
from f1_intelligence.transformations.laps import (
    normalize_laps, normalize_observations, normalize_pit_stops,
)
from f1_intelligence.transformations.people import normalize_people
from f1_intelligence.transformations.results import normalize_results

LOGGER = logging.getLogger(__name__)
TABLES = (
    "circuits", "events", "drivers", "constructors", "sessions",
    "race_results", "qualifying_results", "session_results", "laps",
    "pit_stops", "weather", "telemetry",
)
REQUIRED_COLUMNS: dict[str, tuple[tuple[str, ...], ...]] = {
    "schedule": (("RoundNumber",), ("EventName",)),
    "results": (("DriverId", "DriverNumber"),),
    "qualifying_results": (("DriverId", "DriverNumber"),),
    "session_results": (("DriverId", "DriverNumber"),),
    "laps": (("DriverId", "Driver", "DriverNumber"), ("LapNumber",)),
    "pit_stops": (("DriverId", "Driver", "DriverNumber"), ("LapNumber",)),
    "weather": (("Time", "Date"),),
    "telemetry": (("Time", "Date"), ("DriverId", "Driver", "DriverNumber")),
}


class TransformationError(RuntimeError):
    """Raised when source snapshots cannot be safely read."""


@dataclass
class TransformationBundle:
    """Normalized rows, rejected source records, and quality report data."""

    tables: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {name: [] for name in TABLES}
    )
    rejected_records: list[dict[str, Any]] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    source_files: list[str] = field(default_factory=list)


def transform_raw_data(raw_root: Path, previous_report: Path | None = None) -> TransformationBundle:
    """Rebuild all normalized tables solely from immutable raw JSON snapshots."""
    files = sorted(raw_root.rglob("*.json"))
    bundle = TransformationBundle()
    if not files:
        add_issue(
            bundle.issues,
            severity="warning",
            code="no_raw_data",
            message=f"No raw JSON datasets found under {raw_root}",
            source_file=str(raw_root),
        )
        return bundle

    snapshots: list[tuple[Path, dict[str, Any]]] = []
    for path in files:
        try:
            with path.open(encoding="utf-8") as source:
                payload = json.load(source)
        except (OSError, json.JSONDecodeError) as exc:
            raise TransformationError(f"Cannot read raw dataset {path}: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
            raise TransformationError(
                f"Raw dataset {path} must contain a metadata object and records list"
            )
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            raise TransformationError(f"Raw dataset {path} has no metadata object")
        snapshots.append((path, payload))
        bundle.source_files.append(str(path))

    schedules: dict[int, tuple[Path, dict[str, Any]]] = {}
    for path, payload in snapshots:
        metadata = payload["metadata"]
        if metadata.get("dataset") == "schedule":
            try:
                season = int(metadata["season"])
            except (KeyError, TypeError, ValueError) as exc:
                add_issue(
                    bundle.issues, severity="error", code="invalid_schedule_metadata",
                    message="Schedule metadata has no valid season",
                    source_file=str(path),
                )
                continue
            if season in schedules:
                add_issue(
                    bundle.issues, severity="error", code="duplicate_season_schedule",
                    message=f"More than one schedule snapshot found for season {season}",
                    source_file=str(path),
                )
            schedules[season] = (path, payload)

    event_lookup: dict[str, dict[str, Any]] = {}
    for season, (path, payload) in sorted(schedules.items()):
        records = payload["records"]
        schema_valid = _validate_source_schema(
            payload, "schedule", path, bundle, record_count=len(records)
        )
        if not schema_valid:
            bundle.rejected_records.extend(
                _make_reject(
                    "events", str(path), index, record, ["missing_required_columns"]
                )
                for index, record in enumerate(records)
            )
            _count_source(bundle, payload)
            continue
        events, circuits = normalize_events(
            records, season, str(path), bundle.issues
        )
        seen_rounds: set[int] = set()
        valid_rounds = {event["round_number"] for event in events}
        for index, record in enumerate(records):
            try:
                round_number = int(record.get("RoundNumber"))
            except (TypeError, ValueError):
                bundle.rejected_records.append(
                    _make_reject(
                        "events", str(path), index, record, ["invalid_event_round"]
                    )
                )
                continue
            if round_number <= 0:
                continue
            if round_number in seen_rounds:
                bundle.rejected_records.append(
                    _make_reject(
                        "events", str(path), index, record, ["duplicate_event_key"]
                    )
                )
            elif round_number not in valid_rounds:
                bundle.rejected_records.append(
                    _make_reject(
                        "events", str(path), index, record, ["missing_event_name"]
                    )
                )
            seen_rounds.add(round_number)
        bundle.tables["events"].extend(events)
        bundle.tables["circuits"].extend(circuits)
        for event in events:
            event_lookup[event["event_id"]] = event
        bundle.tables["sessions"].extend(
            normalize_scheduled_sessions(records, season, str(path), bundle.issues)
        )
        _count_source(bundle, payload)

    driver_aliases: dict[str, str] = {}
    known_driver_ids: set[str] = set()
    known_constructor_ids: set[str] = set()
    result_snapshots = [
        (path, payload)
        for path, payload in snapshots
        if payload["metadata"].get("dataset")
        in {"results", "qualifying_results", "session_results"}
    ]
    for path, payload in result_snapshots:
        metadata = payload["metadata"]
        season, event_id, session_code = _source_identity(
            metadata, path, bundle, event_lookup
        )
        dataset = str(metadata.get("dataset"))
        expected_session = {
            "results": "R",
            "qualifying_results": "Q",
        }.get(dataset)
        if expected_session and session_code != expected_session:
            add_issue(
                bundle.issues, severity="error", code="inconsistent_dataset_session",
                message=(
                    f"{dataset} dataset must identify session {expected_session}, "
                    f"not {session_code or 'missing'}"
                ),
                source_file=str(path),
            )
            event_id = None
        records = payload["records"]
        schema_valid = _validate_source_schema(
            payload, dataset, path, bundle, len(records)
        )
        if not schema_valid:
            bundle.rejected_records.extend(
                _make_reject(
                    dataset, str(path), index, record, ["missing_required_columns"]
                )
                for index, record in enumerate(records)
            )
            _count_source(bundle, payload)
            continue
        drivers, constructors = normalize_people(
            records, season, str(path), bundle.issues
        )
        for driver in drivers:
            bundle.tables["drivers"].append(driver)
            known_driver_ids.add(driver["driver_id"])
        for constructor in constructors:
            bundle.tables["constructors"].append(constructor)
            known_constructor_ids.add(constructor["constructor_id"])
        for record in records:
            driver_id = _driver_id(record, season)
            if driver_id:
                for alias in (
                    record.get("DriverId"), record.get("DriverNumber"),
                    record.get("Abbreviation"), record.get("Driver"),
                ):
                    if alias is not None and str(alias).strip():
                        driver_aliases[str(alias).strip()] = driver_id
        table = {
            "qualifying_results": "qualifying_results",
            "results": "race_results",
            "session_results": "session_results",
        }[dataset]
        _ensure_session(bundle, event_id, session_code, metadata)
        rows, rejects = normalize_results(
            records,
            season=season,
            event_id=event_id,
            session_code=session_code,
            dataset=dataset,
            source_file=str(path),
            issues=bundle.issues,
        )
        for row in rows:
            if row["driver_id"] not in known_driver_ids:
                add_issue(
                    bundle.issues, severity="error", code="missing_driver_dimension",
                    message=f"Result references driver {row['driver_id']!r} absent from driver dimension",
                    source_file=str(path),
                )
                rejects.append(
                    _make_reject(
                        table, str(path), None, row, ["missing_driver_dimension"]
                    )
                )
                continue
            constructor_id = row["constructor_id"]
            if constructor_id is not None and constructor_id not in known_constructor_ids:
                add_issue(
                    bundle.issues, severity="error", code="missing_constructor_dimension",
                    message=f"Result references constructor {constructor_id!r} absent from constructor dimension",
                    source_file=str(path),
                )
                rejects.append(
                    _make_reject(
                        table, str(path), None, row, ["missing_constructor_dimension"]
                    )
                )
                continue
            if event_id is None or event_id not in event_lookup:
                add_issue(
                    bundle.issues, severity="error", code="broken_event_relationship",
                    message=f"Result references unavailable event {event_id!r}",
                    source_file=str(path),
                )
                rejects.append(
                    _make_reject(table, str(path), None, row, ["broken_event_relationship"])
                )
                continue
            bundle.tables[table].append(row)
        bundle.rejected_records.extend(rejects)
        _count_source(bundle, payload)

    for path, payload in snapshots:
        dataset = str(payload["metadata"].get("dataset", "unknown"))
        if dataset in {
            "schedule", "results", "qualifying_results", "session_results"
        }:
            continue
        metadata = payload["metadata"]
        season, event_id, session_code = _source_identity(
            metadata, path, bundle, event_lookup
        )
        records = payload["records"]
        schema_valid = _validate_source_schema(
            payload, dataset, path, bundle, len(records)
        )
        if not schema_valid:
            bundle.rejected_records.extend(
                _make_reject(
                    dataset, str(path), index, record, ["missing_required_columns"]
                )
                for index, record in enumerate(records)
            )
            _count_source(bundle, payload)
            continue
        _ensure_session(bundle, event_id, session_code, metadata)
        if dataset in {"laps", "pit_stops"}:
            if dataset == "laps":
                rows, rejected = normalize_laps(
                    records, event_id, session_code, str(path), bundle.issues
                )
                fact_table = "laps"
            else:
                rows, rejected = normalize_pit_stops(
                    records, event_id, session_code, str(path), bundle.issues
                )
                fact_table = "pit_stops"
            bundle.rejected_records.extend(rejected)
            for row in rows:
                driver_id = driver_aliases.get(row["driver_id"], row["driver_id"])
                row["driver_id"] = driver_id
                if driver_id not in known_driver_ids:
                    add_issue(
                        bundle.issues, severity="error", code="missing_driver_dimension",
                        message=f"{fact_table} row references unknown driver {driver_id!r}",
                        source_file=str(path),
                    )
                    bundle.rejected_records.append(
                        _make_reject(fact_table, str(path), None, row, ["missing_driver_dimension"])
                    )
                elif event_id not in event_lookup:
                    add_issue(
                        bundle.issues, severity="error", code="broken_event_relationship",
                        message=f"{fact_table} row references unavailable event {event_id!r}",
                        source_file=str(path),
                    )
                    bundle.rejected_records.append(
                        _make_reject(fact_table, str(path), None, row, ["broken_event_relationship"])
                    )
                else:
                    bundle.tables[fact_table].append(row)
        elif dataset in {"weather", "telemetry"}:
            rows, rejected = normalize_observations(
                records, dataset=dataset, event_id=event_id,
                session_code=session_code, source_file=str(path), issues=bundle.issues,
            )
            bundle.rejected_records.extend(rejected)
            fact_table = dataset
            for row in rows:
                if dataset == "telemetry":
                    row["driver_id"] = driver_aliases.get(row["driver_id"], row["driver_id"])
                    if row["driver_id"] not in known_driver_ids:
                        add_issue(
                            bundle.issues, severity="error", code="missing_driver_dimension",
                            message=f"Telemetry row references unknown driver {row['driver_id']!r}",
                            source_file=str(path),
                        )
                        bundle.rejected_records.append(
                            _make_reject(fact_table, str(path), row["sample_number"], row, ["missing_driver_dimension"])
                        )
                        continue
                if event_id not in event_lookup:
                    add_issue(
                        bundle.issues, severity="error", code="broken_event_relationship",
                        message=f"{fact_table} row references unavailable event {event_id!r}",
                        source_file=str(path),
                    )
                    bundle.rejected_records.append(
                        _make_reject(fact_table, str(path), row.get("sample_number"), row, ["broken_event_relationship"])
                    )
                else:
                    bundle.tables[fact_table].append(row)
        else:
            add_issue(
                bundle.issues, severity="warning", code="unsupported_raw_dataset",
                message=f"No transformer registered for raw dataset {dataset!r}",
                source_file=str(path),
            )
        _count_source(bundle, payload)

    _deduplicate_dimensions(bundle)
    _deduplicate_facts(bundle)
    _check_null_rates(bundle)
    _check_previous_counts(bundle, previous_report)
    return bundle


def build_quality_report(bundle: TransformationBundle) -> dict[str, Any]:
    """Create a machine-readable summary of transformations and quality."""
    issue_counts = Counter(issue.code for issue in bundle.issues)
    return {
        "source_files": bundle.source_files,
        "source_record_counts": bundle.source_counts,
        "transformed_row_counts": {
            table: len(bundle.tables[table]) for table in TABLES
        },
        "rejected_record_count": len(bundle.rejected_records),
        "issue_counts": dict(sorted(issue_counts.items())),
        "issues": [issue.to_dict() for issue in bundle.issues],
        "rejected_records": bundle.rejected_records,
        "error_count": sum(issue.severity == "error" for issue in bundle.issues),
        "warning_count": sum(issue.severity == "warning" for issue in bundle.issues),
    }


def render_quality_summary(report: dict[str, Any]) -> str:
    """Render the machine report as a readable Markdown summary."""
    lines = [
        "# Data quality report",
        "",
        f"- Source files: {len(report['source_files'])}",
        f"- Rejected records: {report['rejected_record_count']}",
        f"- Errors: {report['error_count']}",
        f"- Warnings: {report['warning_count']}",
        "",
        "## Transformed rows",
        "",
        "| Table | Rows |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {name} | {count} |"
        for name, count in report["transformed_row_counts"].items()
    )
    lines.extend(["", "## Quality findings", ""])
    if report["issues"]:
        lines.extend(
            f"- **{issue['severity'].upper()} `{issue['code']}`** "
            f"{issue['message']} ({issue['source_file']})"
            for issue in report["issues"]
        )
    else:
        lines.append("No quality findings.")
    lines.append("")
    return "\n".join(lines)


def _source_identity(
    metadata: dict[str, Any],
    path: Path,
    bundle: TransformationBundle,
    event_lookup: dict[str, dict[str, Any]],
) -> tuple[int, str | None, str]:
    try:
        season = int(metadata["season"])
    except (KeyError, TypeError, ValueError):
        season = 0
        add_issue(
            bundle.issues, severity="error", code="invalid_dataset_season",
            message="Dataset metadata has no valid season",
            source_file=str(path),
        )
    event_id = source_text(metadata.get("event_id"))
    session_code = source_text(metadata.get("session")) or ""
    if event_id:
        event = event_lookup.get(event_id)
        if event is None:
            add_issue(
                bundle.issues, severity="error", code="broken_event_relationship",
                message=f"Dataset event_id {event_id!r} is absent from all schedules",
                source_file=str(path),
            )
            event_id = None
        else:
            try:
                metadata_round = int(metadata.get("event_round"))
            except (TypeError, ValueError):
                metadata_round = None
            if metadata_round is not None and metadata_round != event["round_number"]:
                add_issue(
                    bundle.issues, severity="error", code="inconsistent_event_round",
                    message=f"Metadata round {metadata_round} does not match schedule round {event['round_number']}",
                    source_file=str(path),
                )
                event_id = None
            try:
                metadata_event_season = int(event_id.split(":", maxsplit=1)[0])
            except (ValueError, AttributeError):
                metadata_event_season = None
            if metadata_event_season is not None and metadata_event_season != season:
                add_issue(
                    bundle.issues, severity="error", code="inconsistent_season_event",
                    message=f"Dataset season {season} conflicts with event identifier {event_id}",
                    source_file=str(path),
                )
                event_id = None
            if event["season"] != season:
                add_issue(
                    bundle.issues, severity="error", code="inconsistent_season_event",
                    message=f"Dataset season {season} conflicts with event {event_id}",
                    source_file=str(path),
                )
                event_id = None
            metadata_name = source_text(metadata.get("event_name"))
            if metadata_name and metadata_name.casefold() != event["event_name"].casefold():
                add_issue(
                    bundle.issues, severity="error", code="inconsistent_event_name",
                    message=f"Metadata event {metadata_name!r} does not match schedule {event['event_name']!r}",
                    source_file=str(path),
                )
                event_id = None
    if event_id and session_code:
        session_id = f"{event_id}:{session_code}"
        if not any(row["session_id"] == session_id for row in bundle.tables["sessions"]):
            _ensure_session(bundle, event_id, session_code, metadata)
    return season, event_id, session_code


def _ensure_session(
    bundle: TransformationBundle,
    event_id: str | None,
    session_code: str,
    metadata: dict[str, Any],
) -> None:
    if not event_id or not session_code:
        return
    session_id = f"{event_id}:{session_code}"
    if any(row["session_id"] == session_id for row in bundle.tables["sessions"]):
        return
    bundle.tables["sessions"].append(
        {
            "session_id": session_id,
            "event_id": event_id,
            "session_code": session_code,
            "session_name": session_code,
            "scheduled_start": None,
        }
    )


def _validate_source_schema(
    payload: dict[str, Any],
    dataset: str,
    path: Path,
    bundle: TransformationBundle,
    record_count: int,
) -> bool:
    required_groups = REQUIRED_COLUMNS.get(dataset)
    schema_valid = True
    if required_groups and payload["records"]:
        present = set().union(*(set(record) for record in payload["records"]))
        missing = [group for group in required_groups if not set(group) & present]
        for group in missing:
            schema_valid = False
            add_issue(
                bundle.issues, severity="error", code="missing_required_columns",
                message=(
                    f"{dataset} requires at least one of columns "
                    f"{', '.join(group)}"
                ),
                source_file=str(path),
            )
    expected_count = payload.get("metadata", {}).get("record_count")
    if expected_count is not None:
        try:
            expected_count = int(expected_count)
        except (TypeError, ValueError):
            expected_count = None
        if expected_count is not None and expected_count != record_count:
            add_issue(
                bundle.issues, severity="warning", code="source_row_count_mismatch",
                message=f"Metadata says {expected_count} rows but raw file contains {record_count}",
                source_file=str(path),
            )
    return schema_valid


def _count_source(bundle: TransformationBundle, payload: dict[str, Any]) -> None:
    metadata = payload["metadata"]
    key = ":".join(
        str(metadata.get(part) or "")
        for part in ("season", "event_round", "session", "dataset")
    )
    bundle.source_counts[key] = len(payload["records"])


def _driver_id(record: dict[str, Any], season: int) -> str | None:
    driver_id = source_text(record.get("DriverId"))
    if driver_id:
        return driver_id
    number = source_text(record.get("DriverNumber"))
    return f"fastf1:{season}:number:{number}" if number else None


def _deduplicate_dimensions(bundle: TransformationBundle) -> None:
    for table, key in (
        ("circuits", "circuit_id"), ("events", "event_id"),
        ("drivers", "driver_id"), ("constructors", "constructor_id"),
        ("sessions", "session_id"),
    ):
        unique: dict[str, dict[str, Any]] = {}
        for row in bundle.tables[table]:
            unique.setdefault(row[key], row)
        bundle.tables[table] = list(unique.values())


def _deduplicate_facts(bundle: TransformationBundle) -> None:
    keys = {
        "race_results": ("event_id", "session_id", "driver_id"),
        "qualifying_results": ("event_id", "session_id", "driver_id"),
        "session_results": ("event_id", "session_id", "driver_id"),
        "laps": ("session_id", "driver_id", "lap_number"),
        "pit_stops": ("session_id", "driver_id", "lap_number"),
        "weather": ("session_id", "sample_number"),
        "telemetry": ("session_id", "driver_id", "sample_number"),
    }
    for table, columns in keys.items():
        seen: set[tuple[Any, ...]] = set()
        unique: list[dict[str, Any]] = []
        for row in bundle.tables[table]:
            key = tuple(row.get(column) for column in columns)
            if key in seen:
                add_issue(
                    bundle.issues, severity="error", code=f"duplicate_{table}_key",
                    message=f"Duplicate {table} natural key {key} across source snapshots",
                    source_file="normalized bundle",
                    record=row,
                )
                bundle.rejected_records.append(
                    _make_reject(
                        table, "normalized bundle", None, row, [f"duplicate_{table}_key"]
                    )
                )
                continue
            seen.add(key)
            unique.append(row)
        bundle.tables[table] = unique


def _check_null_rates(bundle: TransformationBundle) -> None:
    for table, column, maximum in (
        ("drivers", "full_name", 0.5),
        ("constructors", "constructor_name", 0.5),
        ("events", "event_name", 0.0),
    ):
        rows = bundle.tables[table]
        if not rows:
            continue
        null_rate = sum(row.get(column) is None for row in rows) / len(rows)
        if null_rate > maximum:
            add_issue(
                bundle.issues, severity="warning", code="unexpected_null_rate",
                message=f"{table}.{column} null rate {null_rate:.1%} exceeds {maximum:.1%}",
                source_file="transformed bundle",
            )


def _check_previous_counts(bundle: TransformationBundle, previous_report: Path | None) -> None:
    if previous_report is None or not previous_report.is_file():
        return
    try:
        previous = json.loads(previous_report.read_text(encoding="utf-8"))
        previous_counts = previous.get("source_record_counts", {})
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        LOGGER.warning("Cannot compare prior quality report %s: %s", previous_report, exc)
        return
    for key, count in bundle.source_counts.items():
        old_count = previous_counts.get(key)
        if not isinstance(old_count, int) or max(old_count, count) < 20:
            continue
        change = abs(count - old_count) / max(old_count, 1)
        if change > 0.5:
            add_issue(
                bundle.issues, severity="warning", code="suspicious_row_count_change",
                message=f"Source row count changed from {old_count} to {count} for {key}",
                source_file="current ingestion run",
            )


def _make_reject(
    table: str,
    source_file: str,
    index: int | None,
    record: dict[str, Any],
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "target_table": table,
        "source_file": source_file,
        "record_index": index,
        "reason_codes": reasons,
        "source_record": record,
    }
