"""Validate Context Pack payloads against the frozen 0.4 contract."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema.validators import Draft202012Validator

SCHEMA_FILENAME = "context-pack.schema.json"


class ContextPackSchemaError(ValueError):
    """Payload failed contracts/context-pack.schema.json (Draft 2020-12)."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("Context Pack failed schema validation")


def _find_contracts_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "contracts" / SCHEMA_FILENAME
        if candidate.is_file():
            return candidate.parent
    raise FileNotFoundError(f"Could not locate contracts/{SCHEMA_FILENAME} from {here}")


@lru_cache(maxsize=1)
def load_context_pack_schema() -> dict[str, Any]:
    path = _find_contracts_dir() / SCHEMA_FILENAME
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError(f"{SCHEMA_FILENAME} must be a JSON object")
    return loaded


def validate_context_pack(payload: dict[str, Any]) -> None:
    """Raise ContextPackSchemaError if payload is not a valid Context Pack."""
    validator = Draft202012Validator(
        load_context_pack_schema(),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    errors = [
        {
            "path": ".".join(str(part) for part in error.absolute_path),
            "message": error.message,
        }
        for error in validator.iter_errors(payload)
    ]
    if errors:
        raise ContextPackSchemaError(errors)
