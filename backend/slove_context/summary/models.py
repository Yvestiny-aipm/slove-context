"""In-process Scene / Chapter summary jobs and immutable revisions (node 4.3).

A Scene Summary is a short recap of one existing Scene Draft revision.
A Chapter Summary is rolled up from existing Scene Summaries in that
chapter. Neither is Canon, Scene Draft, or a Candidate Change. Neither
auto-approves. Retry creates a new revision; old rows are not overwritten.

Job states: queued / running / succeeded / failed / cancelled.

Idempotency (see SummaryService):
- Same idempotency_key returns the existing job if it is queued, running,
  or succeeded (scoped to the same scene or chapter).
- Retry after success uses a new key (or omits the key) and creates a new
  job + new summary revision. The old revision is not overwritten.
- Cancel is terminal and does not delete the job.
- A failed or cancelled job is not reused; a later trigger (same or new
  key) creates a new job / revision attempt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCENE_PROMPT_VERSION = "scene_summary.v1"
CHAPTER_PROMPT_VERSION = "chapter_summary.v1"

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"

JOB_STATES = frozenset(
    {JOB_QUEUED, JOB_RUNNING, JOB_SUCCEEDED, JOB_FAILED, JOB_CANCELLED}
)
JOB_REUSABLE_STATES = frozenset({JOB_QUEUED, JOB_RUNNING, JOB_SUCCEEDED})
JOB_CANCELLABLE_STATES = frozenset({JOB_QUEUED, JOB_RUNNING})

KIND_SCENE = "scene"
KIND_CHAPTER = "chapter"
JOB_KINDS = frozenset({KIND_SCENE, KIND_CHAPTER})

SUMMARY_GENERATED = "Generated"
SUMMARY_SUPERSEDED = "Superseded"
SUMMARY_STATUSES = frozenset({SUMMARY_GENERATED, SUMMARY_SUPERSEDED})

DEFAULT_SCENE_TASK_TYPE = "scene_summary"
DEFAULT_CHAPTER_TASK_TYPE = "chapter_summary"


def _identity_flags() -> dict[str, Any]:
    return {
        "is_canon": False,
        "is_scene_draft": False,
        "is_candidate_change": False,
        "is_approved": False,
        "is_published": False,
        "writes_canon": False,
        "auto_approved": False,
    }


@dataclass
class SceneSummary:
    id: str
    project_id: str
    scene_id: str
    job_id: str
    revision: int
    status: str
    body: str
    content_hash: str
    source_draft_revision_id: str
    source_draft_revision: int
    source_draft_content_hash: str
    prompt_version: str
    generated_at: str
    generation_model: str
    created_at: str
    created_by: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "job_id": self.job_id,
            "revision": self.revision,
            "status": self.status,
            "body": self.body,
            "content_hash": self.content_hash,
            "source_draft_revision_id": self.source_draft_revision_id,
            "source_draft_revision": self.source_draft_revision,
            "source_draft_content_hash": self.source_draft_content_hash,
            "prompt_version": self.prompt_version,
            "generated_at": self.generated_at,
            "generation_model": self.generation_model,
            "created_at": self.created_at,
            "created_by": self.created_by,
            **_identity_flags(),
        }

    def to_audit_dict(self) -> dict[str, Any]:
        # Never include full summary or draft prose. Hash + ids only.
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "job_id": self.job_id,
            "revision": self.revision,
            "status": self.status,
            "content_hash": self.content_hash,
            "source_draft_revision_id": self.source_draft_revision_id,
            "source_draft_revision": self.source_draft_revision,
            "source_draft_content_hash": self.source_draft_content_hash,
            "prompt_version": self.prompt_version,
            "generated_at": self.generated_at,
            "generation_model": self.generation_model,
            **_identity_flags(),
        }


@dataclass
class ChapterSummary:
    id: str
    project_id: str
    chapter_id: str
    job_id: str
    revision: int
    status: str
    body: str
    content_hash: str
    source_scene_summary_revision_ids: list[str]
    prompt_version: str
    generated_at: str
    generation_model: str
    created_at: str
    created_by: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "job_id": self.job_id,
            "revision": self.revision,
            "status": self.status,
            "body": self.body,
            "content_hash": self.content_hash,
            "source_scene_summary_revision_ids": list(
                self.source_scene_summary_revision_ids
            ),
            "prompt_version": self.prompt_version,
            "generated_at": self.generated_at,
            "generation_model": self.generation_model,
            "created_at": self.created_at,
            "created_by": self.created_by,
            **_identity_flags(),
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "job_id": self.job_id,
            "revision": self.revision,
            "status": self.status,
            "content_hash": self.content_hash,
            "source_scene_summary_revision_ids": list(
                self.source_scene_summary_revision_ids
            ),
            "prompt_version": self.prompt_version,
            "generated_at": self.generated_at,
            "generation_model": self.generation_model,
            **_identity_flags(),
        }


@dataclass
class SummaryJob:
    id: str
    project_id: str
    kind: str
    prompt_version: str
    state: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    scene_id: str | None = None
    chapter_id: str | None = None
    draft_revision_id: str | None = None
    source_draft_content_hash: str | None = None
    source_scene_summary_revision_ids: list[str] = field(default_factory=list)
    idempotency_key: str | None = None
    summary_id: str | None = None
    summary_revision: int | None = None
    request_refs: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] | None = None
    transitions: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "kind": self.kind,
            "scene_id": self.scene_id,
            "chapter_id": self.chapter_id,
            "draft_revision_id": self.draft_revision_id,
            "source_draft_content_hash": self.source_draft_content_hash,
            "source_scene_summary_revision_ids": list(
                self.source_scene_summary_revision_ids
            ),
            "prompt_version": self.prompt_version,
            "state": self.state,
            "idempotency_key": self.idempotency_key,
            "summary_id": self.summary_id,
            "summary_revision": self.summary_revision,
            "request_refs": [dict(item) for item in self.request_refs],
            "evidence": dict(self.evidence) if self.evidence is not None else None,
            "transitions": [dict(item) for item in self.transitions],
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            **_identity_flags(),
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "kind": self.kind,
            "scene_id": self.scene_id,
            "chapter_id": self.chapter_id,
            "draft_revision_id": self.draft_revision_id,
            "source_draft_content_hash": self.source_draft_content_hash,
            "source_scene_summary_revision_ids": list(
                self.source_scene_summary_revision_ids
            ),
            "prompt_version": self.prompt_version,
            "state": self.state,
            "idempotency_key": self.idempotency_key,
            "summary_id": self.summary_id,
            "summary_revision": self.summary_revision,
            "request_refs": [dict(item) for item in self.request_refs],
            "failure_reason": self.failure_reason,
            **_identity_flags(),
        }
