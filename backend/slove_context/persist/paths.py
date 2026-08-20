"""Resolve the single default book snapshot path (node P.1)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ENV_BOOK_PATH = "SLOVE_BOOK_PATH"
DEFAULT_BOOK_FILENAME = "book.json"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_book_path() -> Path:
    return repo_root() / "data" / DEFAULT_BOOK_FILENAME


def normalize_book_path(path: Path) -> Path:
    """Accept a file or a data directory; the snapshot file is ``book.json``."""
    resolved = path.expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    if resolved.exists() and resolved.is_dir():
        return resolved / DEFAULT_BOOK_FILENAME
    if resolved.suffix.lower() == ".json":
        return resolved
    return resolved / DEFAULT_BOOK_FILENAME


def _under_pytest() -> bool:
    if os.environ.get("PYTEST_VERSION") or os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules


def resolve_persist_path(
    persist_path: str | Path | bool | None,
    *,
    any_repo_injected: bool,
) -> Path | None:
    """Decide whether ``create_app`` should attach a book snapshot.

    ``False`` / empty env disables persist. A concrete path always wins.
    Injected repositories (unit tests) stay in-memory unless a path is given.
    Pytest auto-persist is off so existing ``create_app()`` tests stay isolated.
    """
    if persist_path is False:
        return None
    if isinstance(persist_path, (str, Path)):
        text = str(persist_path).strip()
        if not text:
            return None
        return normalize_book_path(Path(text))
    if any_repo_injected:
        return None
    if _under_pytest():
        return None
    env = os.environ.get(ENV_BOOK_PATH)
    if env is not None and not env.strip():
        return None
    if env:
        return normalize_book_path(Path(env))
    return default_book_path()


def persist_file_has_book(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return False
    import json

    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    story = payload.get("story")
    if not isinstance(story, dict):
        return False
    projects = story.get("projects")
    return isinstance(projects, dict) and bool(projects)
