"""Copy the local dashboard database to a hosted SQLAlchemy database."""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
from pathlib import Path
from typing import Sequence

import pandas as pd
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError

from f1_intelligence.analytics import (
    CORE_TABLES,
    DASHBOARD_TABLES,
    normalize_database_url,
)


def sync_database(source: Path, destination_url: str) -> dict[str, int]:
    """Replace known dashboard tables in the destination in one transaction."""
    if not source.is_file():
        raise FileNotFoundError(f"Source database not found: {source}")
    normalized_url = normalize_database_url(destination_url)
    engine = create_engine(normalized_url, pool_pre_ping=True)
    try:
        with sqlite3.connect(source) as source_connection:
            source_tables = {
                row[0]
                for row in source_connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            absent_core = set(CORE_TABLES) - source_tables
            if absent_core:
                raise ValueError(
                    f"Source database is missing required tables: {sorted(absent_core)}"
                )
            table_names = source_tables & set(DASHBOARD_TABLES)
            tables = {
                name: pd.read_sql_query(f'SELECT * FROM "{name}"', source_connection)
                for name in sorted(table_names)
            }

        with engine.begin() as destination:
            existing_tables = set(inspect(destination).get_table_names())
            unexpected = existing_tables - table_names
            if unexpected:
                raise ValueError(
                    "Destination contains unrelated tables; refusing to replace data: "
                    f"{sorted(unexpected)}"
                )
            counts: dict[str, int] = {}
            for name, frame in tables.items():
                frame.to_sql(name, destination, if_exists="replace", index=False)
                counts[name] = len(frame)
        return counts
    finally:
        engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/processed/f1_intelligence.db"),
        help="Local dashboard SQLite database",
    )
    args = parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("Set DATABASE_URL to the hosted PostgreSQL connection URL.")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        counts = sync_database(args.source, database_url)
    except (OSError, sqlite3.Error, SQLAlchemyError, ValueError) as exc:
        logging.error("Database sync failed: %s", exc)
        return 2
    for table, count in counts.items():
        print(f"{table}: {count:,} rows")
    print("Hosted dashboard database synchronized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
