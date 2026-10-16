"""Download and inventory the three project Kaggle datasets."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

LOGGER = logging.getLogger("f1_dataset_download")


@dataclass(frozen=True)
class DatasetSpec:
    """A Kaggle dataset and its project-local destination."""

    identifier: str
    label: str
    destination: Path


@dataclass
class DatasetResult:
    """Download and inventory status for one source dataset."""

    spec: DatasetSpec
    staged_files: list[Path]
    inventory: list[str]
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and bool(self.staged_files)


DATASETS = (
    DatasetSpec(
        "anthonytherrien/predicting-f1-pit-stops-vault",
        "Pit-stop data",
        Path("data/raw/pit_stops"),
    ),
    DatasetSpec(
        "navenkumar1998/formula-1-dataset-with-weather-and-tyre-features",
        "Weather and tyre features",
        Path("data/raw/weather_tyre"),
    ),
    DatasetSpec(
        "rohanrao/formula-1-world-championship-1950-2020",
        "Historical Formula 1 data",
        Path("data/raw/historical_f1"),
    ),
)

TABULAR_SUFFIXES = {
    ".csv",
    ".tsv",
    ".json",
    ".xlsx",
    ".xls",
    ".xlsm",
    ".parquet",
}


class DatasetDownloadError(RuntimeError):
    """Raised when a dataset cannot be downloaded, staged, or validated."""


def authentication_configured(
    environ: dict[str, str] | None = None, home: Path | None = None
) -> bool:
    """Return whether a documented KaggleHub credential location is present."""
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home

    if environment.get("KAGGLE_API_TOKEN", "").strip():
        return True
    if environment.get("KAGGLE_USERNAME", "").strip() and environment.get(
        "KAGGLE_KEY", ""
    ).strip():
        return True

    credential_dir = Path(
        environment.get("KAGGLE_CONFIG_DIR", str(user_home / ".kaggle"))
    )
    candidates = (
        credential_dir / "kaggle.json",
        credential_dir / "access_token",
        user_home / ".config" / "kaggle" / "access_token",
    )
    return any(path.is_file() and path.stat().st_size > 0 for path in candidates)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stage_download(source_directory: Path, destination: Path) -> list[Path]:
    """Copy a KaggleHub directory without modifying its cache or overwriting conflicts."""
    source = source_directory.expanduser().resolve()
    target_root = destination.resolve()
    if not source.exists() or not source.is_dir():
        raise DatasetDownloadError(
            f"Downloaded path is missing or is not a directory: {source_directory}"
        )

    source_files = sorted(source.rglob("*"))
    files: list[Path] = []
    for source_file in source_files:
        if source_file.is_symlink():
            raise DatasetDownloadError(
                f"Refusing to stage a symbolic link from downloaded data: {source_file}"
            )
        if source_file.is_file():
            files.append(source_file)
    if not files:
        raise DatasetDownloadError(
            f"Downloaded directory contains no files: {source_directory}"
        )

    staged: list[Path] = []
    for source_file in files:
        relative = source_file.relative_to(source)
        destination_file = target_root / relative
        resolved_target = destination_file.resolve()
        if not resolved_target.is_relative_to(target_root):
            raise DatasetDownloadError(
                f"Downloaded file resolves outside its destination: {relative}"
            )
        destination_file.parent.mkdir(parents=True, exist_ok=True)

        if destination_file.exists():
            if not destination_file.is_file():
                raise DatasetDownloadError(
                    f"Destination exists but is not a regular file: {destination_file}"
                )
            if _sha256(source_file) != _sha256(destination_file):
                raise DatasetDownloadError(
                    "Destination file differs from the downloaded source; "
                    f"refusing to overwrite: {destination_file}"
                )
            LOGGER.info("Unchanged file already staged: %s", destination_file)
        elif source_file.resolve() != destination_file.resolve():
            temporary_file = destination_file.with_name(destination_file.name + ".tmp")
            try:
                shutil.copy2(source_file, temporary_file)
                if _sha256(source_file) != _sha256(temporary_file):
                    raise DatasetDownloadError(
                        f"Copied file failed SHA-256 verification: {relative}"
                    )
                temporary_file.replace(destination_file)
            finally:
                temporary_file.unlink(missing_ok=True)
            LOGGER.info("Staged %s", destination_file)

        if not destination_file.is_file():
            raise DatasetDownloadError(
                f"Staged file is missing after copy: {destination_file}"
            )
        if source_file.stat().st_size != destination_file.stat().st_size:
            raise DatasetDownloadError(
                f"Staged file size does not match downloaded source: {relative}"
            )
        staged.append(destination_file)
    return staged


def _dataframe_inventory(
    dataset_id: str,
    display_path: str,
    file_format: str,
    file_size: int,
    frame: pd.DataFrame,
) -> str:
    null_counts = frame.isna().sum()
    columns = ", ".join(
        f"{name} ({frame[name].dtype}, missing={int(null_counts[name])})"
        for name in frame.columns
    )
    duplicate_count = int(frame.duplicated().sum()) if len(frame.columns) else 0
    return (
        f"Dataset: {dataset_id}\n"
        f"File: {display_path}\n"
        f"Format: {file_format}\n"
        f"File size: {file_size} bytes\n"
        f"Rows: {len(frame)}\n"
        f"Columns: {len(frame.columns)}\n"
        f"Column details: {columns or '(no columns)'}\n"
        f"Duplicate rows: {duplicate_count}\n"
        f"Read errors: none\n"
    )


def _read_json_frame(content: bytes) -> pd.DataFrame:
    value = json.loads(content.decode("utf-8-sig"))
    if isinstance(value, dict) and isinstance(value.get("records"), list):
        return pd.json_normalize(value["records"])
    if isinstance(value, list):
        return pd.json_normalize(value)
    if isinstance(value, dict):
        return pd.json_normalize(value)
    raise ValueError("JSON root must be an object or array")


def _inspect_tabular_bytes(
    dataset_id: str, display_path: str, suffix: str, content: bytes
) -> list[str]:
    suffix = suffix.lower()
    try:
        if suffix == ".csv":
            frame = pd.read_csv(BytesIO(content))
            format_name = "CSV"
        elif suffix == ".tsv":
            frame = pd.read_csv(BytesIO(content), sep="\t")
            format_name = "TSV"
        elif suffix == ".json":
            frame = _read_json_frame(content)
            format_name = "JSON"
        elif suffix == ".parquet":
            frame = pd.read_parquet(BytesIO(content))
            format_name = "Parquet"
        elif suffix in {".xlsx", ".xls", ".xlsm"}:
            sheets = pd.read_excel(BytesIO(content), sheet_name=None)
            format_name = "Excel"
            return [
                _dataframe_inventory(
                    dataset_id,
                    f"{display_path} [sheet: {sheet_name}]",
                    format_name,
                    len(content),
                    frame,
                )
                for sheet_name, frame in sheets.items()
            ]
        else:
            return []
        return [
            _dataframe_inventory(
                dataset_id, display_path, format_name, len(content), frame
            )
        ]
    except Exception as exc:
        return [
            f"Dataset: {dataset_id}\n"
            f"File: {display_path}\n"
            f"Format: {suffix.lstrip('.').upper() or 'unknown'}\n"
            "Rows: unavailable\n"
            "Columns: unavailable\n"
            "Missing values: unavailable\n"
            "Duplicate rows: unavailable\n"
            f"Read errors: {type(exc).__name__}: {exc}\n"
        ]


def inventory_file(dataset_id: str, root: Path, file_path: Path) -> list[str]:
    """Inventory one staged file, including readable tabular ZIP members."""
    relative_path = file_path.relative_to(root).as_posix()
    size = file_path.stat().st_size
    suffix = file_path.suffix.lower()
    base = (
        f"Dataset: {dataset_id}\n"
        f"File: {relative_path}\n"
        f"Format: {suffix.lstrip('.').upper() or 'unknown'}\n"
        f"File size: {size} bytes\n"
    )

    if suffix == ".zip":
        entries = [base + "Rows: not applicable (archive)\n"]
        try:
            with zipfile.ZipFile(file_path) as archive:
                for member in sorted(archive.infolist(), key=lambda item: item.filename):
                    if member.is_dir():
                        continue
                    member_display = f"{relative_path}!{member.filename}"
                    member_suffix = Path(member.filename).suffix.lower()
                    if member_suffix not in TABULAR_SUFFIXES:
                        entries.append(
                            f"Dataset: {dataset_id}\n"
                            f"File: {member_display}\n"
                            "Format: archive member (not tabular or unsupported)\n"
                            f"File size: {member.file_size} bytes\n"
                            "Read errors: not inspected\n"
                        )
                        continue
                    content = archive.read(member)
                    entries.extend(
                        _inspect_tabular_bytes(
                            dataset_id, member_display, member_suffix, content
                        )
                    )
        except Exception as exc:
            entries.append(f"Read errors: {type(exc).__name__}: {exc}\n")
        return entries

    if suffix in TABULAR_SUFFIXES:
        try:
            return _inspect_tabular_bytes(
                dataset_id, relative_path, suffix, file_path.read_bytes()
            )
        except OSError as exc:
            return [base + f"Read errors: {type(exc).__name__}: {exc}\n"]
    return [base + "Rows: not applicable (non-tabular or unsupported format)\n"]


def build_inventory(
    dataset_id: str, root: Path, files: Iterable[Path]
) -> list[str]:
    """Build inventory entries for staged files in deterministic path order."""
    return [
        entry
        for file_path in sorted(files)
        for entry in inventory_file(dataset_id, root, file_path)
    ]


def _safe_error_message(error: Exception) -> str:
    message = str(error)
    secrets = {
        os.environ.get(name, "")
        for name in ("KAGGLE_API_TOKEN", "KAGGLE_KEY")
        if os.environ.get(name)
    }
    for secret in secrets:
        message = message.replace(secret, "[REDACTED]")
    return f"{type(error).__name__}: {message}"


def run_downloads(
    project_root: Path,
    dataset_specs: Iterable[DatasetSpec] = DATASETS,
    downloader: Callable[[str], str | Path] | None = None,
    auth_available: bool | None = None,
) -> list[DatasetResult]:
    """Download, stage, and inventory each configured dataset independently."""
    if downloader is None:
        try:
            import kagglehub
        except ImportError as exc:
            raise DatasetDownloadError(
                "kagglehub is not installed; install project dependencies first"
            ) from exc
        downloader = kagglehub.dataset_download

    authenticated = (
        authentication_configured() if auth_available is None else auth_available
    )
    if not authenticated:
        LOGGER.warning(
            "No Kaggle credentials detected. Public datasets may still download; "
            "consent-restricted/private datasets will fail. Configure access "
            "securely as documented in README.md."
        )

    results: list[DatasetResult] = []
    for spec in dataset_specs:
        destination = project_root / spec.destination
        LOGGER.info("Downloading %s (%s)", spec.label, spec.identifier)
        try:
            returned_path = downloader(spec.identifier)
            staged_files = stage_download(Path(returned_path), destination)
            inventory = build_inventory(spec.identifier, project_root, staged_files)
            results.append(DatasetResult(spec, staged_files, inventory))
            LOGGER.info(
                "Completed %s: %d files staged",
                spec.identifier,
                len(staged_files),
            )
        except Exception as exc:
            error = _safe_error_message(exc)
            LOGGER.error("Dataset %s failed: %s", spec.identifier, error)
            existing_files = (
                sorted(path for path in destination.rglob("*") if path.is_file())
                if destination.exists()
                else []
            )
            inventory = (
                build_inventory(spec.identifier, project_root, existing_files)
                if existing_files
                else []
            )
            results.append(DatasetResult(spec, existing_files, inventory, error))
    return results


def write_inventory_report(
    report_path: Path,
    results: Iterable[DatasetResult],
    auth_available: bool,
) -> None:
    """Write a truthful human-readable dataset and download status report."""
    result_list = list(results)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Formula 1 Race Intelligence — Kaggle dataset inventory",
        f"Authentication configured: {'yes' if auth_available else 'no'}",
        "",
    ]
    for result in result_list:
        status = "SUCCESS" if result.succeeded else "FAILED"
        lines.extend(
            [
                "=" * 78,
                f"Dataset: {result.spec.identifier}",
                f"Label: {result.spec.label}",
                f"Destination: {result.spec.destination.as_posix()}",
                f"Status: {status}",
                f"Files discovered/staged: {len(result.staged_files)}",
            ]
        )
        if result.error:
            lines.append(f"Download/staging error: {result.error}")
        lines.append("")
        if result.inventory:
            lines.extend(result.inventory)
        elif not result.error:
            lines.append("No files were available to inventory.\n")
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    """Run downloads and return a nonzero status if any required source failed."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    project_root = Path(__file__).resolve().parents[1]
    auth_available = authentication_configured()
    results = run_downloads(project_root, auth_available=auth_available)
    report_path = project_root / "reports" / "dataset_inventory.txt"
    write_inventory_report(report_path, results, auth_available)

    print("\nDataset download summary")
    for result in results:
        state = "SUCCESS" if result.succeeded else "FAILED"
        print(f"- {state}: {result.spec.identifier} ({len(result.staged_files)} files)")
        if result.error:
            print(f"  Error: {result.error}")
    print(f"Inventory report: {report_path}")

    return 0 if len(results) == len(DATASETS) and all(r.succeeded for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
