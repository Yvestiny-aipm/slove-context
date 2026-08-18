"""In-process job queue records (node 8.1).

Statuses: queued / running / succeeded / failed / cancelled / dead_letter.
Write jobs on the same scene_id serialize via a scene lock.
payload_reference points at stored input refs, not ephemeral bodies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

JOB_TYPE_PLAN = "plan"
JOB_TYPE_DRAFT = "draft"
JOB_TYPE_EXTRACT = "extract"
JOB_TYPE_VALIDATE = "validate"
JOB_TYPE_REPAIR = "repair"
JOB_TYPE_SUMMARIZE = "summarize"
JOB_TYPE_CONTEXT_PACK = "context_pack"

JOB_TYPES = frozenset(
    {
        JOB_TYPE_PLAN,
        JOB_TYPE_DRAFT,
        JOB_TYPE_EXTRACT,
        JOB_TYPE_VALIDATE,
        JOB_TYPE_REPAIR,
        JOB_TYPE_SUMMARIZE,
        JOB_TYPE_CONTEXT_PACK,
    }
)

# Mutually exclusive writers for one scene. Read-only-ish types
# (validate / summarize / context_pack) are more lenient.
WRITE_JOB_TYPES = frozenset(
    {
        JOB_TYPE_PLAN,
        JOB_TYPE_DRAFT,
        JOB_TYPE_EXTRACT,
        JOB_TYPE_REPAIR,
    }
)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_DEAD_LETTER = "dead_letter"

JOB_STATUSES = frozenset(
    {
        STATUS_QUEUED,
        STATUS_RUNNING,
        STATUS_SUCCEEDED,
        STATUS_FAILED,
        STATUS_CANCELLED,
        STATUS_DEAD_LETTER,
    }
)

ACTIVE_STATUSES = frozenset({STATUS_QUEUED, STATUS_RUNNING, STATUS_SUCCEEDED})
TERMINAL_KEEP_STATUSES = frozenset(
    {STATUS_FAILED, STATUS_CANCELLED, STATUS_DEAD_LETTER, STATUS_SUCCEEDED}
)
RERUNNABLE_STATUSES = frozenset({STATUS_FAILED, STATUS_DEAD_LETTER})
CANCELLABLE_STATUSES = frozenset({STATUS_QUEUED, STATUS_RUNNING})

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_BASE_BACKOFF_S = 1.0

_JOB_TYPE_ALIASES = {
    "plan": JOB_TYPE_PLAN,
    "scene_plan": JOB_TYPE_PLAN,
    "draft": JOB_TYPE_DRAFT,
    "scene_draft": JOB_TYPE_DRAFT,
    "extract": JOB_TYPE_EXTRACT,
    "candidate_extract": JOB_TYPE_EXTRACT,
    "validate": JOB_TYPE_VALIDATE,
    "validation": JOB_TYPE_VALIDATE,
    "repair": JOB_TYPE_REPAIR,
    "summarize": JOB_TYPE_SUMMARIZE,
    "summary": JOB_TYPE_SUMMARIZE,
    "context_pack": JOB_TYPE_CONTEXT_PACK,
    "context-pack": JOB_TYPE_CONTEXT_PACK,
}


def normalize_job_type(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    if stripped in JOB_TYPES:
        return stripped
    lowered = stripped.lower().replace("-", "_").replace(" ", "_")
    return _JOB_TYPE_ALIASES.get(lowered)


def is_write_job(job_type: str) -> bool:
    return job_type in WRITE_JOB_TYPES


@dataclass
class JobPayload:
    """Stored input references. Replay always reloads this row."""

    id: str
    project_id: str
    job_type: str
    inputs: dict[str, Any]
    created_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "job_type": self.job_type,
            "inputs": dict(self.inputs),
            "created_at": self.created_at,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "job_type": self.job_type,
            "input_keys": sorted(self.inputs.keys()),
            "input_refs": {
                key: value
                for key, value in self.inputs.items()
                if isinstance(value, str | int | float | bool) or value is None
            },
        }


@dataclass
class JobLock:
    scene_id: str
    job_id: str
    locked_at: str
    expires_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "job_id": self.job_id,
            "locked_at": self.locked_at,
            "expires_at": self.expires_at,
        }


@dataclass
class Job:
    id: str
    project_id: str
    job_type: str
    payload_reference: str
    status: str
    attempt_count: int
    max_attempts: int
    scheduled_at: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    correlation_id: str
    scene_id: str | None = None
    idempotency_key: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    result_reference: dict[str, Any] | None = None
    dispatched_resource_type: str | None = None
    dispatched_resource_id: str | None = None
    rerun_of_job_id: str | None = None
    transitions: list[dict[str, Any]] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "job_type": self.job_type,
            "payload_reference": self.payload_reference,
            "status": self.status,
            "scene_id": self.scene_id,
            "idempotency_key": self.idempotency_key,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "scheduled_at": self.scheduled_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "correlation_id": self.correlation_id,
            "result_reference": (
                dict(self.result_reference)
                if self.result_reference is not None
                else None
            ),
            "dispatched_resource_type": self.dispatched_resource_type,
            "dispatched_resource_id": self.dispatched_resource_id,
            "rerun_of_job_id": self.rerun_of_job_id,
            "transitions": [dict(item) for item in self.transitions],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "writes_canon": False,
            "is_canon": False,
            "auto_approved": False,
            "is_write_job": is_write_job(self.job_type),
            "kept": True,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "job_type": self.job_type,
            "payload_reference": self.payload_reference,
            "status": self.status,
            "scene_id": self.scene_id,
            "idempotency_key": self.idempotency_key,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "error_code": self.error_code,
            "correlation_id": self.correlation_id,
            "dispatched_resource_type": self.dispatched_resource_type,
            "dispatched_resource_id": self.dispatched_resource_id,
            "rerun_of_job_id": self.rerun_of_job_id,
            "writes_canon": False,
            "is_canon": False,
            "auto_approved": False,
        }
