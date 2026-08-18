"""In-process Validation Run and Validation Report records (node 5.1).

Job states match docs/state-machines.md §5: Queued / Running / Passed /
RuleFailed / ExecFailed / Cancelled. Retrying and Rework are not
implemented (Rework opens Repair Task, which is node 5.2).

A report validates against contracts/validation-report.schema.json.
Passed is not Approval and does not write Canon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_SCHEMA_VERSION = "0.4.0"

RUN_QUEUED = "Queued"
RUN_RUNNING = "Running"
RUN_PASSED = "Passed"
RUN_RULE_FAILED = "RuleFailed"
RUN_EXEC_FAILED = "ExecFailed"
RUN_CANCELLED = "Cancelled"

RUN_STATES = frozenset(
    {
        RUN_QUEUED,
        RUN_RUNNING,
        RUN_PASSED,
        RUN_RULE_FAILED,
        RUN_EXEC_FAILED,
        RUN_CANCELLED,
    }
)
RUN_CANCELLABLE_STATES = frozenset({RUN_QUEUED, RUN_RUNNING})
RUN_TERMINAL_STATES = frozenset(
    {RUN_PASSED, RUN_RULE_FAILED, RUN_EXEC_FAILED, RUN_CANCELLED}
)

OUTCOME_PASSED = "Passed"
OUTCOME_RULE_FAILED = "RuleFailed"
OUTCOME_EXEC_FAILED = "ExecFailed"

OUTCOMES = frozenset({OUTCOME_PASSED, OUTCOME_RULE_FAILED, OUTCOME_EXEC_FAILED})

SEVERITY_BLOCKING = "Blocking"
SEVERITY_ADVISORY = "Advisory"

ACTION_REVISE_SCENE_PLAN = "ReviseScenePlan"
ACTION_REGENERATE = "Regenerate"
ACTION_REEXTRACT = "Reextract"
ACTION_HUMAN_REJECT = "HumanReject"

RULE_CANON_CONFLICT = "canon-active-conflict"
RULE_SPEC_FORBID = "spec-must-not-write"

SPEC_USABLE_STATUSES = frozenset({"Written", "Effective"})


@dataclass
class Violation:
    rule_id: str
    severity: str
    entity_ids: list[str]
    source_evidence: str
    canon_evidence: str
    recommended_action: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "entity_ids": list(self.entity_ids),
            "source_evidence": self.source_evidence,
            "canon_evidence": self.canon_evidence,
            "recommended_action": self.recommended_action,
        }


@dataclass
class ValidationReport:
    id: str
    project_id: str
    scene_id: str
    candidate_change_ids: list[str]
    outcome: str
    violations: list[Violation]
    schema_version: str
    created_at: str
    created_by: str
    payload: dict[str, Any]
    run_id: str

    def to_public_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    def to_audit_dict(self) -> dict[str, Any]:
        # Never include source_evidence / canon_evidence / quotes (1.3).
        return {
            "id": self.id,
            "run_id": self.run_id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "candidate_change_ids": list(self.candidate_change_ids),
            "outcome": self.outcome,
            "violation_count": len(self.violations),
            "violation_rule_ids": [item.rule_id for item in self.violations],
            "schema_version": self.schema_version,
            "writes_canon": False,
            "auto_approved": False,
            "is_approval": False,
        }


@dataclass
class ValidationRun:
    id: str
    project_id: str
    scene_id: str
    candidate_ids: list[str]
    state: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    snapshot_id: str | None = None
    spec_id: str | None = None
    report_id: str | None = None
    outcome: str | None = None
    transitions: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "candidate_ids": list(self.candidate_ids),
            "snapshot_id": self.snapshot_id,
            "spec_id": self.spec_id,
            "state": self.state,
            "outcome": self.outcome,
            "report_id": self.report_id,
            "transitions": [dict(item) for item in self.transitions],
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "is_canon": False,
            "is_approved": False,
            "writes_canon": False,
            "auto_approved": False,
            "is_approval": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "candidate_ids": list(self.candidate_ids),
            "snapshot_id": self.snapshot_id,
            "spec_id": self.spec_id,
            "state": self.state,
            "outcome": self.outcome,
            "report_id": self.report_id,
            "failure_reason": self.failure_reason,
            "is_canon": False,
            "writes_canon": False,
            "auto_approved": False,
            "is_approval": False,
        }
