"""Repository-relative locations shared by the dashboard and data scripts."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "processed" / "f1_intelligence.db"
DEFAULT_RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw"


def resolve_project_path(path: Path) -> Path:
    """Resolve a configured path against the repository root, not the CWD."""
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
