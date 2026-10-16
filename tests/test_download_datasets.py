"""Tests for Kaggle dataset staging and inventory without network access."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from scripts.download_datasets import (
    DatasetDownloadError,
    DatasetSpec,
    authentication_configured,
    build_inventory,
    run_downloads,
    stage_download,
    write_inventory_report,
)


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_authentication_detection_does_not_require_printing_credentials(
    tmp_path: Path,
) -> None:
    assert not authentication_configured({}, tmp_path)
    assert authentication_configured({"KAGGLE_API_TOKEN": "not-printed"}, tmp_path)
    assert authentication_configured(
        {"KAGGLE_USERNAME": "user", "KAGGLE_KEY": "key"}, tmp_path
    )

    config_dir = tmp_path / "custom-kaggle"
    _write(config_dir / "kaggle.json", b'{"username":"user","key":"key"}')
    assert authentication_configured({"KAGGLE_CONFIG_DIR": str(config_dir)}, tmp_path)


def test_stage_download_copies_and_skips_identical_files(tmp_path: Path) -> None:
    source = tmp_path / "cache" / "dataset"
    source_file = _write(source / "nested" / "results.csv", b"driver,points\nA,10\n")
    destination = tmp_path / "project" / "data" / "raw" / "source"

    copied = stage_download(source, destination)
    assert copied == [destination / "nested" / "results.csv"]
    assert copied[0].read_bytes() == source_file.read_bytes()

    assert stage_download(source, destination) == copied


@pytest.mark.parametrize("source_exists", [False, True])
def test_stage_download_rejects_missing_or_empty_directory(
    tmp_path: Path, source_exists: bool
) -> None:
    source = tmp_path / "cache" / "empty"
    if source_exists:
        source.mkdir(parents=True)

    with pytest.raises(DatasetDownloadError, match="Downloaded"):
        stage_download(source, tmp_path / "destination")


def test_stage_download_refuses_to_overwrite_different_existing_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "cache"
    destination = tmp_path / "destination"
    _write(source / "results.csv", b"new source")
    existing = _write(destination / "results.csv", b"keep existing")

    with pytest.raises(DatasetDownloadError, match="refusing to overwrite"):
        stage_download(source, destination)
    assert existing.read_bytes() == b"keep existing"


def test_inventory_reports_csv_schema_missing_and_duplicate_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    csv_file = _write(
        root / "data" / "raw" / "source" / "results.csv",
        b"driver,points,note\nA,10,\nA,10,\nB,,ok\n",
    )

    entries = build_inventory("owner/dataset", root, [csv_file])
    report = "\n".join(entries)

    assert "Rows: 3" in report
    assert "Columns: 3" in report
    assert "driver (" in report
    assert "points (" in report
    assert "missing=1" in report
    assert "Duplicate rows: 1" in report
    assert f"File size: {csv_file.stat().st_size} bytes" in report
    assert "Read errors: none" in report


def test_inventory_reports_parquet_schema_and_quality(tmp_path: Path) -> None:
    root = tmp_path / "project"
    parquet_file = root / "data" / "source.parquet"
    parquet_file.parent.mkdir(parents=True)
    buffer = BytesIO()
    pd.DataFrame({"driver": ["A", "A", "B"], "points": [10, 10, None]}).to_parquet(
        buffer, index=False
    )
    parquet_file.write_bytes(buffer.getvalue())

    report = "\n".join(build_inventory("owner/dataset", root, [parquet_file]))

    assert "Format: Parquet" in report
    assert "Rows: 3" in report
    assert "Columns: 2" in report
    assert "driver (" in report
    assert "points (" in report
    assert "missing=1" in report
    assert "Duplicate rows: 1" in report


def test_inventory_reads_supported_tabular_member_without_extracting(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    archive_path = root / "data" / "raw" / "source" / "download.zip"
    archive_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("tables/results.csv", "driver,position\nA,1\n")
        archive.writestr("../outside.csv", "not,extracted\n")

    entries = build_inventory("owner/dataset", root, [archive_path])
    report = "\n".join(entries)

    assert "download.zip!tables/results.csv" in report
    assert "Rows: 1" in report
    assert not (tmp_path / "outside.csv").exists()
    assert sorted(path.name for path in archive_path.parent.iterdir()) == [
        "download.zip"
    ]


def test_inventory_records_read_errors(tmp_path: Path) -> None:
    root = tmp_path / "project"
    csv_file = _write(root / "broken.csv", b'"unterminated\n')

    report = "\n".join(build_inventory("owner/dataset", root, [csv_file]))

    assert "Rows: unavailable" in report
    assert "Read errors:" in report


def test_run_downloads_reports_each_dataset_failure_and_writes_report(
    tmp_path: Path,
) -> None:
    first = DatasetSpec("owner/first", "First", Path("data/raw/first"))
    second = DatasetSpec("owner/second", "Second", Path("data/raw/second"))
    source = tmp_path / "cache" / "first"
    _write(source / "data.csv", b"value\n1\n")

    def fake_downloader(identifier: str) -> Path:
        if identifier == first.identifier:
            return source
        raise PermissionError("access denied")

    results = run_downloads(
        tmp_path, (first, second), downloader=fake_downloader, auth_available=False
    )
    report_path = tmp_path / "reports" / "dataset_inventory.txt"
    write_inventory_report(report_path, results, auth_available=False)
    report = report_path.read_text(encoding="utf-8")

    assert [result.succeeded for result in results] == [True, False]
    assert results[1].error is not None and "PermissionError" in results[1].error
    assert "owner/first" in report and "owner/second" in report
    assert "Authentication configured: no" in report
    assert "Status: SUCCESS" in report and "Status: FAILED" in report


def test_run_downloads_rejects_missing_download_directory(tmp_path: Path) -> None:
    spec = DatasetSpec("owner/missing", "Missing", Path("data/raw/missing"))

    results = run_downloads(
        tmp_path,
        (spec,),
        downloader=lambda _: tmp_path / "no-such-download",
        auth_available=True,
    )

    assert not results[0].succeeded
    assert "DatasetDownloadError" in (results[0].error or "")


def test_run_downloads_skips_verified_existing_data(tmp_path: Path) -> None:
    spec = DatasetSpec("owner/present", "Present", Path("data/raw/present"))
    existing = _write(
        tmp_path / spec.destination / "results.csv",
        b"driver,points\nA,10\n",
    )

    def unexpected_download(_identifier: str) -> Path:
        raise AssertionError("verified local files should not be downloaded again")

    result = run_downloads(
        tmp_path, (spec,), downloader=unexpected_download, auth_available=True
    )[0]

    assert result.succeeded
    assert result.staged_files == [existing]
    assert any("Read errors: none" in entry for entry in result.inventory)
