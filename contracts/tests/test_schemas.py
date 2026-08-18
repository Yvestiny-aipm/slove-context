"""Validate node 0.4 JSON Schema contracts and their examples.

No external model calls. Draft 2020-12 only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema.validators import Draft202012Validator

CONTRACTS = Path(__file__).resolve().parents[1]
EXAMPLES = CONTRACTS / "examples"

SCHEMA_NAMES = (
    "story-spec",
    "scene-card",
    "scene-plan",
    "candidate-change",
    "validation-report",
    "approval-decision",
    "context-pack",
)

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"

CANDIDATE_FROZEN_FIELDS = (
    "subject",
    "predicate",
    "object",
    "value",
    "effective_story_time",
    "source_scene_id",
    "evidence_quote",
    "confidence",
    "status",
)

CANDIDATE_STATUSES = (
    "Extracted",
    "Validating",
    "FailedValidation",
    "AwaitingVerdict",
    "Approved",
    "Rejected",
    "Submitted",
    "Failed",
    "Cancelled",
    "Rework",
)

VIOLATION_FROZEN_FIELDS = (
    "rule_id",
    "severity",
    "entity_ids",
    "source_evidence",
    "canon_evidence",
    "recommended_action",
)

SHARED_REQUIRED = (
    "schema_version",
    "id",
    "project_id",
    "created_at",
    "created_by",
)

FORBIDDEN_PROPERTY_NAMES = frozenset(
    {
        "auto_approve",
        "auto_approval",
        "autoApprove",
        "autoApproval",
        "auto_approved",
        "write_canon",
        "commit_canon",
        "promote_to_canon",
        "canon_writable",
    }
)


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_path(name: str) -> Path:
    return CONTRACTS / f"{name}.schema.json"


def _validator(schema: dict) -> Draft202012Validator:
    return Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    )


def _property_names(node: object) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            names.update(props)
        for value in node.values():
            names.update(_property_names(value))
    elif isinstance(node, list):
        for item in node:
            names.update(_property_names(item))
    return names


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_is_draft_2020_12_and_valid(name: str) -> None:
    path = _schema_path(name)
    assert path.is_file(), f"missing schema: {path}"
    schema = _load(path)
    assert isinstance(schema, dict)
    assert schema.get("$schema") == DRAFT_2020_12
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_requires_shared_envelope(name: str) -> None:
    schema = _load(_schema_path(name))
    required = schema.get("required", [])
    for field in SHARED_REQUIRED:
        assert field in required, f"{name} must require {field}"
        assert field in schema.get("properties", {}), f"{name} must define {field}"


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_valid_example_passes(name: str) -> None:
    schema = _load(_schema_path(name))
    example = EXAMPLES / f"{name}.valid.json"
    assert example.is_file(), f"missing valid example: {example}"
    _validator(schema).validate(_load(example))


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_invalid_example_is_rejected(name: str) -> None:
    schema = _load(_schema_path(name))
    example = EXAMPLES / f"{name}.invalid.json"
    assert example.is_file(), f"missing invalid example: {example}"
    errors = list(_validator(schema).iter_errors(_load(example)))
    assert errors, f"{name} invalid example must be rejected"


def test_candidate_change_has_frozen_fields_and_statuses() -> None:
    schema = _load(_schema_path("candidate-change"))
    required = schema.get("required", [])
    for field in CANDIDATE_FROZEN_FIELDS:
        assert field in required, f"candidate-change must require {field}"
        assert field in schema.get("properties", {})

    status_def = schema["$defs"]["candidate_change_status"]
    consts = [item["const"] for item in status_def["oneOf"]]
    assert consts == list(CANDIDATE_STATUSES)


def test_violation_has_frozen_fields() -> None:
    schema = _load(_schema_path("validation-report"))
    violation = schema["$defs"]["violation"]
    required = violation.get("required", [])
    for field in VIOLATION_FROZEN_FIELDS:
        assert field in required, f"violation must require {field}"
        assert field in violation.get("properties", {})


def test_no_auto_approval_or_system_canon_write_fields() -> None:
    for name in SCHEMA_NAMES:
        schema = _load(_schema_path(name))
        names = _property_names(schema)
        forbidden = names & FORBIDDEN_PROPERTY_NAMES
        assert not forbidden, f"{name} must not define {sorted(forbidden)}"


def test_approval_decision_is_approve_or_reject_only() -> None:
    schema = _load(_schema_path("approval-decision"))
    consts = [
        item["const"] for item in schema["$defs"]["decision"]["oneOf"]
    ]
    assert consts == ["Approve", "Reject"]
