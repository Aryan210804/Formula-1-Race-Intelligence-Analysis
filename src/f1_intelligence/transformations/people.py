"""Driver and constructor dimension normalization."""

from typing import Any

from f1_intelligence.transformations.common import QualityIssue, add_issue, source_text


def normalize_people(
    records: list[dict[str, Any]],
    season: int,
    source_file: str,
    issues: list[QualityIssue],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract unique source-identified drivers and constructors."""
    drivers: dict[str, dict[str, Any]] = {}
    constructors: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        driver_id = source_text(record.get("DriverId"))
        if driver_id is None:
            driver_number = source_text(record.get("DriverNumber"))
            if driver_number is None:
                add_issue(
                    issues, severity="error", code="missing_driver_identifier",
                    message="Driver has neither DriverId nor DriverNumber",
                    source_file=source_file, record_index=index, record=record,
                )
                continue
            driver_id = f"fastf1:{season}:number:{driver_number}"
            add_issue(
                issues, severity="warning", code="driver_id_fallback",
                message="Using season-scoped DriverNumber because DriverId is absent",
                source_file=source_file, record_index=index, record=record,
            )
        drivers.setdefault(
            driver_id,
            {
                "driver_id": driver_id,
                "driver_number": source_text(record.get("DriverNumber")),
                "abbreviation": (
                    source_text(record.get("Abbreviation")).upper()
                    if source_text(record.get("Abbreviation"))
                    else None
                ),
                "first_name": source_text(record.get("FirstName")),
                "last_name": source_text(record.get("LastName")),
                "full_name": source_text(record.get("FullName")),
                "country_code": source_text(record.get("CountryCode")),
            },
        )
        constructor_id = source_text(record.get("TeamId"))
        if constructor_id:
            constructors.setdefault(
                constructor_id,
                {
                    "constructor_id": constructor_id,
                    "constructor_name": source_text(record.get("TeamName")),
                    "team_color": source_text(record.get("TeamColor")),
                },
            )
    return list(drivers.values()), list(constructors.values())
