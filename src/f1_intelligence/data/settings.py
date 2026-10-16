"""Configuration for FastF1 ingestion."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


ALLOWED_SCOPES = frozenset(
    {"results", "laps", "pit_stops", "weather", "telemetry"}
)
ALLOWED_SESSIONS = frozenset({"FP1", "FP2", "FP3", "Q", "SQ", "S", "SS", "R"})


class ConfigurationError(ValueError):
    """Raised when the ingestion configuration is invalid."""


@dataclass(frozen=True)
class IngestionSettings:
    """Validated ingestion settings with paths rooted at the project directory."""

    project_root: Path
    raw_data: Path
    kaggle_raw_data: Path
    fastf1_raw_data: Path
    interim_data: Path
    processed_data: Path
    exports: Path
    fastf1_cache: Path
    sqlite_database: Path
    quality_reports: Path
    logging_level: str
    start_year: int
    end_year: int
    sessions: tuple[str, ...]
    download_scope: tuple[str, ...]
    historical_max_seasons: int
    max_attempts: int
    backoff_base_seconds: float
    backoff_max_seconds: float
    minimum_request_interval_seconds: float

    @classmethod
    def from_yaml(cls, config_path: Path) -> "IngestionSettings":
        """Load and validate settings from a YAML configuration file."""
        config_path = config_path.resolve()
        try:
            with config_path.open(encoding="utf-8") as config_file:
                config: dict[str, Any] = yaml.safe_load(config_file) or {}
        except OSError as exc:
            raise ConfigurationError(
                f"Unable to read settings file {config_path}: {exc}"
            ) from exc
        except yaml.YAMLError as exc:
            raise ConfigurationError(
                f"Invalid YAML in settings file {config_path}: {exc}"
            ) from exc
        if not isinstance(config, dict):
            raise ConfigurationError("Settings YAML must contain a mapping")

        root = (
            config_path.parent.parent
            if config_path.parent.name.casefold() == "config"
            else config_path.parent
        )
        paths = config.get("paths", {})
        ingestion = config.get("ingestion", {})
        logging_config = config.get("logging", {})
        if not isinstance(paths, dict) or not isinstance(ingestion, dict):
            raise ConfigurationError("'paths' and 'ingestion' must be YAML mappings")
        if not isinstance(logging_config, dict):
            raise ConfigurationError("'logging' must be a YAML mapping")
        try:
            start_year = int(ingestion.get("start_year", 2018))
            end_year = int(ingestion.get("end_year") or datetime.now().year)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                "ingestion.start_year and end_year must be integer years"
            ) from exc
        configured_sessions = ingestion.get("sessions", ("Q", "R"))
        configured_scope = ingestion.get(
            "download_scope", ("results", "laps", "pit_stops", "weather")
        )
        if isinstance(configured_sessions, str) or not isinstance(
            configured_sessions, (list, tuple)
        ):
            raise ConfigurationError("ingestion.sessions must be a list of session codes")
        if isinstance(configured_scope, str) or not isinstance(
            configured_scope, (list, tuple)
        ):
            raise ConfigurationError("ingestion.download_scope must be a list")
        sessions = tuple(
            str(session).strip().upper()
            for session in configured_sessions
        )
        scope = tuple(
            str(dataset).strip().lower()
            for dataset in configured_scope
        )
        try:
            settings = cls(
                project_root=root,
                raw_data=_configured_path(root, paths, "raw_data", "data/raw"),
                kaggle_raw_data=_configured_path(
                    root, paths, "kaggle_raw_data", "data/raw/kaggle"
                ),
                fastf1_raw_data=_configured_path(
                    root, paths, "fastf1_raw_data", "data/raw/fastf1"
                ),
                interim_data=_configured_path(
                    root, paths, "interim_data", "data/interim"
                ),
                processed_data=_configured_path(
                    root, paths, "processed_data", "data/processed"
                ),
                exports=_configured_path(root, paths, "exports", "data/exports"),
                fastf1_cache=_configured_path(
                    root, paths, "fastf1_cache", ".cache/fastf1"
                ),
                sqlite_database=_configured_path(
                    root,
                    paths,
                    "sqlite_database",
                    "data/processed/f1_intelligence.sqlite3",
                ),
                quality_reports=_configured_path(
                    root, paths, "quality_reports", "data/processed/quality"
                ),
                logging_level=str(logging_config.get("level", "INFO")).upper(),
                start_year=start_year,
                end_year=end_year,
                sessions=sessions,
                download_scope=scope,
                historical_max_seasons=int(
                    ingestion.get("historical_max_seasons", 3)
                ),
                max_attempts=int(ingestion.get("max_attempts", 3)),
                backoff_base_seconds=float(
                    ingestion.get("backoff_base_seconds", 1.0)
                ),
                backoff_max_seconds=float(
                    ingestion.get("backoff_max_seconds", 8.0)
                ),
                minimum_request_interval_seconds=float(
                    ingestion.get("minimum_request_interval_seconds", 1.0)
                ),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ConfigurationError):
                raise
            raise ConfigurationError(f"Invalid configuration value: {exc}") from exc
        settings.validate()
        return settings

    def validate(self) -> None:
        """Reject invalid values before any source access or data download."""
        if self.start_year < 1950 or self.end_year < self.start_year:
            raise ConfigurationError(
                f"Invalid configured season range: {self.start_year}-{self.end_year}"
            )
        if not self.sessions or any(not session for session in self.sessions):
            raise ConfigurationError("At least one non-empty session code is required")
        unknown_sessions = set(self.sessions) - ALLOWED_SESSIONS
        if unknown_sessions:
            raise ConfigurationError(
                f"Unsupported session code: {', '.join(sorted(unknown_sessions))}"
            )
        unknown_scopes = set(self.download_scope) - ALLOWED_SCOPES
        if unknown_scopes:
            raise ConfigurationError(
                f"Unsupported download scope: {', '.join(sorted(unknown_scopes))}"
            )
        if not self.download_scope:
            raise ConfigurationError("At least one download scope is required")
        if self.historical_max_seasons < 1 or self.max_attempts < 1:
            raise ConfigurationError(
                "historical_max_seasons and max_attempts must be at least 1"
            )
        if (
            self.backoff_base_seconds < 0
            or self.backoff_max_seconds < self.backoff_base_seconds
            or self.minimum_request_interval_seconds < 0
        ):
            raise ConfigurationError(
                "Backoff and request interval settings must be non-negative "
                "and backoff_max_seconds must be >= backoff_base_seconds"
            )
        if self.logging_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError(
                "logging.level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL"
            )

    def validate_season(self, season: int) -> None:
        """Ensure a requested season lies inside the configured ingestion range."""
        if not self.start_year <= season <= self.end_year:
            raise ConfigurationError(
                f"Season {season} is outside configured range "
                f"{self.start_year}-{self.end_year}"
            )


def _configured_path(
    root: Path, paths: dict[str, Any], key: str, default: str
) -> Path:
    """Resolve a configured path relative to the project root unless absolute."""
    configured_path = paths.get(key, default)
    if not isinstance(configured_path, str) or not configured_path.strip():
        raise ConfigurationError(f"paths.{key} must be a non-empty path string")
    path = Path(configured_path)
    return path if path.is_absolute() else (root / path).resolve()
