"""In-memory eval case and result records (node 9.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from slove_context.validation.models import Violation


@dataclass(frozen=True)
class EvalCaseManifest:
    """Case wrapper. Contract payloads live in fixture / expected files."""

    id: str
    title: str
    difficulty: str
    rule_category: str
    expected_severity: str
    human_verdict_rationale: str
    fixture_paths: dict[str, str]
    expected_paths: dict[str, str]
    schema_version: str
    source_path: str


@dataclass
class LoadedEvalCase:
    manifest: EvalCaseManifest
    story_spec: dict[str, Any]
    canon_snapshot: dict[str, Any]
    scene_card: dict[str, Any]
    context_pack: dict[str, Any]
    draft: dict[str, Any]
    expected_candidates: list[dict[str, Any]]
    expected_violations: list[dict[str, Any]]


@dataclass
class CaseResult:
    case_id: str
    rule_category: str
    difficulty: str
    expected_severity: str
    passed: bool
    hits: int
    misses: int
    extras: int
    expected_violation_count: int
    observed_violation_count: int
    observed_violations: list[dict[str, Any]]
    expected_violations: list[dict[str, Any]]
    missed_violations: list[dict[str, Any]]
    extra_violations: list[dict[str, Any]]
    observed_rule_ids: list[str]
    writes_canon: bool = False
    auto_approved: bool = False
    is_approval: bool = False
    used_real_model: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "rule_category": self.rule_category,
            "difficulty": self.difficulty,
            "expected_severity": self.expected_severity,
            "passed": self.passed,
            "hits": self.hits,
            "misses": self.misses,
            "extras": self.extras,
            "expected_violation_count": self.expected_violation_count,
            "observed_violation_count": self.observed_violation_count,
            "observed_violations": [dict(item) for item in self.observed_violations],
            "expected_violations": [dict(item) for item in self.expected_violations],
            "missed_violations": [dict(item) for item in self.missed_violations],
            "extra_violations": [dict(item) for item in self.extra_violations],
            "observed_rule_ids": list(self.observed_rule_ids),
            "writes_canon": False,
            "auto_approved": False,
            "is_approval": False,
            "used_real_model": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        # No prose, prompts, quotes, or text_evidence (1.3).
        return {
            "case_id": self.case_id,
            "rule_category": self.rule_category,
            "passed": self.passed,
            "hits": self.hits,
            "misses": self.misses,
            "extras": self.extras,
            "observed_rule_ids": list(self.observed_rule_ids),
            "writes_canon": False,
            "auto_approved": False,
            "is_approval": False,
            "used_real_model": False,
        }


@dataclass
class RunSummary:
    cases_run: int
    cases_passed: int
    cases_failed: int
    hits: int
    misses: int
    extras: int
    precision: float
    recall: float
    passed: bool
    writes_canon: bool = False
    auto_approved: bool = False
    used_real_model: bool = False
    categories: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "cases_run": self.cases_run,
            "cases_passed": self.cases_passed,
            "cases_failed": self.cases_failed,
            "hits": self.hits,
            "misses": self.misses,
            "extras": self.extras,
            "precision": self.precision,
            "recall": self.recall,
            "passed": self.passed,
            "writes_canon": False,
            "auto_approved": False,
            "is_approval": False,
            "used_real_model": False,
            "categories": list(self.categories),
        }


def violation_to_dict(item: Violation) -> dict[str, Any]:
    return item.to_public_dict()


def violation_key(payload: dict[str, Any]) -> tuple[Any, ...]:
    entities = tuple(payload.get("entity_ids") or [])
    return (
        payload.get("rule_id"),
        payload.get("severity"),
        entities,
        payload.get("recommended_action"),
        payload.get("source_evidence"),
        payload.get("canon_evidence"),
    )
