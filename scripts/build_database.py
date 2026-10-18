"""CLI for building the validated historical/strategy SQLite database."""

import argparse
import logging
import sqlite3
from pathlib import Path
from typing import Sequence

from f1_intelligence.database import DatabaseBuildError, build_database
from f1_intelligence.paths import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_RAW_DATA_PATH,
    resolve_project_path,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_DATA_PATH)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--no-weather", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raw_root = resolve_project_path(args.raw_root)
    database_path = resolve_project_path(args.database)
    try:
        counts = build_database(raw_root, database_path, include_weather=not args.no_weather)
    except (DatabaseBuildError, OSError, ValueError, sqlite3.Error) as exc:
        logging.error("Database build failed: %s", exc)
        return 2
    for table, count in counts.items():
        print(f"{table}: {count:,} rows")
    print(f"Built validated database: {database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
