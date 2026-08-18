"""In-process Scene Plan job and plan records (node 3.3).

A Scene Plan is per-scene intent, not Canon and not Scene Draft.
Job states: queued / running / repair / succeeded / failed.
Failed jobs keep evidence (request refs, raw_response_reference, errors).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_SCHEMA_VERSION = "0.4.0"
PROMPT_VERSION = "scene_plan.v1"

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_REPAIR = "repair"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"

JOB_STATES = frozenset({JOB_QUEUED, JOB_RUNNING, JOB_REPAIR, JOB_SUCCEEDED, JOB_FAILED})

PLAN_DRAFTED = "Drafted"

ATTEMPT_GENERATE = "generate"
ATTEMPT_REPAIR = "repair"

DEFAULT_TASK_TYPE = "scene_plan"
DEFAULT_REPAIR_TASK_TYPE = "scene_plan_repair"


@dataclass
class ScenePlan:
    id: str
    project_id: str
    scene_id: str
    scene_card_id: str
    snapshot_id: str
    job_id: str
    prompt_version: str
    status: str
    payload: dict[str, Any]
    created_at: str
    created_by: str

    def to_public_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "scene_card_id": self.scene_card_id,
            "snapshot_id": self.snapshot_id,
            "job_id": self.job_id,
            "prompt_version": self.prompt_version,
            "status": self.status,
            "is_canon": False,
            "is_scene_draft": False,
        }


@dataclass
class ScenePlanJob:
    id: str
    project_id: str
    scene_id: str
    scene_card_id: str
    snapshot_id: str
    prompt_version: str
    state: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    plan_id: str | None = None
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
            "scene_card_id": self.scene_card_id,
            "snapshot_id": self.snapshot_id,
            "prompt_version": self.prompt_version,
            "state": self.state,
            "plan_id": self.plan_id,
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
            "is_scene_draft": False,
            "writes_canon": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "scene_card_id": self.scene_card_id,
            "snapshot_id": self.snapshot_id,
            "prompt_version": self.prompt_version,
            "state": self.state,
            "plan_id": self.plan_id,
            "request_refs": [dict(item) for item in self.request_refs],
            "validation_ok": (
                None
                if self.validation_result is None
                else bool(self.validation_result.get("ok"))
            ),
            "failure_reason": self.failure_reason,
            "repair_count": self.repair_count,
            "is_canon": False,
            "is_scene_draft": False,
        }
