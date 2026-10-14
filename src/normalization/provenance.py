"""What produced an output (A-71): the code, next to the bundle and mapping files the output records.

A changed result can then be explained: a different snapshot (bundle SHA-256), a different evaluation
date, a different mapping file (its SHA-256), or different code (version, commit, and whether the
working tree had uncommitted changes).
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from functools import cache
from importlib import metadata
from pathlib import Path
from typing import Any

from .output import Output

PACKAGE = "tada-normalization"


@cache
def tool() -> dict[str, Any]:
    """The package version and, when run from a git checkout, its commit."""
    try:
        version: str | None = metadata.version(PACKAGE)
    except metadata.PackageNotFoundError:
        version = None
    checkout = Path(__file__).resolve().parents[2]
    # Only a checkout running its own source can name the commit: an installed copy may differ from it.
    running_from_checkout = (checkout / "src" / "normalization" / Path(__file__).name).resolve() == Path(
        __file__
    ).resolve()
    commit = _git(checkout, "rev-parse", "HEAD") if running_from_checkout else None
    changes = _git(checkout, "status", "--porcelain", "--untracked-files=no") if commit else None
    return {
        "name": PACKAGE,
        "version": version,
        "commit": commit,
        "uncommitted_changes": bool(changes) if commit else None,
    }


def document(output: Output) -> dict[str, Any]:
    """Everything known about how an output was produced, for provenance.json."""
    return {**output.provenance, "tool": tool(), "written_at": datetime.now(UTC).isoformat(timespec="seconds")}


def _git(checkout: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None
