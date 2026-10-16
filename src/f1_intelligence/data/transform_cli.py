"""CLI for rebuilding normalized tables and quality reports from raw snapshots."""

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Sequence

from f1_intelligence.data.settings import ConfigurationError, IngestionSettings
from f1_intelligence.storage.sqlite import SQLiteStore
from f1_intelligence.transformations.runner import (
    TransformationError,
    build_quality_report,
    render_quality_summary,
    transform_raw_data,
)

LOGGER = logging.getLogger("f1_intelligence.transform")


def build_parser() -> argparse.ArgumentParser:
    """Build the transformation/rebuild command parser."""
    parser = argparse.ArgumentParser(
        prog="f1-transform",
        description="Rebuild analytical SQLite tables from immutable raw FastF1 JSON.",
    )
    parser.add_argument("--config", type=Path, default=Path("config/settings.yaml"))
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Upsert current rows without clearing tables (default rebuilds all raw-derived rows)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 1 when any error-severity quality finding exists",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Transform raw snapshots, rebuild SQLite tables, and write QA reports."""
    args = build_parser().parse_args(argv)
    try:
        settings = IngestionSettings.from_yaml(args.config)
        logging.basicConfig(
            level=getattr(logging, settings.logging_level),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        raw_root = (args.raw_root or settings.fastf1_raw_data).resolve()
        database_path = (args.database or settings.sqlite_database).resolve()
        report_dir = (args.report_dir or settings.quality_reports).resolve()
        report_dir.mkdir(parents=True, exist_ok=True)
        json_report = report_dir / "quality_report.json"
        summary_report = report_dir / "quality_summary.md"
        bundle = transform_raw_data(
            raw_root,
            previous_report=json_report if json_report.is_file() else None,
        )
        report = build_quality_report(bundle)
        storage = SQLiteStore(database_path)
        database_counts = storage.load_bundle(
            bundle.tables,
            bundle.rejected_records,
            [issue.to_dict() for issue in bundle.issues],
            rebuild=not args.incremental,
        )
        report["database_row_counts"] = database_counts
        _atomic_write(
            json_report,
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        )
        _atomic_write(summary_report, render_quality_summary(report))
        print(
            f"Loaded {sum(report['transformed_row_counts'].values())} transformed "
            f"rows into {database_path}"
        )
        print(
            f"Rejected {report['rejected_record_count']} records; "
            f"quality errors={report['error_count']}, warnings={report['warning_count']}"
        )
        print(f"Quality report: {json_report}")
        print(f"Quality summary: {summary_report}")
        return 1 if args.strict and report["error_count"] else 0
    except (ConfigurationError, OSError, TransformationError, RuntimeError, ValueError) as exc:
        LOGGER.error("Transformation failed: %s", exc)
        return 2

def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
