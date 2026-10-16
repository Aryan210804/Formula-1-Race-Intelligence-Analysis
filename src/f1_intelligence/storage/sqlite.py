"""Transactional SQLite storage for normalized Formula 1 analytical tables."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from f1_intelligence.transformations.runner import TABLES
from f1_intelligence.transformations.common import slug


SCHEMA = """
CREATE TABLE IF NOT EXISTS circuits (
    circuit_id TEXT PRIMARY KEY,
    country TEXT,
    location TEXT
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    season INTEGER NOT NULL CHECK (season >= 1950),
    round_number INTEGER NOT NULL CHECK (round_number > 0),
    event_name TEXT NOT NULL,
    event_name_key TEXT NOT NULL,
    official_event_name TEXT,
    country TEXT,
    location TEXT,
    circuit_id TEXT,
    event_date TEXT,
    event_format TEXT,
    UNIQUE (season, round_number),
    FOREIGN KEY (circuit_id) REFERENCES circuits(circuit_id)
);
CREATE TABLE IF NOT EXISTS drivers (
    driver_id TEXT PRIMARY KEY,
    driver_number TEXT,
    abbreviation TEXT,
    first_name TEXT,
    last_name TEXT,
    full_name TEXT,
    country_code TEXT
);
CREATE TABLE IF NOT EXISTS constructors (
    constructor_id TEXT PRIMARY KEY,
    constructor_name TEXT,
    team_color TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    session_code TEXT NOT NULL,
    session_name TEXT,
    scheduled_start TEXT,
    UNIQUE (event_id, session_code),
    UNIQUE (session_id, event_id),
    FOREIGN KEY (event_id) REFERENCES events(event_id)
);
CREATE TABLE IF NOT EXISTS race_results (
    event_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    driver_id TEXT NOT NULL,
    constructor_id TEXT,
    position INTEGER CHECK (position IS NULL OR position > 0),
    classified_position TEXT,
    grid_position INTEGER CHECK (grid_position IS NULL OR grid_position > 0),
    points REAL,
    status_source TEXT,
    status_group TEXT,
    time_s REAL CHECK (time_s IS NULL OR time_s >= 0),
    laps_completed INTEGER CHECK (laps_completed IS NULL OR laps_completed > 0),
    PRIMARY KEY (event_id, session_id, driver_id),
    FOREIGN KEY (session_id, event_id) REFERENCES sessions(session_id, event_id),
    FOREIGN KEY (driver_id) REFERENCES drivers(driver_id),
    FOREIGN KEY (constructor_id) REFERENCES constructors(constructor_id)
);
CREATE TABLE IF NOT EXISTS qualifying_results (
    event_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    driver_id TEXT NOT NULL,
    constructor_id TEXT,
    position INTEGER CHECK (position IS NULL OR position > 0),
    classified_position TEXT,
    grid_position INTEGER CHECK (grid_position IS NULL OR grid_position > 0),
    points REAL,
    status_source TEXT,
    status_group TEXT,
    time_s REAL CHECK (time_s IS NULL OR time_s >= 0),
    laps_completed INTEGER CHECK (laps_completed IS NULL OR laps_completed > 0),
    q1_source TEXT,
    q1_s REAL CHECK (q1_s IS NULL OR q1_s >= 0),
    q2_source TEXT,
    q2_s REAL CHECK (q2_s IS NULL OR q2_s >= 0),
    q3_source TEXT,
    q3_s REAL CHECK (q3_s IS NULL OR q3_s >= 0),
    PRIMARY KEY (event_id, session_id, driver_id),
    FOREIGN KEY (session_id, event_id) REFERENCES sessions(session_id, event_id),
    FOREIGN KEY (driver_id) REFERENCES drivers(driver_id),
    FOREIGN KEY (constructor_id) REFERENCES constructors(constructor_id)
);
CREATE TABLE IF NOT EXISTS session_results (
    event_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    driver_id TEXT NOT NULL,
    constructor_id TEXT,
    position INTEGER CHECK (position IS NULL OR position > 0),
    classified_position TEXT,
    grid_position INTEGER CHECK (grid_position IS NULL OR grid_position > 0),
    points REAL,
    status_source TEXT,
    status_group TEXT,
    time_s REAL CHECK (time_s IS NULL OR time_s >= 0),
    laps_completed INTEGER CHECK (laps_completed IS NULL OR laps_completed > 0),
    PRIMARY KEY (event_id, session_id, driver_id),
    FOREIGN KEY (session_id, event_id) REFERENCES sessions(session_id, event_id),
    FOREIGN KEY (driver_id) REFERENCES drivers(driver_id),
    FOREIGN KEY (constructor_id) REFERENCES constructors(constructor_id)
);
CREATE TABLE IF NOT EXISTS laps (
    event_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    driver_id TEXT NOT NULL,
    lap_number INTEGER NOT NULL CHECK (lap_number > 0),
    lap_time_source TEXT,
    lap_time_s REAL CHECK (lap_time_s IS NULL OR lap_time_s >= 0),
    lap_start_time_s REAL CHECK (lap_start_time_s IS NULL OR lap_start_time_s >= 0),
    sector1_s REAL CHECK (sector1_s IS NULL OR sector1_s >= 0),
    sector2_s REAL CHECK (sector2_s IS NULL OR sector2_s >= 0),
    sector3_s REAL CHECK (sector3_s IS NULL OR sector3_s >= 0),
    stint INTEGER CHECK (stint IS NULL OR stint > 0),
    compound TEXT,
    tyre_life INTEGER CHECK (tyre_life IS NULL OR tyre_life > 0),
    is_personal_best INTEGER CHECK (is_personal_best IS NULL OR is_personal_best IN (0, 1)),
    PRIMARY KEY (session_id, driver_id, lap_number),
    FOREIGN KEY (session_id, event_id) REFERENCES sessions(session_id, event_id),
    FOREIGN KEY (driver_id) REFERENCES drivers(driver_id)
);
CREATE TABLE IF NOT EXISTS pit_stops (
    event_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    driver_id TEXT NOT NULL,
    lap_number INTEGER NOT NULL CHECK (lap_number > 0),
    pit_in_time_s REAL CHECK (pit_in_time_s IS NULL OR pit_in_time_s >= 0),
    pit_out_time_s REAL CHECK (pit_out_time_s IS NULL OR pit_out_time_s >= 0),
    PRIMARY KEY (session_id, driver_id, lap_number),
    FOREIGN KEY (session_id, event_id) REFERENCES sessions(session_id, event_id),
    FOREIGN KEY (driver_id) REFERENCES drivers(driver_id)
);
CREATE TABLE IF NOT EXISTS weather (
    event_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    sample_number INTEGER NOT NULL CHECK (sample_number >= 0),
    time_source TEXT,
    time_s REAL CHECK (time_s IS NULL OR time_s >= 0),
    air_temp REAL,
    track_temp REAL,
    humidity REAL,
    pressure REAL,
    rainfall_source TEXT,
    wind_direction REAL,
    wind_speed REAL,
    PRIMARY KEY (session_id, sample_number),
    FOREIGN KEY (session_id, event_id) REFERENCES sessions(session_id, event_id)
);
CREATE TABLE IF NOT EXISTS telemetry (
    event_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    driver_id TEXT NOT NULL,
    sample_number INTEGER NOT NULL CHECK (sample_number >= 0),
    time_source TEXT,
    time_s REAL CHECK (time_s IS NULL OR time_s >= 0),
    speed REAL,
    throttle REAL,
    brake INTEGER CHECK (brake IS NULL OR brake IN (0, 1)),
    gear INTEGER CHECK (gear IS NULL OR gear >= 0),
    rpm REAL,
    drs REAL,
    PRIMARY KEY (session_id, driver_id, sample_number),
    FOREIGN KEY (session_id, event_id) REFERENCES sessions(session_id, event_id),
    FOREIGN KEY (driver_id) REFERENCES drivers(driver_id)
);
CREATE TABLE IF NOT EXISTS rejected_records (
    reject_id TEXT PRIMARY KEY,
    target_table TEXT NOT NULL,
    source_file TEXT NOT NULL,
    record_index INTEGER,
    reason_codes_json TEXT NOT NULL,
    source_record_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_issues (
    issue_id TEXT PRIMARY KEY,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    source_file TEXT NOT NULL,
    record_index INTEGER,
    record_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_season ON events(season, round_number);
CREATE INDEX IF NOT EXISTS idx_sessions_event ON sessions(event_id, session_code);
CREATE INDEX IF NOT EXISTS idx_race_results_driver ON race_results(driver_id);
CREATE INDEX IF NOT EXISTS idx_race_results_event_position ON race_results(event_id, position);
CREATE INDEX IF NOT EXISTS idx_qualifying_driver ON qualifying_results(driver_id);
CREATE INDEX IF NOT EXISTS idx_laps_event_driver ON laps(event_id, driver_id, lap_number);
CREATE INDEX IF NOT EXISTS idx_pit_stops_event_driver ON pit_stops(event_id, driver_id);
CREATE INDEX IF NOT EXISTS idx_quality_issues_severity ON quality_issues(severity, code);
"""

TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "circuits": ("circuit_id", "country", "location"),
    "events": (
        "event_id", "season", "round_number", "event_name",
        "event_name_key", "official_event_name", "country", "location", "circuit_id",
        "event_date", "event_format",
    ),
    "drivers": (
        "driver_id", "driver_number", "abbreviation", "first_name", "last_name",
        "full_name", "country_code",
    ),
    "constructors": ("constructor_id", "constructor_name", "team_color"),
    "sessions": (
        "session_id", "event_id", "session_code", "session_name", "scheduled_start",
    ),
    "race_results": (
        "event_id", "session_id", "driver_id", "constructor_id", "position",
        "classified_position", "grid_position", "points", "status_source",
        "status_group", "time_s", "laps_completed",
    ),
    "qualifying_results": (
        "event_id", "session_id", "driver_id", "constructor_id", "position",
        "classified_position", "grid_position", "points", "status_source",
        "status_group", "time_s", "laps_completed", "q1_source", "q1_s",
        "q2_source", "q2_s", "q3_source", "q3_s",
    ),
    "session_results": (
        "event_id", "session_id", "driver_id", "constructor_id", "position",
        "classified_position", "grid_position", "points", "status_source",
        "status_group", "time_s", "laps_completed",
    ),
    "laps": (
        "event_id", "session_id", "driver_id", "lap_number", "lap_time_source",
        "lap_time_s", "lap_start_time_s", "sector1_s", "sector2_s", "sector3_s",
        "stint", "compound", "tyre_life", "is_personal_best",
    ),
    "pit_stops": (
        "event_id", "session_id", "driver_id", "lap_number", "pit_in_time_s",
        "pit_out_time_s",
    ),
    "weather": (
        "event_id", "session_id", "sample_number", "time_source", "time_s",
        "air_temp", "track_temp", "humidity", "pressure", "rainfall_source",
        "wind_direction", "wind_speed",
    ),
    "telemetry": (
        "event_id", "session_id", "driver_id", "sample_number", "time_source",
        "time_s", "speed", "throttle", "brake", "gear", "rpm", "drs",
    ),
}

DELETE_ORDER = (
    "quality_issues", "rejected_records", "telemetry", "weather", "pit_stops",
    "laps", "session_results", "qualifying_results", "race_results", "sessions",
    "drivers", "constructors", "events", "circuits",
)


class SQLiteStore:
    """SQLite implementation of the reusable analytical storage interface."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def load_bundle(
        self,
        tables: dict[str, list[dict[str, Any]]],
        rejected_records: list[dict[str, Any]],
        quality_issues: list[dict[str, Any]],
        *,
        rebuild: bool = True,
    ) -> dict[str, int]:
        """Atomically replace (or idempotently upsert) transformed table rows."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        counts: dict[str, int] = {}
        with closing(sqlite3.connect(self.database_path, timeout=30)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(SCHEMA)
            try:
                with connection:
                    self._migrate(connection)
                    if rebuild:
                        for table in DELETE_ORDER:
                            connection.execute(f"DELETE FROM {table}")
                    for table in TABLES:
                        rows = tables.get(table, [])
                        self._write_table(connection, table, rows)
                        counts[table] = len(rows)
                    self._write_rejected(connection, rejected_records)
                    self._write_issues(connection, quality_issues)
                    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
                    if violations:
                        raise sqlite3.IntegrityError(
                            f"Foreign-key validation failed: {violations[:5]}"
                        )
            except sqlite3.Error as exc:
                raise RuntimeError(
                    f"SQLite load failed for {self.database_path}: {exc}"
                ) from exc
        counts["rejected_records"] = len(rejected_records)
        counts["quality_issues"] = len(quality_issues)
        return counts

    def row_counts(self) -> dict[str, int]:
        """Return persisted row counts for analytical and QA tables."""
        counts: dict[str, int] = {}
        if not self.database_path.is_file():
            return counts
        with closing(sqlite3.connect(self.database_path)) as connection:
            for table in (*TABLES, "rejected_records", "quality_issues"):
                counts[table] = connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
        return counts

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Add backward-compatible analytical columns to an existing database."""
        event_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(events)")
        }
        if "event_name_key" not in event_columns:
            connection.execute(
                "ALTER TABLE events ADD COLUMN event_name_key TEXT NOT NULL DEFAULT ''"
            )
            existing_events = connection.execute(
                "SELECT event_id, event_name FROM events"
            ).fetchall()
            connection.executemany(
                "UPDATE events SET event_name_key = ? WHERE event_id = ?",
                [(slug(name) or "", event_id) for event_id, name in existing_events],
            )

    @staticmethod
    def _write_table(
        connection: sqlite3.Connection,
        table: str,
        rows: list[dict[str, Any]],
    ) -> None:
        columns = TABLE_COLUMNS[table]
        if not rows:
            return
        names = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        conflict_columns = {
            "circuits": ("circuit_id",),
            "events": ("event_id",),
            "drivers": ("driver_id",),
            "constructors": ("constructor_id",),
            "sessions": ("session_id",),
            "race_results": ("event_id", "session_id", "driver_id"),
            "qualifying_results": ("event_id", "session_id", "driver_id"),
            "session_results": ("event_id", "session_id", "driver_id"),
            "laps": ("session_id", "driver_id", "lap_number"),
            "pit_stops": ("session_id", "driver_id", "lap_number"),
            "weather": ("session_id", "sample_number"),
            "telemetry": ("session_id", "driver_id", "sample_number"),
        }[table]
        updates = [column for column in columns if column not in conflict_columns]
        conflict = ", ".join(conflict_columns)
        if updates:
            assignments = ", ".join(f"{column}=excluded.{column}" for column in updates)
            suffix = f"DO UPDATE SET {assignments}"
        else:
            suffix = "DO NOTHING"
        statement = (
            f"INSERT INTO {table} ({names}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) {suffix}"
        )
        connection.executemany(
            statement,
            [tuple(_sqlite_value(row.get(column)) for column in columns) for row in rows],
        )

    @staticmethod
    def _write_rejected(
        connection: sqlite3.Connection, records: list[dict[str, Any]]
    ) -> None:
        rows = []
        for record in records:
            normalized = _jsonable(record)
            reject_id = _stable_id(normalized)
            rows.append(
                (
                    reject_id,
                    normalized["target_table"],
                    normalized["source_file"],
                    normalized.get("record_index"),
                    json.dumps(normalized["reason_codes"], sort_keys=True),
                    json.dumps(normalized["source_record"], sort_keys=True),
                )
            )
        connection.executemany(
            """
            INSERT INTO rejected_records
                (reject_id, target_table, source_file, record_index,
                 reason_codes_json, source_record_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (reject_id) DO UPDATE SET
                reason_codes_json=excluded.reason_codes_json,
                source_record_json=excluded.source_record_json
            """,
            rows,
        )

    @staticmethod
    def _write_issues(
        connection: sqlite3.Connection, issues: list[dict[str, Any]]
    ) -> None:
        rows = []
        for issue in issues:
            normalized = _jsonable(issue)
            rows.append(
                (
                    _stable_id(normalized),
                    normalized["severity"],
                    normalized["code"],
                    normalized["message"],
                    normalized["source_file"],
                    normalized.get("record_index"),
                    json.dumps(normalized.get("record"), sort_keys=True)
                    if normalized.get("record") is not None
                    else None,
                )
            )
        connection.executemany(
            """
            INSERT INTO quality_issues
                (issue_id, severity, code, message, source_file, record_index, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (issue_id) DO UPDATE SET
                severity=excluded.severity, message=excluded.message
            """,
            rows,
        )


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, default=str, allow_nan=False))


def _stable_id(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, default=str)
    return value
