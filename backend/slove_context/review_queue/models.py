"""In-process Review Queue item and decision records (node 7.3).

Queue statuses: Opened / Escalated / Approved / Rejected /
RevisionRequested / Failed / Cancelled.

Opened and Escalated remain decidable. Failure and cancel keep the
row. No decision writes Canon. Style-report approve is not Canon
approval and does not block Canon submit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SUBJECT_SCENE_PLAN = "scene_plan"
SUBJECT_SCENE_DRAFT = "scene_draft"
SUBJECT_CANDIDATE_CHANGE = "candidate_change"
SUBJECT_VALIDATION_REPORT = "validation_report"
SUBJECT_REPAIR_TASK = "repair_task"
SUBJECT_STYLE_REPORT = "style_report"

SUBJECT_TYPES = frozenset(
    {
        SUBJECT_SCENE_PLAN,
        SUBJECT_SCENE_DRAFT,
        SUBJECT_CANDIDATE_CHANGE,
        SUBJECT_VALIDATION_REPORT,
        SUBJECT_REPAIR_TASK,
        SUBJECT_STYLE_REPORT,
    }
)

_SUBJECT_ALIASES = {
    "sceneplan": SUBJECT_SCENE_PLAN,
    "plan": SUBJECT_SCENE_PLAN,
    "scenedraft": SUBJECT_SCENE_DRAFT,
    "draft": SUBJECT_SCENE_DRAFT,
    "candidate": SUBJECT_CANDIDATE_CHANGE,
    "candidatechange": SUBJECT_CANDIDATE_CHANGE,
    "candidate_changes": SUBJECT_CANDIDATE_CHANGE,
    "validation": SUBJECT_VALIDATION_REPORT,
    "validationreport": SUBJECT_VALIDATION_REPORT,
    "validation_run_report": SUBJECT_VALIDATION_REPORT,
    "repair": SUBJECT_REPAIR_TASK,
    "repairtask": SUBJECT_REPAIR_TASK,
    "style": SUBJECT_STYLE_REPORT,
    "stylereport": SUBJECT_STYLE_REPORT,
    "style_validation": SUBJECT_STYLE_REPORT,
    "style_validation_report": SUBJECT_STYLE_REPORT,
}

ACTION_APPROVE = "approve"
ACTION_REJECT = "reject"
ACTION_REQUEST_REVISION = "request_revision"
ACTION_ESCALATE = "escalate"
ACTION_CANCEL = "cancel"

DECISION_ACTIONS = frozenset(
    {ACTION_APPROVE, ACTION_REJECT, ACTION_REQUEST_REVISION, ACTION_ESCALATE}
)

STATUS_OPENED = "Opened"
STATUS_ESCALATED = "Escalated"
STATUS_APPROVED = "Approved"
STATUS_REJECTED = "Rejected"
STATUS_REVISION_REQUESTED = "RevisionRequested"
STATUS_FAILED = "Failed"
STATUS_CANCELLED = "Cancelled"

QUEUE_STATES = frozenset(
    {
        STATUS_OPENED,
        STATUS_ESCALATED,
        STATUS_APPROVED,
        STATUS_REJECTED,
        STATUS_REVISION_REQUESTED,
        STATUS_FAILED,
        STATUS_CANCELLED,
    }
)

DECIDABLE_STATES = frozenset({STATUS_OPENED, STATUS_ESCALATED})
CANCEL_FROM_STATES = frozenset({STATUS_OPENED, STATUS_ESCALATED})
OPEN_STATES = frozenset({STATUS_OPENED, STATUS_ESCALATED})

ACTION_TO_STATUS = {
    ACTION_APPROVE: STATUS_APPROVED,
    ACTION_REJECT: STATUS_REJECTED,
    ACTION_REQUEST_REVISION: STATUS_REVISION_REQUESTED,
    ACTION_ESCALATE: STATUS_ESCALATED,
    ACTION_CANCEL: STATUS_CANCELLED,
}

CANON_SUBMIT_PATH_TEMPLATE = (
    "POST /projects/{project_id}/candidate-changes/{subject_id}/submit"
)


def normalize_subject_type(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    if stripped in SUBJECT_TYPES:
        return stripped
    compact = stripped.lower().replace("-", "_").replace(" ", "_")
    if compact in SUBJECT_TYPES:
        return compact
    collapsed = compact.replace("_", "")
    return _SUBJECT_ALIASES.get(collapsed) or _SUBJECT_ALIASES.get(compact)


def canon_submit_path(project_id: str, subject_id: str) -> str:
    return CANON_SUBMIT_PATH_TEMPLATE.format(
        project_id=project_id, subject_id=subject_id
    )


@dataclass
class ReviewDecision:
    id: str
    item_id: str
    project_id: str
    action: str
    reason_code: str
    created_at: str
    actor_type: str
    actor_id: str | None
    comment: str | None = None
    writes_canon: bool = False
    is_canon_approval: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "item_id": self.item_id,
            "project_id": self.project_id,
            "action": self.action,
            "reason_code": self.reason_code,
            "comment": self.comment,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "created_at": self.created_at,
            "writes_canon": False,
            "is_canon_approval": False,
            "auto_approved": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "item_id": self.item_id,
            "project_id": self.project_id,
            "action": self.action,
            "reason_code": self.reason_code,
            "has_comment": bool(self.comment),
            "actor_type": self.actor_type,
            "writes_canon": False,
            "is_canon_approval": False,
            "auto_approved": False,
        }


@dataclass
class ReviewQueueItem:
    id: str
    project_id: str
    subject_type: str
    subject_id: str
    status: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    is_blocker: bool = False
    chapter_id: str | None = None
    scene_id: str | None = None
    context_pack_id: str | None = None
    input_versions: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    diff: dict[str, Any] = field(default_factory=dict)
    decision_ids: list[str] = field(default_factory=list)
    failure_reason: str | None = None

    def to_public_dict(
        self, decisions: list[ReviewDecision] | None = None
    ) -> dict[str, Any]:
        history = [
            item.to_public_dict()
            for item in (decisions or [])
            if item.item_id == self.id
        ]
        is_candidate = self.subject_type == SUBJECT_CANDIDATE_CHANGE
        is_style = self.subject_type == SUBJECT_STYLE_REPORT
        return {
            "id": self.id,
            "project_id": self.project_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "status": self.status,
            "is_blocker": self.is_blocker,
            "chapter_id": self.chapter_id,
            "scene_id": self.scene_id,
            "input_versions": dict(self.input_versions),
            "context_pack_id": self.context_pack_id,
            "evidence_refs": [dict(item) for item in self.evidence_refs],
            "diff": dict(self.diff),
            "decision_history": history,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "writes_canon": False,
            "auto_approved": False,
            "is_canon": False,
            "is_canon_approval": False,
            "is_approval": False,
            "blocks_canon_submit": False,
            "style_report_approve_is_canon_approve": False,
            "canon_commit_required": is_candidate,
            "canon_commit_path": (
                canon_submit_path(self.project_id, self.subject_id)
                if is_candidate
                else None
            ),
            "subject_is_style_report": is_style,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "status": self.status,
            "is_blocker": self.is_blocker,
            "chapter_id": self.chapter_id,
            "scene_id": self.scene_id,
            "context_pack_id": self.context_pack_id,
            "input_version_keys": sorted(self.input_versions.keys()),
            "evidence_ref_count": len(self.evidence_refs),
            "diff_kind": self.diff.get("kind"),
            "decision_count": len(self.decision_ids),
            "failure_reason": self.failure_reason,
            "writes_canon": False,
            "auto_approved": False,
            "is_canon": False,
            "is_canon_approval": False,
            "blocks_canon_submit": False,
        }


@dataclass(frozen=True)
class SubjectSnapshot:
    subject_type: str
    subject_id: str
    scene_id: str | None
    chapter_id: str | None
    context_pack_id: str | None
    input_versions: dict[str, Any]
    evidence_refs: list[dict[str, Any]]
    diff: dict[str, Any]
    is_blocker: bool
    subject_status: str | None
