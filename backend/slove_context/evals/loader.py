"""Load and schema-check eval cases. No network. No production writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slove_context.candidate_change.validate import validate_candidate_change
from slove_context.context_pack.validate import validate_context_pack
from slove_context.evals.constants import (
    DIFFICULTIES,
    EVAL_SCHEMA_VERSION,
    REQUIRED_CATEGORIES,
    SEVERITIES,
)
from slove_context.evals.models import EvalCaseManifest, LoadedEvalCase
from slove_context.evals.paths import find_evals_root, repo_root
from slove_context.scene.validate import validate_scene_card
from slove_context.story.validate import validate_story_spec


class EvalCaseError(ValueError):
    """An eval case file is missing fields or failed a contract check."""


_FIXTURE_KEYS = (
    "story_spec",
    "canon_snapshot",
    "scene_card",
    "context_pack",
    "draft",
)
_EXPECTED_KEYS = ("candidate_changes", "violations")


def load_all_cases(evals_root: Path | None = None) -> list[LoadedEvalCase]:
    root = evals_root or find_evals_root()
    cases_dir = root / "cases"
    loaded = [load_case(path, evals_root=root) for path in _case_files(cases_dir)]
    _require_categories(loaded)
    return loaded


def load_case(path: Path, *, evals_root: Path | None = None) -> LoadedEvalCase:
    root = evals_root or find_evals_root(path)
    base = repo_root(root)
    raw = _read_json(path)
    manifest = _manifest_from_payload(raw, source_path=str(path))
    fixtures = {
        key: _read_json(_resolve(base, manifest.fixture_paths[key]))
        for key in _FIXTURE_KEYS
    }
    expected_candidates = _read_json(
        _resolve(base, manifest.expected_paths["candidate_changes"])
    )
    expected_violations = _read_json(
        _resolve(base, manifest.expected_paths["violations"])
    )
    _validate_contract_payloads(
        story_spec=fixtures["story_spec"],
        scene_card=fixtures["scene_card"],
        context_pack=fixtures["context_pack"],
        snapshot=fixtures["canon_snapshot"],
        draft=fixtures["draft"],
        candidates=_candidate_items(expected_candidates),
        violations=_violation_items(expected_violations),
    )
    return LoadedEvalCase(
        manifest=manifest,
        story_spec=fixtures["story_spec"],
        canon_snapshot=fixtures["canon_snapshot"],
        scene_card=fixtures["scene_card"],
        context_pack=fixtures["context_pack"],
        draft=fixtures["draft"],
        expected_candidates=_candidate_items(expected_candidates),
        expected_violations=_violation_items(expected_violations),
    )


def _case_files(cases_dir: Path) -> list[Path]:
    if not cases_dir.is_dir():
        raise EvalCaseError(f"Missing evals/cases directory: {cases_dir}")
    files = sorted(
        path
        for path in cases_dir.glob("*.json")
        if path.is_file() and not path.name.startswith("_")
    )
    if not files:
        raise EvalCaseError(f"No eval case manifests in {cases_dir}")
    return files


def _manifest_from_payload(
    raw: dict[str, Any], *, source_path: str
) -> EvalCaseManifest:
    required = (
        "id",
        "title",
        "difficulty",
        "rule_category",
        "expected_severity",
        "human_verdict_rationale",
        "fixtures",
        "expected",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise EvalCaseError(f"{source_path} missing fields: {missing}")
    difficulty = str(raw["difficulty"])
    if difficulty not in DIFFICULTIES:
        raise EvalCaseError(f"{source_path} unknown difficulty {difficulty!r}")
    severity = str(raw["expected_severity"])
    if severity not in SEVERITIES:
        raise EvalCaseError(f"{source_path} unknown severity {severity!r}")
    fixtures = raw["fixtures"]
    expected = raw["expected"]
    if not isinstance(fixtures, dict) or not isinstance(expected, dict):
        raise EvalCaseError(f"{source_path} fixtures/expected must be objects")
    for key in _FIXTURE_KEYS:
        if key not in fixtures:
            raise EvalCaseError(f"{source_path} fixtures missing {key}")
    for key in _EXPECTED_KEYS:
        if key not in expected:
            raise EvalCaseError(f"{source_path} expected missing {key}")
    rationale = str(raw["human_verdict_rationale"]).strip()
    if not rationale:
        raise EvalCaseError(f"{source_path} human_verdict_rationale is empty")
    return EvalCaseManifest(
        id=str(raw["id"]),
        title=str(raw["title"]),
        difficulty=difficulty,
        rule_category=str(raw["rule_category"]),
        expected_severity=severity,
        human_verdict_rationale=rationale,
        fixture_paths={key: str(fixtures[key]) for key in _FIXTURE_KEYS},
        expected_paths={key: str(expected[key]) for key in _EXPECTED_KEYS},
        schema_version=str(raw.get("schema_version") or EVAL_SCHEMA_VERSION),
        source_path=source_path,
    )


def _validate_contract_payloads(
    *,
    story_spec: dict[str, Any],
    scene_card: dict[str, Any],
    context_pack: dict[str, Any],
    snapshot: dict[str, Any],
    draft: dict[str, Any],
    candidates: list[dict[str, Any]],
    violations: list[dict[str, Any]],
) -> None:
    validate_story_spec(story_spec)
    validate_scene_card(scene_card)
    validate_context_pack(context_pack)
    if snapshot.get("eval_kind") != "canon_snapshot":
        raise EvalCaseError("canon_snapshot must be an eval-only wrapper")
    if not isinstance(snapshot.get("entities"), list):
        raise EvalCaseError("canon_snapshot.entities must be an array")
    if not isinstance(snapshot.get("facts"), list):
        raise EvalCaseError("canon_snapshot.facts must be an array")
    if draft.get("eval_kind") != "scene_draft":
        raise EvalCaseError("draft must be an eval-only wrapper")
    if not str(draft.get("prose") or "").strip():
        raise EvalCaseError("draft.prose must be non-empty")
    for candidate in candidates:
        validate_candidate_change(candidate)
    for violation in violations:
        _require_violation_fields(violation)


def _require_violation_fields(payload: dict[str, Any]) -> None:
    required = (
        "rule_id",
        "severity",
        "entity_ids",
        "source_evidence",
        "canon_evidence",
        "recommended_action",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise EvalCaseError(f"expected violation missing {missing}")
    if payload["severity"] not in SEVERITIES:
        raise EvalCaseError(f"invalid violation severity {payload['severity']!r}")
    if not payload["entity_ids"]:
        raise EvalCaseError("violation.entity_ids must be non-empty")


def _candidate_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise EvalCaseError("expected candidate_changes.items must be an array")
    return [dict(item) for item in items if isinstance(item, dict)]


def _violation_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise EvalCaseError("expected violations.items must be an array")
    return [dict(item) for item in items if isinstance(item, dict)]


def _require_categories(loaded: list[LoadedEvalCase]) -> None:
    present = {item.manifest.rule_category for item in loaded}
    missing = [name for name in REQUIRED_CATEGORIES if name not in present]
    if missing:
        raise EvalCaseError(f"eval set missing required categories: {missing}")


def _resolve(repo: Path, relative: str) -> Path:
    path = Path(relative)
    resolved = path if path.is_absolute() else repo / path
    if not resolved.is_file():
        raise EvalCaseError(f"Missing eval file: {relative}")
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise EvalCaseError(f"{path} must be a JSON object")
    return loaded
