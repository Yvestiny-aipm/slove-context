"""Batch schedule records (node 8.4).

Configs, runs, decisions, alerts, and daily budget counters.
Pause / cancel / fail keep the row. Scheduler never auto-approves
or submits Canon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STATUS_PLANNED = "planned"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

RUN_STATUSES = frozenset(
    {
        STATUS_PLANNED,
        STATUS_RUNNING,
        STATUS_PAUSED,
        STATUS_SUCCEEDED,
        STATUS_FAILED,
        STATUS_CANCELLED,
    }
)

KEEP_RUN_STATUSES = frozenset(
    {STATUS_PAUSED, STATUS_FAILED, STATUS_CANCELLED, STATUS_SUCCEEDED}
)

DECISION_ENQUEUED = "enqueued"
DECISION_HELD = "held"
DECISION_REJECTED = "rejected"
DECISION_SKIPPED = "skipped"

DECISION_ACTIONS = frozenset(
    {DECISION_ENQUEUED, DECISION_HELD, DECISION_REJECTED, DECISION_SKIPPED}
)

REASON_UNAPPROVED_DEPENDENCY = "unapproved_dependency"
REASON_SCENE_NOT_APPROVED = "scene_not_approved"
REASON_PROSE_STATE_DEPENDENCY = "prose_state_dependency"
REASON_CANON_WRITE_PARALLEL = "canon_write_parallel_forbidden"
REASON_SNAPSHOT_CANON_CONFLICT = "snapshot_canon_conflict"
REASON_CONCURRENCY = "concurrency_limit"
REASON_COST_CAP = "per_scene_cost_cap"
REASON_PAUSED = "project_paused"
REASON_DRY_RUN = "dry_run_no_enqueue"
REASON_ELIGIBLE = "eligible_generatable"
REASON_INDEPENDENT_PROJECT = "independent_project"
REASON_READ_CHECK = "read_check_allowed"
REASON_PLANNING = "planning_no_write_dependency"
REASON_ALREADY_ENQUEUED = "already_enqueued"

ALERT_BUDGET_EXCEEDED = "budget_exceeded"
ALERT_CONSECUTIVE_FAILURES = "consecutive_failures"
ALERT_OPEN = "open"
ALERT_ACKNOWLEDGED = "acknowledged"

ALERT_KINDS = frozenset({ALERT_BUDGET_EXCEEDED, ALERT_CONSECUTIVE_FAILURES})

KIND_PLANNING = "planning"
KIND_READ_CHECK = "read_check"
KIND_PROSE_WRITE = "prose_write"
KIND_CANON_WRITE = "canon_write"

TASK_KINDS = frozenset(
    {KIND_PLANNING, KIND_READ_CHECK, KIND_PROSE_WRITE, KIND_CANON_WRITE}
)

DEFAULT_CONCURRENCY = 2
DEFAULT_DAILY_TOKEN_BUDGET = 100_000
DEFAULT_PER_SCENE_COST_CAP = 10.0
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_ESTIMATED_TOKENS_PER_DAG = 100
DEFAULT_ESTIMATED_COST_PER_SCENE = 0.01
WORKER_JOBS_PER_DAG = 6


@dataclass
class ScheduleConfig:
    project_id: str
    concurrency: int
    daily_token_budget: int
    per_scene_cost_cap: float
    failure_threshold: int
    updated_at: str
    updated_by: str
    actor_type: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "concurrency": self.concurrency,
            "daily_token_budget": self.daily_token_budget,
            "per_scene_cost_cap": self.per_scene_cost_cap,
            "failure_threshold": self.failure_threshold,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
            "actor_type": self.actor_type,
            "writes_canon": False,
            "auto_approved": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "concurrency": self.concurrency,
            "daily_token_budget": self.daily_token_budget,
            "per_scene_cost_cap": self.per_scene_cost_cap,
            "failure_threshold": self.failure_threshold,
            "writes_canon": False,
            "auto_approved": False,
        }


@dataclass
class ScheduleDecision:
    id: str
    run_id: str
    project_id: str
    scene_id: str
    action: str
    reason_code: str
    task_kind: str
    snapshot_id: str | None
    dag_id: str | None
    message: str
    created_at: str
    parallel_with: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "action": self.action,
            "reason_code": self.reason_code,
            "task_kind": self.task_kind,
            "snapshot_id": self.snapshot_id,
            "dag_id": self.dag_id,
            "message": self.message,
            "parallel_with": list(self.parallel_with),
            "created_at": self.created_at,
            "writes_canon": False,
            "auto_approved": False,
            "kept": True,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "action": self.action,
            "reason_code": self.reason_code,
            "task_kind": self.task_kind,
            "dag_id": self.dag_id,
            "writes_canon": False,
            "auto_approved": False,
        }


@dataclass
class ScheduleAlert:
    id: str
    project_id: str
    run_id: str | None
    kind: str
    status: str
    message: str
    created_at: str
    created_by: str
    actor_type: str
    tokens_used: int = 0
    consecutive_failures: int = 0

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "kind": self.kind,
            "status": self.status,
            "message": self.message,
            "tokens_used": self.tokens_used,
            "consecutive_failures": self.consecutive_failures,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "auto_resumed": False,
            "auto_approved": False,
            "writes_canon": False,
            "kept": True,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "kind": self.kind,
            "status": self.status,
            "tokens_used": self.tokens_used,
            "consecutive_failures": self.consecutive_failures,
            "auto_resumed": False,
            "auto_approved": False,
            "writes_canon": False,
            "kept": True,
        }


@dataclass
class BudgetCounter:
    project_id: str
    day: str
    tokens_used: int
    cost_used: float
    updated_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "day": self.day,
            "tokens_used": self.tokens_used,
            "cost_used": self.cost_used,
            "updated_at": self.updated_at,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "day": self.day,
            "tokens_used": self.tokens_used,
            "cost_used": self.cost_used,
        }


@dataclass
class ScheduleRun:
    id: str
    project_id: str
    snapshot_id: str
    status: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    chapter_id: str | None = None
    dry_run: bool = False
    estimated_task_count: int = 0
    estimated_dag_count: int = 0
    enqueued_count: int = 0
    held_count: int = 0
    tokens_used: int = 0
    cost_used: float = 0.0
    consecutive_failures: int = 0
    paused_reason: str | None = None
    correlation_id: str | None = None
    dag_ids: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "dry_run": self.dry_run,
            "estimated_task_count": self.estimated_task_count,
            "estimated_dag_count": self.estimated_dag_count,
            "enqueued_count": self.enqueued_count,
            "held_count": self.held_count,
            "tokens_used": self.tokens_used,
            "cost_used": self.cost_used,
            "consecutive_failures": self.consecutive_failures,
            "paused_reason": self.paused_reason,
            "dag_ids": list(self.dag_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "writes_canon": False,
            "auto_approved": False,
            "auto_canon_commit": False,
            "called_model": False if self.dry_run else None,
            "kept": True,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "dry_run": self.dry_run,
            "estimated_task_count": self.estimated_task_count,
            "estimated_dag_count": self.estimated_dag_count,
            "enqueued_count": self.enqueued_count,
            "held_count": self.held_count,
            "tokens_used": self.tokens_used,
            "consecutive_failures": self.consecutive_failures,
            "paused_reason": self.paused_reason,
            "dag_ids": list(self.dag_ids),
            "writes_canon": False,
            "auto_approved": False,
            "auto_canon_commit": False,
        }


def default_config(
    project_id: str, *, updated_at: str, updated_by: str
) -> ScheduleConfig:
    return ScheduleConfig(
        project_id=project_id,
        concurrency=DEFAULT_CONCURRENCY,
        daily_token_budget=DEFAULT_DAILY_TOKEN_BUDGET,
        per_scene_cost_cap=DEFAULT_PER_SCENE_COST_CAP,
        failure_threshold=DEFAULT_FAILURE_THRESHOLD,
        updated_at=updated_at,
        updated_by=updated_by,
        actor_type="system",
    )
