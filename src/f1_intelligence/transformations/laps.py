"""Lap timing, pit-stop observation, weather and telemetry cleaning."""

from typing import Any

from f1_intelligence.transformations.common import (
    QualityIssue, add_issue, number, source_text, time_seconds,
)


def normalize_laps(
    records: list[dict[str, Any]],
    event_id: str | None,
    session_code: str,
    source_file: str,
    issues: list[QualityIssue],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Clean lap rows; each accepted row represents one driver's source lap."""
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for index, record in enumerate(records):
        driver_id = source_text(record.get("DriverId")) or source_text(record.get("Driver"))
        lap_number = number(record.get("LapNumber"))
        reasons: list[str] = []
        if event_id is None or driver_id is None:
            reasons.append("missing_event_or_driver_identifier")
        if lap_number is None or lap_number <= 0 or not lap_number.is_integer():
            add_issue(
                issues, severity="error", code="invalid_lap_number",
                message=f"LapNumber {record.get('LapNumber')!r} must be a positive integer",
                source_file=source_file, record_index=index, record=record,
            )
            reasons.append("invalid_lap_number")
            lap_int = None
        else:
            lap_int = int(lap_number)
        if source_text(record.get("LapNumber")) is not None and number(
            record.get("LapNumber")
        ) is None:
            add_issue(
                issues, severity="error", code="invalid_lap_number",
                message=f"LapNumber {record.get('LapNumber')!r} is not numeric",
                source_file=source_file, record_index=index, record=record,
            )
            reasons.append("invalid_lap_number")
        lap_time_source = record.get("LapTime")
        lap_time_s = time_seconds(lap_time_source)
        if source_text(lap_time_source) is not None and lap_time_s is None:
            add_issue(
                issues, severity="error", code="invalid_lap_time",
                message=f"LapTime {lap_time_source!r} is not a valid non-negative time",
                source_file=source_file, record_index=index, record=record,
            )
            reasons.append("invalid_lap_time")
        if lap_time_s == 0:
            add_issue(
                issues, severity="error", code="impossible_lap_time",
                message="A completed lap cannot have zero elapsed seconds",
                source_file=source_file, record_index=index, record=record,
            )
            reasons.append("impossible_lap_time")
        lap_start_source = record.get("LapStartTime")
        lap_start_time_s = time_seconds(lap_start_source)
        if source_text(lap_start_source) is not None and lap_start_time_s is None:
            add_issue(
                issues, severity="error", code="invalid_lap_start_time",
                message=f"LapStartTime {lap_start_source!r} is not a valid non-negative time",
                source_file=source_file, record_index=index, record=record,
            )
            reasons.append("invalid_lap_start_time")
        for column in ("Sector1Time", "Sector2Time", "Sector3Time"):
            value = record.get(column)
            parsed = time_seconds(value)
            if source_text(value) is not None and parsed is None:
                add_issue(
                    issues, severity="error", code="invalid_sector_time",
                    message=f"{column} {value!r} is not a valid non-negative time",
                    source_file=source_file, record_index=index, record=record,
                )
                reasons.append("invalid_sector_time")
            elif parsed == 0:
                add_issue(
                    issues, severity="error", code="impossible_sector_time",
                    message=f"{column} cannot be zero for a completed sector",
                    source_file=source_file, record_index=index, record=record,
                )
                reasons.append("impossible_sector_time")
        if driver_id is not None and lap_int is not None:
            key = (event_id or "", driver_id, lap_int)
            if key in seen:
                add_issue(
                    issues, severity="error", code="duplicate_lap_key",
                    message=f"Duplicate session/driver/lap key {key}",
                    source_file=source_file, record_index=index, record=record,
                )
                reasons.append("duplicate_lap_key")
            seen.add(key)
        if reasons:
            rejected.append(_reject("laps", source_file, index, record, reasons))
            continue
        rows.append(
            {
                "event_id": event_id,
                "session_id": f"{event_id}:{session_code}" if event_id else None,
                "driver_id": driver_id,
                "lap_number": lap_int,
                "lap_time_source": source_text(lap_time_source),
                "lap_time_s": lap_time_s,
                "lap_start_time_s": lap_start_time_s,
                "sector1_s": time_seconds(record.get("Sector1Time")),
                "sector2_s": time_seconds(record.get("Sector2Time")),
                "sector3_s": time_seconds(record.get("Sector3Time")),
                "stint": _optional_positive_integer(record.get("Stint")),
                "compound": source_text(record.get("Compound")),
                "tyre_life": _optional_positive_integer(record.get("TyreLife")),
                "is_personal_best": _optional_bool(record.get("IsPersonalBest")),
            }
        )
    return rows, rejected


def normalize_pit_stops(
    records: list[dict[str, Any]],
    event_id: str | None,
    session_code: str,
    source_file: str,
    issues: list[QualityIssue],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Preserve source pit-in/out observations; do not infer a stop duration."""
    rows: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        driver_id = source_text(record.get("DriverId")) or source_text(record.get("Driver"))
        lap_value = number(record.get("LapNumber"))
        lap_number = (
            int(lap_value)
            if lap_value is not None and lap_value.is_integer() and lap_value > 0
            else None
        )
        pit_in = time_seconds(record.get("PitInTime"))
        pit_out = time_seconds(record.get("PitOutTime"))
        if pit_in is None and pit_out is None:
            continue
        reasons: list[str] = []
        if event_id is None or driver_id is None or lap_number is None:
            reasons.append("missing_event_driver_or_lap_identifier")
            add_issue(
                issues, severity="error", code="invalid_pit_observation_key",
                message="Pit observation requires event, driver, and positive lap number",
                source_file=source_file, record_index=index, record=record,
            )
        if any(
            source_text(record.get(column)) is not None and time_seconds(record.get(column)) is None
            for column in ("PitInTime", "PitOutTime")
        ):
            reasons.append("invalid_pit_observation_time")
            add_issue(
                issues, severity="error", code="invalid_pit_observation_time",
                message="PitInTime/PitOutTime must be non-negative source times",
                source_file=source_file, record_index=index, record=record,
            )
        if reasons:
            rejects.append(_reject("pit_stops", source_file, index, record, reasons))
            continue
        rows.append(
            {
                "event_id": event_id,
                "session_id": f"{event_id}:{session_code}",
                "driver_id": driver_id,
                "lap_number": lap_number,
                "pit_in_time_s": pit_in,
                "pit_out_time_s": pit_out,
            }
        )
    return rows, rejects


def normalize_observations(
    records: list[dict[str, Any]],
    *,
    dataset: str,
    event_id: str | None,
    session_code: str,
    source_file: str,
    issues: list[QualityIssue],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize session weather or telemetry as ordered source observations."""
    rows: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    table = "weather" if dataset == "weather" else "telemetry"
    for index, record in enumerate(records):
        time_value = source_text(record.get("Time"))
        timestamp = time_seconds(record.get("Date"))
        if timestamp is None and time_value:
            timestamp = time_seconds(time_value)
        if time_value and timestamp is None:
            add_issue(
                issues, severity="error", code="invalid_observation_time",
                message=f"Observation Time {time_value!r} is not a recognized elapsed time",
                source_file=source_file, record_index=index, record=record,
            )
            rejects.append(
                _reject(table, source_file, index, record, ["invalid_observation_time"])
            )
            continue
        driver_id = source_text(record.get("DriverId")) or source_text(record.get("Driver"))
        if not time_value and timestamp is None:
            add_issue(
                issues, severity="warning", code="missing_observation_time",
                message="Observation has no usable time; source sample index is retained",
                source_file=source_file, record_index=index, record=record,
            )
        if dataset == "weather":
            key_id = str(index)
            row = {
                "event_id": event_id,
                "session_id": f"{event_id}:{session_code}" if event_id else None,
                "sample_number": index,
                "time_source": time_value,
                "time_s": timestamp,
                "air_temp": number(record.get("AirTemp")),
                "track_temp": number(record.get("TrackTemp")),
                "humidity": number(record.get("Humidity")),
                "pressure": number(record.get("Pressure")),
                "rainfall_source": _bool_source(record.get("Rainfall")),
                "wind_direction": number(record.get("WindDirection")),
                "wind_speed": number(record.get("WindSpeed")),
            }
        else:
            key_id = driver_id or ""
            row = {
                "event_id": event_id,
                "session_id": f"{event_id}:{session_code}" if event_id else None,
                "driver_id": driver_id,
                "sample_number": index,
                "time_source": time_value,
                "time_s": timestamp,
                "speed": number(record.get("Speed")),
                "throttle": number(record.get("Throttle")),
                "brake": _optional_bool(record.get("Brake")),
                "gear": _optional_positive_integer(record.get("nGear"), allow_zero=True),
                "rpm": number(record.get("RPM")),
                "drs": number(record.get("DRS")),
            }
        numeric_columns = (
            (
                "AirTemp", "TrackTemp", "Humidity", "Pressure",
                "WindDirection", "WindSpeed",
            )
            if dataset == "weather"
            else ("Speed", "Throttle", "nGear", "RPM", "DRS")
        )
        invalid_numeric_columns = [
            column for column in numeric_columns
            if source_text(record.get(column)) is not None
            and number(record.get(column)) is None
        ]
        if invalid_numeric_columns:
            add_issue(
                issues, severity="error", code=f"invalid_{dataset}_numeric_value",
                message=(
                    "Non-numeric source values in "
                    + ", ".join(invalid_numeric_columns)
                ),
                source_file=source_file, record_index=index, record=record,
            )
            rejects.append(
                _reject(
                    table, source_file, index, record,
                    [f"invalid_{dataset}_numeric_value"],
                )
            )
            continue
        invalid_range_columns = _invalid_ranges(dataset, record)
        if invalid_range_columns:
            add_issue(
                issues, severity="error", code=f"impossible_{dataset}_numeric_value",
                message=(
                    "Source values outside expected physical bounds: "
                    + ", ".join(invalid_range_columns)
                ),
                source_file=source_file, record_index=index, record=record,
            )
            rejects.append(
                _reject(
                    table, source_file, index, record,
                    [f"impossible_{dataset}_numeric_value"],
                )
            )
            continue
        if event_id is None or (dataset == "telemetry" and driver_id is None):
            reason = "missing_event_identifier" if event_id is None else "missing_driver_identifier"
            add_issue(
                issues, severity="error", code=reason,
                message=f"{dataset} observation is missing a required key",
                source_file=source_file, record_index=index, record=record,
            )
            rejects.append(_reject(table, source_file, index, record, [reason]))
            continue
        key = (event_id, key_id, str(index))
        if key in seen:
            add_issue(
                issues, severity="error", code=f"duplicate_{dataset}_key",
                message=f"Duplicate {dataset} sample key {key}",
                source_file=source_file, record_index=index, record=record,
            )
            rejects.append(_reject(table, source_file, index, record, [f"duplicate_{dataset}_key"]))
            continue
        seen.add(key)
        rows.append(row)
    return rows, rejects


def _optional_positive_integer(value: Any, allow_zero: bool = False) -> int | None:
    parsed = number(value)
    if parsed is None or not parsed.is_integer() or parsed < (0 if allow_zero else 1):
        return None
    return int(parsed)


def _optional_bool(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    return None


def _bool_source(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    return source_text(value)


def _invalid_ranges(dataset: str, record: dict[str, Any]) -> list[str]:
    bounds = (
        {
            "AirTemp": (-100, 100),
            "TrackTemp": (-100, 150),
            "Humidity": (0, 100),
            "Pressure": (0, float("inf")),
            "WindDirection": (0, 360),
            "WindSpeed": (0, float("inf")),
        }
        if dataset == "weather"
        else {
            "Speed": (0, float("inf")),
            "Throttle": (0, 100),
            "nGear": (0, float("inf")),
            "RPM": (0, float("inf")),
        }
    )
    return [
        column
        for column, (minimum, maximum) in bounds.items()
        if number(record.get(column)) is not None
        and not minimum <= number(record[column]) <= maximum
    ]


def _reject(
    table: str, source_file: str, index: int, record: dict[str, Any], reasons: list[str]
) -> dict[str, Any]:
    return {
        "target_table": table,
        "source_file": source_file,
        "record_index": index,
        "reason_codes": reasons,
        "source_record": record,
    }
