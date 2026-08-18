"""Locate the repo-root ``evals/`` tree from any working directory."""

from __future__ import annotations

from pathlib import Path


def find_evals_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__).resolve()).resolve()
    candidates = [here, *here.parents]
    for parent in candidates:
        cases = parent / "evals" / "cases"
        if cases.is_dir():
            return parent / "evals"
    raise FileNotFoundError(f"Could not locate evals/cases from {here}")


def repo_root(start: Path | None = None) -> Path:
    return find_evals_root(start).parent
