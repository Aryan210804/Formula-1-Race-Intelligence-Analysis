"""Atomic JSON persistence for raw and enriched ingestion datasets."""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def dataset_directory(
    root: Path, season: int, event_round: int | None, event_name: str, session: str
) -> Path:
    """Return a stable path for a season, event, and session."""
    if event_round is None:
        return root / f"season={season}"
    slug = re.sub(r"[^a-z0-9]+", "-", event_name.casefold()).strip("-") or "event"
    return (
        root
        / f"season={season}"
        / f"round={event_round:02d}-{slug}"
        / f"session={session}"
    )


def json_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a source DataFrame to JSON-compatible records without filling nulls."""
    return json.loads(
        frame.to_json(
            orient="records",
            date_format="iso",
            date_unit="ns",
            double_precision=15,
        )
    )


def enrich_records(
    records: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    """Add stable event/session metadata and a source-backed driver key."""
    result: list[dict[str, Any]] = []
    for record in records:
        enriched = dict(record)
        enriched.update(
            {
                "season": metadata["season"],
                "event_id": metadata["event_id"],
                "event_name": metadata["event_name"],
                "event_round": metadata["event_round"],
                "session": metadata["session"],
                "retrieved_at_utc": metadata["retrieved_at_utc"],
                "source": metadata["source"],
            }
        )
        driver_id = _first_value(
            record,
            ("DriverId", "driver_id", "DriverNumber", "driver_number", "Driver"),
        )
        if driver_id is not None:
            enriched["driver_key"] = f"fastf1:{metadata['season']}:{driver_id}"
        result.append(enriched)
    return result


def write_dataset(
    *,
    raw_root: Path,
    processed_root: Path,
    season: int,
    event_round: int | None,
    event_name: str,
    session: str,
    dataset: str,
    frame: pd.DataFrame,
    source: str = "fastf1",
    extra_metadata: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    """Write raw and enriched JSON snapshots using atomic file replacement."""
    retrieved_at = datetime.now(timezone.utc).isoformat()
    event_id = f"{season}:{event_round}" if event_round is not None else None
    metadata: dict[str, Any] = {
        "dataset": dataset,
        "season": season,
        "event_id": event_id,
        "event_name": event_name,
        "event_round": event_round,
        "session": session or None,
        "retrieved_at_utc": retrieved_at,
        "source": source,
        "record_count": len(frame.index),
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    source_records = json_records(frame)
    raw_payload = {"metadata": metadata, "records": source_records}
    processed_payload = {
        "metadata": metadata,
        "records": enrich_records(source_records, metadata),
    }
    raw_path = dataset_directory(
        raw_root, season, event_round, event_name, session
    ) / f"{dataset}.json"
    processed_path = dataset_directory(
        processed_root, season, event_round, event_name, session
    ) / f"{dataset}.json"
    _atomic_write_json(raw_path, raw_payload)
    _atomic_write_json(processed_path, processed_payload)
    return raw_path, processed_path


def _first_value(record: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    for key in candidates:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary_path.replace(path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise
