"""Inspect local tabular sources and write JSON/text inventory reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

SUPPORTED = {".csv", ".tsv", ".parquet", ".json", ".xlsx", ".xls", ".xlsm"}


def _read(path: Path) -> dict[str, pd.DataFrame]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return {"data": pd.read_csv(path, low_memory=False, na_values=["\\N"])}
    if suffix == ".tsv":
        return {"data": pd.read_csv(path, sep="\t", low_memory=False)}
    if suffix == ".parquet":
        return {"data": pd.read_parquet(path)}
    if suffix == ".json":
        try:
            return {"data": pd.read_json(path)}
        except ValueError:
            value = json.loads(path.read_text(encoding="utf-8"))
            return {"data": pd.json_normalize(value)}
    sheets = pd.read_excel(path, sheet_name=None)
    return {str(name): frame for name, frame in sheets.items()}


def _duplicate_count(frame: pd.DataFrame) -> int:
    try:
        return int(frame.duplicated().sum())
    except TypeError:
        return int(frame.astype("string").duplicated().sum())


def inspect_datasets(raw_root: Path) -> list[dict[str, Any]]:
    """Collect actual file/sheet schemas and quality indicators."""
    inventory = []
    for path in sorted(item for item in raw_root.rglob("*") if item.is_file()):
        if path.suffix.lower() not in SUPPORTED:
            continue
        entry: dict[str, Any] = {
            "file": str(path),
            "source": path.parent.name,
            "format": path.suffix.lower().lstrip("."),
            "size_bytes": path.stat().st_size,
            "sheets": [],
        }
        try:
            for sheet_name, frame in _read(path).items():
                columns = list(frame.columns)
                key_candidates = []
                for column in columns:
                    if column.lower().endswith("id") and frame[column].notna().all():
                        if not frame[column].duplicated().any():
                            key_candidates.append([column])
                for key in (["raceId", "driverId", "lap"], ["raceId", "driverId", "stop"]):
                    if set(key).issubset(columns) and not frame.duplicated(key).any():
                        key_candidates.append(key)
                dates = {}
                for column in columns:
                    if column.lower() in {"date", "year", "dob"} or column.lower().endswith("_date"):
                        if column.lower() == "year":
                            values = pd.to_numeric(frame[column], errors="coerce").dropna()
                            if not values.empty:
                                dates[column] = {
                                    "min": int(values.min()),
                                    "max": int(values.max()),
                                }
                            continue
                        values = pd.to_datetime(frame[column], errors="coerce").dropna()
                        if not values.empty:
                            dates[column] = {
                                "min": str(values.min()),
                                "max": str(values.max()),
                            }
                categorical = {}
                for column in columns:
                    if pd.api.types.is_object_dtype(frame[column]):
                        values = frame[column].map(repr)
                        if values.nunique(dropna=True) <= 30:
                            categorical[column] = values.value_counts(dropna=False).head(30).to_dict()
                entry["sheets"].append(
                    {
                        "name": sheet_name,
                        "rows": len(frame),
                        "columns": len(columns),
                        "column_types": {str(col): str(dtype) for col, dtype in frame.dtypes.items()},
                        "missing": {
                            str(col): {
                                "count": int(frame[col].isna().sum()),
                                "percent": round(float(frame[col].isna().mean() * 100), 2),
                            }
                            for col in columns
                        },
                        "duplicate_rows": _duplicate_count(frame),
                        "candidate_unique_keys": key_candidates,
                        "date_ranges": dates,
                        "categorical_samples": categorical,
                    }
                )
        except (OSError, ValueError, ImportError, json.JSONDecodeError) as exc:
            entry["read_error"] = f"{type(exc).__name__}: {exc}"
        inventory.append(entry)
    return inventory


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports"))
    args = parser.parse_args(argv)
    inventory = inspect_datasets(args.raw_root)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.report_dir / "dataset_inventory.json"
    text_path = args.report_dir / "dataset_inspection.txt"
    json_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["Formula 1 Race Intelligence — source inspection", ""]
    for item in inventory:
        lines.append(f"{item['source']}: {item['file']} ({item['size_bytes']:,} bytes)")
        if "read_error" in item:
            lines.append(f"  Read error: {item['read_error']}")
            continue
        for sheet in item["sheets"]:
            lines.append(
                f"  {sheet['name']}: {sheet['rows']:,} rows x {sheet['columns']} columns; "
                f"{sheet['duplicate_rows']:,} duplicate rows"
            )
            lines.append("  Columns: " + ", ".join(sheet["column_types"]))
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Inspected {len(inventory)} supported files")
    print(f"JSON inventory: {json_path.resolve()}")
    print(f"Text report: {text_path.resolve()}")
    return 1 if any("read_error" in item for item in inventory) else 0


if __name__ == "__main__":
    raise SystemExit(main())
