"""In-process Repair Task records (node 5.2).

States match docs/state-machines.md §6:
Opened / InProgress / Completed / Rechecking / RecheckPassed /
Failed / Cancelled / Rework.

recommended_action / action values match the 0.4 Validation Report
contract: ReviseScenePlan / Regenerate / Reextract / HumanReject.

A Repair Task is not Approval, not Canon, and not a Candidate Change.
Completed is not approve. RecheckPassed only means candidates may go
to AwaitingVerdict via the 5.1 Validation Run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from slove_context.validation.models import (
    ACTION_HUMAN_REJECT,
    ACTION_REEXTRACT,
    ACTION_REGENERATE,
    ACTION_REVISE_SCENE_PLAN,
)

TASK_OPENED = "Opened"
TASK_IN_PROGRESS = "InProgress"
TASK_COMPLETED = "Completed"
TASK_RECHECKING = "Rechecking"
TASK_RECHECK_PASSED = "RecheckPassed"
TASK_FAILED = "Failed"
TASK_CANCELLED = "Cancelled"
TASK_REWORK = "Rework"

TASK_STATES = frozenset(
    {
        TASK_OPENED,
        TASK_IN_PROGRESS,
        TASK_COMPLETED,
        TASK_RECHECKING,
        TASK_RECHECK_PASSED,
        TASK_FAILED,
        TASK_CANCELLED,
        TASK_REWORK,
    }
)

TASK_CANCELLABLE_STATES = frozenset(
    {
        TASK_OPENED,
        TASK_IN_PROGRESS,
        TASK_COMPLETED,
        TASK_RECHECKING,
        TASK_FAILED,
        TASK_REWORK,
    }
)

RECOMMENDED_ACTIONS = frozenset(
    {
        ACTION_REVISE_SCENE_PLAN,
        ACTION_REGENERATE,
        ACTION_REEXTRACT,
        ACTION_HUMAN_REJECT,
    }
)

RECHECK_PASSED = "Passed"
RECHECK_RULE_FAILED = "RuleFailed"
RECHECK_EXEC_FAILED = "ExecFailed"
RECHECK_NOT_APPLICABLE = "not_applicable"

HUMAN_REJECT_SKIP_REASON = "human_reject_no_new_candidates"

JOB_KIND_SCENE_PLAN = "scene_plan"
JOB_KIND_SCENE_DRAFT = "scene_draft"
JOB_KIND_EXTRACT = "extract"


@dataclass
class RepairTask:
    id: str
    project_id: str
    scene_id: str
    validation_run_id: str
    action: str
    state: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    report_id: str | None = None
    violation_id: str | None = None
    violation_index: int | None = None
    recommended_action: str | None = None
    candidate_ids: list[str] = field(default_factory=list)
    invoked_jobs: list[dict[str, str]] = field(default_factory=list)
    produced_candidate_ids: list[str] = field(default_factory=list)
    rejected_candidate_ids: list[str] = field(default_factory=list)
    recheck_run_id: str | None = None
    recheck_status: str | None = None
    recheck_skipped_reason: str | None = None
    transitions: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "validation_run_id": self.validation_run_id,
            "report_id": self.report_id,
            "violation_id": self.violation_id,
            "violation_index": self.violation_index,
            "action": self.action,
            "recommended_action": self.recommended_action,
            "state": self.state,
            "candidate_ids": list(self.candidate_ids),
            "invoked_jobs": [dict(item) for item in self.invoked_jobs],
            "produced_candidate_ids": list(self.produced_candidate_ids),
            "rejected_candidate_ids": list(self.rejected_candidate_ids),
            "recheck_run_id": self.recheck_run_id,
            "recheck_status": self.recheck_status,
            "recheck_skipped_reason": self.recheck_skipped_reason,
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
            "is_candidate_change": False,
            "is_scene_draft": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        # No Prompt, prose, evidence quotes, or violation text (1.3).
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "validation_run_id": self.validation_run_id,
            "report_id": self.report_id,
            "violation_id": self.violation_id,
            "action": self.action,
            "recommended_action": self.recommended_action,
            "state": self.state,
            "candidate_ids": list(self.candidate_ids),
            "invoked_job_ids": [item.get("id") for item in self.invoked_jobs],
            "produced_candidate_ids": list(self.produced_candidate_ids),
            "rejected_candidate_ids": list(self.rejected_candidate_ids),
            "recheck_run_id": self.recheck_run_id,
            "recheck_status": self.recheck_status,
            "recheck_skipped_reason": self.recheck_skipped_reason,
            "failure_reason": self.failure_reason,
            "is_canon": False,
            "writes_canon": False,
            "auto_approved": False,
            "is_approval": False,
        }
