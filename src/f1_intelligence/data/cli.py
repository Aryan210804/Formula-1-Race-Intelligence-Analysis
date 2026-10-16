"""Command-line interface for schedule discovery and session ingestion."""

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from f1_intelligence.data.fastf1_source import FastF1Source
from f1_intelligence.data.pipeline import (
    SUPPORTED_SESSIONS,
    IngestionReport,
    ingest_season,
    ingest_session,
)
from f1_intelligence.data.persistence import write_dataset
from f1_intelligence.data.retry import RequestController
from f1_intelligence.data.schedule import get_season_schedule, select_event
from f1_intelligence.data.settings import ALLOWED_SCOPES, ConfigurationError, IngestionSettings

LOGGER = logging.getLogger("f1_intelligence.ingestion")


def build_parser() -> argparse.ArgumentParser:
    """Build the ingestion CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="f1-ingest",
        description="Discover and incrementally ingest FastF1 season/session data.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/settings.yaml"),
        help="YAML settings file (default: config/settings.yaml)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-seasons", help="List configured season years")
    list_events = subparsers.add_parser(
        "list-events", help="List event rounds from a FastF1 season schedule"
    )
    list_events.add_argument("--season", type=int, required=True)

    event = subparsers.add_parser("ingest-event", help="Ingest one event session")
    _add_event_arguments(event)
    event.add_argument("--dry-run", action="store_true")

    season = subparsers.add_parser("ingest-season", help="Ingest a full season")
    season.add_argument("--season", type=int, required=True)
    season.add_argument(
        "--session",
        nargs="+",
        choices=sorted(SUPPORTED_SESSIONS),
        help="Session codes (default: configured sessions)",
    )
    _add_scope_argument(season)
    season.add_argument("--dry-run", action="store_true")

    history = subparsers.add_parser(
        "ingest-history", help="Ingest a bounded inclusive season range"
    )
    history.add_argument("--start-year", type=int, required=True)
    history.add_argument("--end-year", type=int, required=True)
    history.add_argument(
        "--session",
        nargs="+",
        choices=sorted(SUPPORTED_SESSIONS),
        help="Session codes (default: configured sessions)",
    )
    _add_scope_argument(history)
    history.add_argument("--dry-run", action="store_true")

    resume = subparsers.add_parser(
        "resume", help="Resume incomplete datasets for one season"
    )
    resume.add_argument("--season", type=int, required=True)
    resume.add_argument(
        "--session",
        nargs="+",
        choices=sorted(SUPPORTED_SESSIONS),
        help="Session codes (default: configured sessions)",
    )
    _add_scope_argument(resume)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a CLI command and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = IngestionSettings.from_yaml(args.config)
    except ConfigurationError as exc:
        LOGGER.error("%s", exc)
        return 2
    logging.basicConfig(
        level=getattr(logging, settings.logging_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "list-seasons":
        print(
            f"Configured seasons ({settings.start_year}-{settings.end_year}): "
            + ", ".join(
                str(year) for year in range(settings.start_year, settings.end_year + 1)
            )
        )
        return 0

    try:
        source = FastF1Source(settings.fastf1_cache)
        controller = RequestController(settings)
        if args.command == "list-events":
            settings.validate_season(args.season)
            schedule = get_season_schedule(source, controller, args.season)
            _print_events(schedule)
            return 0
        if args.command == "ingest-event":
            settings.validate_season(args.season)
            schedule = get_season_schedule(source, controller, args.season)
            event = select_event(schedule, args.event)
            if not args.dry_run:
                write_dataset(
                    raw_root=settings.fastf1_raw_data,
                    processed_root=settings.processed_data / "fastf1",
                    season=args.season,
                    event_round=None,
                    event_name="schedule",
                    session="",
                    dataset="schedule",
                    frame=schedule,
                )
            report = ingest_session(
                season=args.season,
                event=event,
                session_code=args.session,
                scope=tuple(args.scope or settings.download_scope),
                source=source,
                settings=settings,
                controller=controller,
                dry_run=args.dry_run,
            )
            _print_report(report, dry_run=args.dry_run)
            return 1 if report.has_failures else 0
        if args.command in {"ingest-season", "resume"}:
            settings.validate_season(args.season)
            report = ingest_season(
                season=args.season,
                source=source,
                settings=settings,
                controller=controller,
                sessions=tuple(args.session) if args.session else None,
                scope=tuple(args.scope) if args.scope else None,
                resume=args.command == "resume",
                dry_run=getattr(args, "dry_run", False),
            )
            _print_report(report, dry_run=getattr(args, "dry_run", False))
            return 1 if report.has_failures else 0
        if args.command == "ingest-history":
            if args.start_year > args.end_year:
                raise ValueError("start-year must be less than or equal to end-year")
            if args.start_year < settings.start_year or args.end_year > settings.end_year:
                raise ValueError(
                    f"Requested range must be within configured seasons "
                    f"{settings.start_year}-{settings.end_year}"
                )
            season_count = args.end_year - args.start_year + 1
            if season_count > settings.historical_max_seasons:
                raise ValueError(
                    f"Requested {season_count} seasons exceeds configured limit "
                    f"{settings.historical_max_seasons}; increase "
                    "historical_max_seasons in config/settings.yaml explicitly"
                )
            report = IngestionReport()
            for year in range(args.start_year, args.end_year + 1):
                LOGGER.info("Starting configured ingestion for season %d", year)
                try:
                    report.extend(
                        ingest_season(
                            season=year,
                            source=source,
                            settings=settings,
                            controller=controller,
                            sessions=tuple(args.session) if args.session else None,
                            scope=tuple(args.scope) if args.scope else None,
                            dry_run=args.dry_run,
                        )
                    )
                except (OSError, ValueError, TypeError, RuntimeError) as exc:
                    failure = f"{year} season schedule: {exc}"
                    LOGGER.error("%s", failure)
                    report.failed.append(failure)
            _print_report(report, dry_run=args.dry_run)
            return 1 if report.has_failures else 0
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 2
    return 2


def _add_event_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument(
        "--event", required=True, help="Exact event name or schedule round number"
    )
    parser.add_argument("--session", required=True, choices=sorted(SUPPORTED_SESSIONS))
    _add_scope_argument(parser)


def _add_scope_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scope",
        nargs="+",
        choices=sorted(ALLOWED_SCOPES),
        help="Datasets to extract (default: configured download_scope)",
    )


def _print_events(schedule: object) -> None:
    if not hasattr(schedule, "iterrows"):
        raise TypeError("Event schedule is not tabular")
    for _, event in schedule.iterrows():
        round_number = event.get("RoundNumber", "N/A")
        event_name = event.get("EventName", "Unknown event")
        event_date = event.get("EventDate", "unknown date")
        print(f"{round_number}\t{event_date}\t{event_name}")


def _print_report(report: IngestionReport, *, dry_run: bool = False) -> None:
    if dry_run:
        print(
            f"Planned: {len(report.planned)} dataset(s); "
            f"already complete/skipped: {len(report.skipped)}; "
            f"failed: {len(report.failed)}"
        )
        for item in report.planned:
            print(f"PLANNED: {item}")
    else:
        print(
            f"Completed: {len(report.completed)} dataset(s); "
            f"skipped: {len(report.skipped)}; failed: {len(report.failed)}"
        )
    for item in report.failed:
        print(f"FAILED: {item}", file=sys.stderr)
    for item in report.skipped:
        print(f"SKIPPED: {item}")


if __name__ == "__main__":
    raise SystemExit(main())
