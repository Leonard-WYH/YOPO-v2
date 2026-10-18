"""Resolve project resources independently of the caller's working directory."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
YOPO_ROOT = PROJECT_ROOT / 'YOPO'


def project_path(value):
    """Relative paths are always relative to the repository root."""
    path = Path(value).expanduser()
    return (PROJECT_ROOT / path).resolve()


def relative_path(value):
    """Store paths relative to the repository, including user-selected outputs."""
    return Path(os.path.relpath(project_path(value), PROJECT_ROOT)).as_posix()


def portable_report(value):
    """Normalize paths in both current and older local verification records."""
    if isinstance(value, dict):
        return {key: portable_report(item) for key, item in value.items()}
    if isinstance(value, list):
        return [portable_report(item) for item in value]
    if isinstance(value, str):
        if value.startswith(str(PROJECT_ROOT) + os.sep):
            return relative_path(value)
        if value == os.environ.get('CONDA_PREFIX'):
            return '${CONDA_PREFIX}'
    return value
