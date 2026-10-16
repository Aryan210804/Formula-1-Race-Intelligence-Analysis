"""Event and circuit normalization from FastF1 schedules."""

from typing import Any

from f1_intelligence.transformations.common import (
    QualityIssue, add_issue, slug, source_text,
)


def normalize_events(
    records: list[dict[str, Any]], season: int, source_file: str, issues: list[QualityIssue]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return event and circuit dimension records from a schedule."""
    events: list[dict[str, Any]] = []
    circuits: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for index, record in enumerate(records):
        round_number = record.get("RoundNumber")
        try:
            round_number = int(round_number)
        except (TypeError, ValueError):
            add_issue(
                issues, severity="error", code="invalid_event_round",
                message="Schedule RoundNumber is missing or not an integer",
                source_file=source_file, record_index=index, record=record,
            )
            continue
        if round_number <= 0:
            add_issue(
                issues, severity="info", code="non_championship_schedule_row",
                message="Schedule row is not a numbered championship event",
                source_file=source_file, record_index=index, record=record,
            )
            continue
        event_name = source_text(record.get("EventName"))
        if event_name is None:
            add_issue(
                issues, severity="error", code="missing_event_name",
                message="Schedule event has no EventName",
                source_file=source_file, record_index=index, record=record,
            )
            continue
        event_id = f"{season}:{round_number}"
        if event_id in seen:
            add_issue(
                issues, severity="error", code="duplicate_event_key",
                message=f"Duplicate event key {event_id}",
                source_file=source_file, record_index=index, record=record,
            )
            continue
        seen.add(event_id)
        country = source_text(record.get("Country"))
        location = source_text(record.get("Location"))
        circuit_key = slug(f"{country or ''}-{location or ''}") if location else None
        if circuit_key:
            circuit_id = f"fastf1:{circuit_key}"
            circuits.setdefault(
                circuit_id,
                {
                    "circuit_id": circuit_id,
                    "country": country,
                    "location": location,
                },
            )
        else:
            circuit_id = None
            add_issue(
                issues, severity="warning", code="missing_circuit_location",
                message="No circuit location supplied; circuit_id remains null",
                source_file=source_file, record_index=index, record=record,
            )
        events.append(
            {
                "event_id": event_id,
                "season": season,
                "round_number": round_number,
                "event_name": event_name,
                "event_name_key": slug(event_name),
                "official_event_name": source_text(record.get("OfficialEventName")),
                "country": country,
                "location": location,
                "circuit_id": circuit_id,
                "event_date": source_text(record.get("EventDate")),
                "event_format": source_text(record.get("EventFormat")),
            }
        )
    return events, list(circuits.values())


def normalize_scheduled_sessions(
    records: list[dict[str, Any]], season: int, source_file: str, issues: list[QualityIssue]
) -> list[dict[str, Any]]:
    """Expand schedule session labels and dates into session dimension rows."""
    sessions: list[dict[str, Any]] = []
    code_map = {
        "practice 1": "FP1", "practice 2": "FP2", "practice 3": "FP3",
        "qualifying": "Q", "sprint qualifying": "SQ", "sprint shootout": "SS",
        "sprint": "S", "race": "R",
    }
    for index, event in enumerate(records):
        try:
            round_number = int(event.get("RoundNumber"))
        except (TypeError, ValueError):
            continue
        if round_number <= 0:
            continue
        event_id = f"{season}:{round_number}"
        for slot in range(1, 6):
            name = source_text(event.get(f"Session{slot}"))
            if name is None:
                continue
            code = code_map.get(name.casefold())
            if code is None:
                add_issue(
                    issues, severity="warning", code="unknown_scheduled_session",
                    message=f"Unrecognized scheduled session name {name!r}",
                    source_file=source_file, record_index=index, record=event,
                )
                continue
            sessions.append(
                {
                    "session_id": f"{event_id}:{code}",
                    "event_id": event_id,
                    "session_code": code,
                    "session_name": name,
                    "scheduled_start": source_text(
                        event.get(f"Session{slot}DateUtc")
                        or event.get(f"Session{slot}Date")
                    ),
                }
            )
    return sessions
