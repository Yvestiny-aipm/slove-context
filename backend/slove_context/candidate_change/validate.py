"""Validate payloads against frozen 0.4 contracts.

Candidate Change: contracts/candidate-change.schema.json
Approval Decision: contracts/approval-decision.schema.json (node 4.2).
This is not Validate / Validation Run (5.x).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema.validators import Draft202012Validator

SCHEMA_FILENAME = "candidate-change.schema.json"
APPROVAL_SCHEMA_FILENAME = "approval-decision.schema.json"


class CandidateChangeSchemaError(ValueError):
    """Payload failed contracts/candidate-change.schema.json (Draft 2020-12)."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("Candidate Change failed schema validation")


class ApprovalDecisionSchemaError(ValueError):
    """Payload failed contracts/approval-decision.schema.json (Draft 2020-12)."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("Approval Decision failed schema validation")


def _find_contracts_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "contracts" / SCHEMA_FILENAME
        if candidate.is_file():
            return candidate.parent
    raise FileNotFoundError(f"Could not locate contracts/{SCHEMA_FILENAME} from {here}")


def _load_schema(filename: str) -> dict[str, Any]:
    path = _find_contracts_dir() / filename
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError(f"{filename} must be a JSON object")
    return loaded


@lru_cache(maxsize=1)
def load_candidate_change_schema() -> dict[str, Any]:
    return _load_schema(SCHEMA_FILENAME)


@lru_cache(maxsize=1)
def load_approval_decision_schema() -> dict[str, Any]:
    return _load_schema(APPROVAL_SCHEMA_FILENAME)


def _schema_errors(
    schema: dict[str, Any], payload: dict[str, Any]
) -> list[dict[str, str]]:
    validator = Draft202012Validator(
        schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    return [
        {
            "path": ".".join(str(part) for part in error.absolute_path),
            "message": error.message,
        }
        for error in validator.iter_errors(payload)
    ]


def validate_candidate_change(payload: dict[str, Any]) -> None:
    """Raise CandidateChangeSchemaError if payload is not a valid candidate."""
    errors = _schema_errors(load_candidate_change_schema(), payload)
    if errors:
        raise CandidateChangeSchemaError(errors)


def validate_approval_decision(payload: dict[str, Any]) -> None:
    """Raise ApprovalDecisionSchemaError if payload is not a valid decision."""
    errors = _schema_errors(load_approval_decision_schema(), payload)
    if errors:
        raise ApprovalDecisionSchemaError(errors)
