"""In-process Candidate Change extract job and candidate records (node 4.1).

A Candidate Change is a proposal extracted from one Scene Draft. It is
not Canon and cannot auto-approve. Initial status is Extracted only.

Extract batches are append-only: a failed or cancelled job is kept; a
later trigger creates a new job and a new batch. Prior candidates are
not overwritten or deleted.

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

    def to_public_dict(self) -> dict[str, Any]:
        public = dict(self.payload)
        public["extract_batch"] = self.extract_batch
        public["draft_id"] = self.draft_id
        public["job_id"] = self.job_id
        public["is_canon"] = False
        public["is_canon_fact"] = False
        public["is_approved"] = False
        public["auto_approved"] = False
        public["writes_canon"] = False
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
            "is_approved": False,
            "writes_canon": False,
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
