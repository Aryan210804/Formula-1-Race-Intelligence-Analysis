"""Race and qualifying result normalization and validation."""

from typing import Any

from f1_intelligence.transformations.common import (
    QualityIssue, add_issue, number, source_text, status_group, time_seconds,
)


def normalize_results(
    records: list[dict[str, Any]],
    *,
    season: int,
    event_id: str | None,
    session_code: str,
    dataset: str,
    source_file: str,
    issues: list[QualityIssue],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return cleaned race or qualifying rows and source-preserving rejects."""
    rows: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    table = {
        "qualifying_results": "qualifying_results",
        "results": "race_results",
        "session_results": "session_results",
    }.get(dataset, "race_results")
    for index, record in enumerate(records):
        reason_codes: list[str] = []
        driver_id = source_text(record.get("DriverId"))
        if driver_id is None:
            driver_number = source_text(record.get("DriverNumber"))
            driver_id = f"fastf1:{season}:number:{driver_number}" if driver_number else None
        if event_id is None:
            reason_codes.append("missing_event_identifier")
        if driver_id is None:
            reason_codes.append("missing_driver_identifier")
        position_source = record.get("Position")
        position = number(position_source)
        if source_text(position_source) is not None and position is None:
            add_issue(
                issues, severity="error", code="invalid_position",
                message=f"Position {position_source!r} is not numeric",
                source_file=source_file, record_index=index, record=record,
            )
            reason_codes.append("invalid_position")
        if position is not None and (position <= 0 or not position.is_integer()):
            add_issue(
                issues, severity="error", code="invalid_position",
                message=f"Position {record.get('Position')!r} must be a positive integer",
                source_file=source_file, record_index=index, record=record,
            )
            reason_codes.append("invalid_position")
        position_int = int(position) if position is not None and position.is_integer() and position > 0 else None
        grid_source = record.get("GridPosition")
        grid = number(grid_source)
        if source_text(grid_source) is not None and grid is None:
            add_issue(
                issues, severity="error", code="invalid_grid_position",
                message=f"GridPosition {grid_source!r} is not numeric",
                source_file=source_file, record_index=index, record=record,
            )
            reason_codes.append("invalid_grid_position")
        grid_int = int(grid) if grid is not None and grid.is_integer() and grid > 0 else None
        if grid is not None and (grid <= 0 or not grid.is_integer()):
            add_issue(
                issues, severity="error", code="invalid_grid_position",
                message=f"GridPosition {record.get('GridPosition')!r} must be a positive integer when supplied",
                source_file=source_file, record_index=index, record=record,
            )
            reason_codes.append("invalid_grid_position")
        key = (event_id or "", session_code, driver_id or "")
        if driver_id is not None and key in seen:
            add_issue(
                issues, severity="error", code="duplicate_result_key",
                message=f"Duplicate event/session/driver result key {key}",
                source_file=source_file, record_index=index, record=record,
            )
            reason_codes.append("duplicate_result_key")
        seen.add(key)
        status = source_text(record.get("Status"))
        result_time = record.get("Time")
        result_time_s = time_seconds(result_time)
        if source_text(result_time) is not None and result_time_s is None:
            add_issue(
                issues, severity="error", code="invalid_result_time",
                message=f"Time {result_time!r} is not a valid non-negative time",
                source_file=source_file, record_index=index, record=record,
            )
            reason_codes.append("invalid_result_time")
        elif result_time_s == 0:
            add_issue(
                issues, severity="error", code="impossible_result_time",
                message="A non-empty result elapsed time cannot be zero",
                source_file=source_file, record_index=index, record=record,
            )
            reason_codes.append("impossible_result_time")
        points_source = record.get("Points")
        points = number(points_source)
        if source_text(points_source) is not None and points is None:
            add_issue(
                issues, severity="error", code="invalid_points",
                message=f"Points {points_source!r} is not numeric",
                source_file=source_file, record_index=index, record=record,
            )
            reason_codes.append("invalid_points")
        row: dict[str, Any] = {
            "event_id": event_id,
            "session_id": f"{event_id}:{session_code}" if event_id else None,
            "driver_id": driver_id,
            "constructor_id": source_text(record.get("TeamId")),
            "position": position_int,
            "classified_position": source_text(record.get("ClassifiedPosition")),
            "grid_position": grid_int,
            "points": points,
            "status_source": status,
            "status_group": status_group(status),
            "time_s": result_time_s,
            "laps_completed": _positive_integer(
                record.get("Laps"), "invalid_result_laps", source_file, index, record, issues,
                reason_codes,
            ),
        }
        if table == "qualifying_results":
            for segment in ("Q1", "Q2", "Q3"):
                source_value = record.get(segment)
                row[f"{segment.lower()}_source"] = source_text(source_value)
                row[f"{segment.lower()}_s"] = time_seconds(source_value)
                if source_text(source_value) is not None and row[f"{segment.lower()}_s"] is None:
                    add_issue(
                        issues, severity="error", code="invalid_qualifying_time",
                        message=f"{segment} value {source_value!r} is not a valid non-negative time",
                        source_file=source_file, record_index=index, record=record,
                    )
                    reason_codes.append("invalid_qualifying_time")
                elif row[f"{segment.lower()}_s"] == 0:
                    add_issue(
                        issues, severity="error", code="impossible_qualifying_time",
                        message=f"{segment} cannot have zero elapsed seconds",
                        source_file=source_file, record_index=index, record=record,
                    )
                    reason_codes.append("impossible_qualifying_time")
        if reason_codes:
            rejects.append(
                _reject(table, source_file, index, record, reason_codes)
            )
        else:
            rows.append(row)
    return rows, rejects


def _positive_integer(
    value: Any,
    code: str,
    source_file: str,
    index: int,
    record: dict[str, Any],
    issues: list[QualityIssue],
    reasons: list[str],
) -> int | None:
    parsed = number(value)
    if parsed is None:
        if source_text(value) is not None:
            add_issue(
                issues, severity="error", code=code,
                message=f"Value {value!r} is not numeric",
                source_file=source_file, record_index=index, record=record,
            )
            reasons.append(code)
        return None
    if parsed <= 0 or not parsed.is_integer():
        add_issue(
            issues, severity="error", code=code,
            message=f"Value {value!r} must be a positive integer when supplied",
            source_file=source_file, record_index=index, record=record,
        )
        reasons.append(code)
        return None
    return int(parsed)


def _reject(
    table: str,
    source_file: str,
    index: int,
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
