"""In-process Scene Draft job and immutable draft records (node 3.4).

A Scene Draft is per-scene prose. It is not Canon and cannot auto-approve
or publish. Body / hash / model / Prompt version are immutable on a
revision; only status may move Generated → Superseded when a newer
revision is persisted.

Job states: queued / running / succeeded / failed / cancelled.

Idempotency (see SceneDraftService.trigger_job):
- Same idempotency_key returns the existing job if it is queued, running,
  or succeeded.
- Retry after success uses a new key (or omits the key) and creates a new
  job + new draft revision. The old revision is not overwritten.
- Cancel is terminal and does not delete the job.
- A failed or cancelled job is not reused; a later trigger (same or new
  key) creates a new job / revision attempt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROMPT_VERSION = "scene_draft.v1"

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

# 0.3 Scene Draft subset. Node 4.1 may move Generated → Extracted
# (status only). Published / approved remain out of scope.
DRAFT_GENERATED = "Generated"
DRAFT_EXTRACTED = "Extracted"
DRAFT_FAILED = "Failed"
DRAFT_CANCELLED = "Cancelled"
DRAFT_SUPERSEDED = "Superseded"

DRAFT_STATUSES = frozenset(
    {
        DRAFT_GENERATED,
        DRAFT_EXTRACTED,
        DRAFT_FAILED,
        DRAFT_CANCELLED,
        DRAFT_SUPERSEDED,
    }
)
EXTRACTABLE_DRAFT_STATUSES = frozenset({DRAFT_GENERATED, DRAFT_EXTRACTED})

DEFAULT_TASK_TYPE = "scene_draft"


@dataclass
class SceneDraft:
    id: str
    project_id: str
    scene_id: str
    job_id: str
    revision: int
    status: str
    body: str
    content_hash: str
    character_count: int
    word_count_estimate: int
    generation_model: str
    prompt_version: str
    generated_at: str
    scene_card_id: str
    plan_id: str
    snapshot_id: str
    context_pack_id: str
    created_at: str
    created_by: str
    # Node 7.1 reference only. Generate job (3.4) does not set these.
    style_guide_revision_id: str | None = None
    style_sample_ids: list[str] = field(default_factory=list)

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
            "character_count": self.character_count,
            "word_count_estimate": self.word_count_estimate,
            "generation_model": self.generation_model,
            "prompt_version": self.prompt_version,
            "generated_at": self.generated_at,
            "input_versions": {
                "scene_id": self.scene_id,
                "scene_card_id": self.scene_card_id,
                "plan_id": self.plan_id,
                "snapshot_id": self.snapshot_id,
                "context_pack_id": self.context_pack_id,
                "style_guide_revision_id": self.style_guide_revision_id,
            },
            "style_guide_revision_id": self.style_guide_revision_id,
            "style_sample_ids": list(self.style_sample_ids),
            "is_canon": False,
            "is_approved": False,
            "is_published": False,
            "writes_canon": False,
            "auto_approved": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        # Never include full prose. Hash + ids only (1.3 redaction).
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "job_id": self.job_id,
            "revision": self.revision,
            "status": self.status,
            "content_hash": self.content_hash,
            "character_count": self.character_count,
            "word_count_estimate": self.word_count_estimate,
            "generation_model": self.generation_model,
            "prompt_version": self.prompt_version,
            "generated_at": self.generated_at,
            "scene_card_id": self.scene_card_id,
            "plan_id": self.plan_id,
            "snapshot_id": self.snapshot_id,
            "context_pack_id": self.context_pack_id,
            "style_guide_revision_id": self.style_guide_revision_id,
            "style_sample_ids": list(self.style_sample_ids),
            "is_canon": False,
            "is_approved": False,
            "is_published": False,
            "writes_canon": False,
        }


@dataclass
class SceneDraftJob:
    id: str
    project_id: str
    scene_id: str
    scene_card_id: str
    plan_id: str
    snapshot_id: str
    context_pack_id: str
    prompt_version: str
    state: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    idempotency_key: str | None = None
    draft_id: str | None = None
    draft_revision: int | None = None
    request_refs: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] | None = None
    transitions: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "scene_card_id": self.scene_card_id,
            "plan_id": self.plan_id,
            "snapshot_id": self.snapshot_id,
            "context_pack_id": self.context_pack_id,
            "prompt_version": self.prompt_version,
            "state": self.state,
            "idempotency_key": self.idempotency_key,
            "draft_id": self.draft_id,
            "draft_revision": self.draft_revision,
            "request_refs": [dict(item) for item in self.request_refs],
            "evidence": dict(self.evidence) if self.evidence is not None else None,
            "transitions": [dict(item) for item in self.transitions],
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "is_canon": False,
            "is_approved": False,
            "is_published": False,
            "writes_canon": False,
            "auto_approved": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "scene_card_id": self.scene_card_id,
            "plan_id": self.plan_id,
            "snapshot_id": self.snapshot_id,
            "context_pack_id": self.context_pack_id,
            "prompt_version": self.prompt_version,
            "state": self.state,
            "idempotency_key": self.idempotency_key,
            "draft_id": self.draft_id,
            "draft_revision": self.draft_revision,
            "request_refs": [dict(item) for item in self.request_refs],
            "failure_reason": self.failure_reason,
            "is_canon": False,
            "writes_canon": False,
        }
