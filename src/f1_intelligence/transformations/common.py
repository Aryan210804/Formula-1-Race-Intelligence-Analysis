"""Shared value normalization and issue reporting."""

import re
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class QualityIssue:
    """A specific validation finding tied to a source record."""

    severity: str
    code: str
    message: str
    source_file: str
    record_index: int | None = None
    record: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return asdict(self)


def slug(value: Any) -> str | None:
    """Normalize a source label to a deterministic lowercase key component."""
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-")
    return text or None


def source_text(value: Any) -> str | None:
    """Preserve non-empty source text while treating blank strings as missing."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def number(value: Any) -> float | None:
    """Convert finite source values to numbers without converting null to zero."""
    if value is None or pd.isna(value) or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def time_seconds(value: Any) -> float | None:
    """Parse FastF1 ISO-like timedeltas or numeric seconds into seconds."""
    text = source_text(value)
    if text is None:
        return None
    try:
        if isinstance(value, (int, float)):
            result = float(value)
        else:
            iso_match = re.fullmatch(
                r"P(?:(\d+(?:\.\d+)?)D)?(?:T"
                r"(?:(\d+(?:\.\d+)?)H)?"
                r"(?:(\d+(?:\.\d+)?)M)?"
                r"(?:(\d+(?:\.\d+)?)S)?)?",
                text,
            )
            if iso_match:
                days, hours, minutes, seconds = (
                    float(part or 0) for part in iso_match.groups()
                )
                result = days * 86400 + hours * 3600 + minutes * 60 + seconds
            else:
                clock_match = re.fullmatch(
                    r"(?:(\d+)\s+days?\s+)?(\d+):(\d{2}):(\d{2})(?:\.(\d+))?",
                    text,
                )
                if not clock_match:
                    return None
                days, hours, minutes, seconds, fraction = clock_match.groups()
                result = (
                    int(days or 0) * 86400
                    + int(hours) * 3600
                    + int(minutes) * 60
                    + int(seconds)
                )
                if fraction:
                    result += float(f"0.{fraction}")
    except (TypeError, ValueError, OverflowError):
        return None
    if not isfinite(result) or result < 0:
        return None
    return float(result)


def status_group(value: Any) -> str | None:
    """Classify only explicitly source-marked finish states."""
    status = source_text(value)
    if status is None:
        return None
    normalized = status.casefold().strip()
    if normalized in {"dnf", "retired", "did not finish"}:
        return "DNF"
    if normalized in {"dns", "did not start", "withdrawn"}:
        return "DNS"
    if normalized in {"dsq", "disqualified", "disqualification"}:
        return "DSQ"
    if normalized in {"finished", "classified"}:
        return "CLASSIFIED"
    return "OTHER_SOURCE_STATUS"


def add_issue(
    issues: list[QualityIssue],
    *,
    severity: str,
    code: str,
    message: str,
    source_file: str,
    record_index: int | None = None,
    record: dict[str, Any] | None = None,
) -> None:
    """Append a normalized issue for reports and rejected-record storage."""
    issues.append(
        QualityIssue(
            severity=severity,
            code=code,
            message=message,
            source_file=source_file,
            record_index=record_index,
            record=record,
        )
    )
