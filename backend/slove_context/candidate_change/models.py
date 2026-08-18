"""In-process Candidate Change extract job and candidate records.

Node 4.1: extraction. A Candidate Change is a proposal extracted from
one Scene Draft. It is not Canon and cannot auto-approve. Initial
status is Extracted only.

Node 4.2: human approve / reject / submit. Approve records a verdict
only and does not write Canon. Submit (Approved → Submitted) is the
human commit path that creates or supersedes a Canon Fact. The
candidate remains a candidate; it never becomes a Canon Fact.

Extract batches are append-only: a failed or cancelled job is kept; a
later trigger creates a new job and a new batch. Prior candidates are
not overwritten or deleted. Failure / cancel / reject keep records.

Job states: queued / running / repair / succeeded / failed / cancelled.

Idempotency (see CandidateChangeService.trigger_job):
- Same idempotency_key returns the existing job if it is queued, running,
  or succeeded.
- Cancel is terminal and does not delete the job.
- A failed or cancelled job is not reused; a later trigger (same or new
  key) creates a new job / extract batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_SCHEMA_VERSION = "0.4.0"
PROMPT_VERSION = "extract_candidates.v1"

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_REPAIR = "repair"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"

JOB_STATES = frozenset(
    {
        JOB_QUEUED,
        JOB_RUNNING,
        JOB_REPAIR,
        JOB_SUCCEEDED,
        JOB_FAILED,
        JOB_CANCELLED,
    }
)
JOB_REUSABLE_STATES = frozenset({JOB_QUEUED, JOB_RUNNING, JOB_SUCCEEDED})
JOB_CANCELLABLE_STATES = frozenset({JOB_QUEUED, JOB_RUNNING})

CANDIDATE_EXTRACTED = "Extracted"
CANDIDATE_VALIDATING = "Validating"
CANDIDATE_FAILED_VALIDATION = "FailedValidation"
CANDIDATE_AWAITING_VERDICT = "AwaitingVerdict"
CANDIDATE_APPROVED = "Approved"
CANDIDATE_REJECTED = "Rejected"
CANDIDATE_SUBMITTED = "Submitted"
CANDIDATE_FAILED = "Failed"
CANDIDATE_CANCELLED = "Cancelled"
CANDIDATE_REWORK = "Rework"

CANDIDATE_STATUSES = frozenset(
    {
        CANDIDATE_EXTRACTED,
        CANDIDATE_VALIDATING,
        CANDIDATE_FAILED_VALIDATION,
        CANDIDATE_AWAITING_VERDICT,
        CANDIDATE_APPROVED,
        CANDIDATE_REJECTED,
        CANDIDATE_SUBMITTED,
        CANDIDATE_FAILED,
        CANDIDATE_CANCELLED,
        CANDIDATE_REWORK,
    }
)

# Approve is allowed only from AwaitingVerdict (0.3).
APPROVE_FROM = frozenset({CANDIDATE_AWAITING_VERDICT})
# Reject is allowed from AwaitingVerdict or Approved (before submit).
REJECT_FROM = frozenset({CANDIDATE_AWAITING_VERDICT, CANDIDATE_APPROVED})
# Submit is allowed only from Approved. Duplicate submit is rejected
# (409); it is not idempotent and must not double-write Canon.
SUBMIT_FROM = frozenset({CANDIDATE_APPROVED})

# Test helper only: skip Validate (5.x). Never an approve or submit path.
SEEDABLE_STATUSES = frozenset(
    {
        CANDIDATE_AWAITING_VERDICT,
        CANDIDATE_VALIDATING,
        CANDIDATE_FAILED_VALIDATION,
        CANDIDATE_FAILED,
        CANDIDATE_REWORK,
        CANDIDATE_CANCELLED,
    }
)

DECISION_APPROVE = "Approve"
DECISION_REJECT = "Reject"
DECISION_VALUES = frozenset({DECISION_APPROVE, DECISION_REJECT})

APPROVED_STATUSES = frozenset({CANDIDATE_APPROVED, CANDIDATE_SUBMITTED})

ATTEMPT_GENERATE = "generate"
ATTEMPT_REPAIR = "repair"

DEFAULT_TASK_TYPE = "extract_candidates"
DEFAULT_REPAIR_TASK_TYPE = "extract_candidates_repair"


@dataclass
class CandidateChange:
    id: str
    project_id: str
    scene_id: str
    draft_id: str
    job_id: str
    extract_batch: int
    schema_version: str
    subject: str
    predicate: str
    object: str
    value: str
    effective_story_time: str
    source_scene_id: str
    evidence_quote: str
    confidence: float
    status: str
    created_at: str
    created_by: str
    payload: dict[str, Any]
    approval_decision: dict[str, Any] | None = None
    submitted_canon_fact_id: str | None = None
    superseded_canon_fact_id: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        public = dict(self.payload)
        public["extract_batch"] = self.extract_batch
        public["draft_id"] = self.draft_id
        public["job_id"] = self.job_id
        public["status"] = self.status
        public["is_canon"] = False
        public["is_canon_fact"] = False
        public["is_approved"] = self.status in APPROVED_STATUSES
        public["auto_approved"] = False
        public["writes_canon"] = False
        public["approval_decision"] = (
            dict(self.approval_decision) if self.approval_decision is not None else None
        )
        public["submitted_canon_fact_id"] = self.submitted_canon_fact_id
        public["superseded_canon_fact_id"] = self.superseded_canon_fact_id
        return public

    def to_audit_dict(self) -> dict[str, Any]:
        # Never include evidence_quote / draft prose (1.3 redaction).
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "draft_id": self.draft_id,
            "job_id": self.job_id,
            "extract_batch": self.extract_batch,
            "schema_version": self.schema_version,
            "subject": self.subject,
            "predicate": self.predicate,
            "source_scene_id": self.source_scene_id,
            "has_evidence_quote": bool(self.evidence_quote),
            "confidence": self.confidence,
            "status": self.status,
            "is_canon": False,
            "is_canon_fact": False,
            "is_approved": self.status in APPROVED_STATUSES,
            "writes_canon": False,
            "approval_decision_id": (
                self.approval_decision.get("id")
                if isinstance(self.approval_decision, dict)
                else None
            ),
            "submitted_canon_fact_id": self.submitted_canon_fact_id,
            "superseded_canon_fact_id": self.superseded_canon_fact_id,
        }


@dataclass
class ExtractJob:
    id: str
    project_id: str
    scene_id: str
    draft_id: str
    draft_revision: int
    prompt_version: str
    state: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    idempotency_key: str | None = None
    extract_batch: int | None = None
    candidate_ids: list[str] = field(default_factory=list)
    request_refs: list[dict[str, Any]] = field(default_factory=list)
    validation_result: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    transitions: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str | None = None
    repair_count: int = 0

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "draft_id": self.draft_id,
            "draft_revision": self.draft_revision,
            "prompt_version": self.prompt_version,
            "state": self.state,
            "idempotency_key": self.idempotency_key,
            "extract_batch": self.extract_batch,
            "candidate_ids": list(self.candidate_ids),
            "request_refs": [dict(item) for item in self.request_refs],
            "validation_result": (
                dict(self.validation_result)
                if self.validation_result is not None
                else None
            ),
            "evidence": dict(self.evidence) if self.evidence is not None else None,
            "transitions": [dict(item) for item in self.transitions],
            "failure_reason": self.failure_reason,
            "repair_count": self.repair_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "is_canon": False,
            "is_approved": False,
            "writes_canon": False,
            "auto_approved": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "draft_id": self.draft_id,
            "draft_revision": self.draft_revision,
            "prompt_version": self.prompt_version,
            "state": self.state,
            "idempotency_key": self.idempotency_key,
            "extract_batch": self.extract_batch,
            "candidate_ids": list(self.candidate_ids),
            "request_refs": [dict(item) for item in self.request_refs],
            "validation_ok": (
                None
                if self.validation_result is None
                else bool(self.validation_result.get("ok"))
            ),
            "failure_reason": self.failure_reason,
            "repair_count": self.repair_count,
            "is_canon": False,
            "writes_canon": False,
        }
