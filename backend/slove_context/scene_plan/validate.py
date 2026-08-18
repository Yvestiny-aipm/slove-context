"""Validate Scene Plan payloads against the frozen 0.4 contract."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema.validators import Draft202012Validator

SCHEMA_FILENAME = "scene-plan.schema.json"


class ScenePlanSchemaError(ValueError):
    """Payload failed contracts/scene-plan.schema.json (Draft 2020-12)."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("Scene Plan failed schema validation")


def _find_contracts_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "contracts" / SCHEMA_FILENAME
        if candidate.is_file():
            return candidate.parent
    raise FileNotFoundError(f"Could not locate contracts/{SCHEMA_FILENAME} from {here}")


@lru_cache(maxsize=1)
def load_scene_plan_schema() -> dict[str, Any]:
    path = _find_contracts_dir() / SCHEMA_FILENAME
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError(f"{SCHEMA_FILENAME} must be a JSON object")
    return loaded


def validate_scene_plan(payload: dict[str, Any]) -> None:
    """Raise ScenePlanSchemaError if payload is not a valid Scene Plan."""
    validator = Draft202012Validator(
        load_scene_plan_schema(),
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
        raise ScenePlanSchemaError(errors)
