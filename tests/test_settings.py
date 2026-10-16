"""Configuration and path-resolution tests."""

from pathlib import Path

import pytest

from f1_intelligence.data.settings import ConfigurationError, IngestionSettings


def _write_config(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_repository_configuration_resolves_paths_without_creating_them(
    project_root: Path,
) -> None:
    settings = IngestionSettings.from_yaml(project_root / "config" / "settings.yaml")

    assert settings.project_root == project_root
    assert settings.raw_data == project_root / "data" / "raw"
    assert settings.kaggle_raw_data == project_root / "data" / "raw" / "kaggle"
    assert settings.fastf1_raw_data == project_root / "data" / "raw" / "fastf1"
    assert settings.interim_data == project_root / "data" / "interim"
    assert settings.processed_data == project_root / "data" / "processed"
    assert settings.exports == project_root / "data" / "exports"
    assert settings.sqlite_database == (
        project_root / "data" / "processed" / "f1_intelligence.sqlite3"
    )
    assert settings.quality_reports == project_root / "data" / "processed" / "quality"
    assert settings.logging_level == "INFO"
    assert (
        project_root / "data" / "raw" / "kaggle" / "README.md"
    ).is_file()


def test_relative_paths_are_rooted_at_configured_project(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path / "example-project" / "config" / "settings.yaml",
        """
paths:
  raw_data: source
  interim_data: work/interim
  processed_data: build/clean
  exports: build/tableau
  sqlite_database: build/db/f1.sqlite3
  quality_reports: build/reports
ingestion:
  start_year: 2020
  end_year: 2024
  sessions: [R]
  download_scope: [results]
logging:
  level: DEBUG
""",
    )

    settings = IngestionSettings.from_yaml(config_path)
    root = tmp_path / "example-project"

    assert settings.project_root == root
    assert settings.raw_data == root / "source"
    assert settings.interim_data == root / "work" / "interim"
    assert settings.processed_data == root / "build" / "clean"
    assert settings.exports == root / "build" / "tableau"
    assert settings.sqlite_database == root / "build" / "db" / "f1.sqlite3"
    assert settings.quality_reports == root / "build" / "reports"
    assert settings.logging_level == "DEBUG"


def test_absolute_paths_are_preserved(tmp_path: Path) -> None:
    external = tmp_path / "external" / "raw"
    config_path = _write_config(
        tmp_path / "project" / "config" / "settings.yaml",
        f"""
paths:
  raw_data: "{external.as_posix()}"
ingestion:
  sessions: [Q]
  download_scope: [results]
""",
    )

    settings = IngestionSettings.from_yaml(config_path)

    assert settings.raw_data == external


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("paths: [invalid]\n", "'paths' and 'ingestion' must be YAML mappings"),
        (
            "paths:\n  raw_data: ''\ningestion:\n  sessions: [R]\n  download_scope: [results]\n",
            "paths.raw_data must be a non-empty path string",
        ),
        (
            "ingestion:\n  sessions: [NOT_A_SESSION]\n  download_scope: [results]\n",
            "Unsupported session code",
        ),
        (
            "ingestion:\n  start_year: nope\n  sessions: [R]\n  download_scope: [results]\n",
            "start_year and end_year must be integer years",
        ),
        (
            "logging:\n  level: TRACE\n",
            "logging.level must be",
        ),
    ],
)
def test_invalid_configuration_has_actionable_error(
    tmp_path: Path, content: str, message: str
) -> None:
    config_path = _write_config(tmp_path / "project" / "config" / "settings.yaml", content)

    with pytest.raises(ConfigurationError, match=message):
        IngestionSettings.from_yaml(config_path)


def test_missing_or_malformed_config_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="Unable to read settings file"):
        IngestionSettings.from_yaml(tmp_path / "missing.yaml")

    malformed = _write_config(
        tmp_path / "project" / "config" / "settings.yaml",
        "paths: [unterminated",
    )
    with pytest.raises(ConfigurationError, match="Invalid YAML"):
        IngestionSettings.from_yaml(malformed)
