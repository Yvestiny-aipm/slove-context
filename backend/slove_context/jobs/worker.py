"""In-process Worker (node 8.1).

Dispatcher only. Claims queued jobs, serializes write jobs on a
scene lock, and calls existing services by job_type. Timeout / backoff
/ max retries / dead-letter live here. Tests call tick() / run_once()
/ claim_one(). No background daemon. No Canon write. No approve.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from slove_context.audit import AuditWriter
from slove_context.candidate_change.service import CandidateChangeServiceError
from slove_context.context_pack.service import ContextPackServiceError
from slove_context.jobs.deps import ExistingServices
from slove_context.jobs.models import (
    DEFAULT_BASE_BACKOFF_S,
    DEFAULT_TIMEOUT_S,
    JOB_TYPE_CONTEXT_PACK,
    JOB_TYPE_DRAFT,
    JOB_TYPE_EXTRACT,
    JOB_TYPE_PLAN,
    JOB_TYPE_REPAIR,
    JOB_TYPE_SUMMARIZE,
    JOB_TYPE_VALIDATE,
    STATUS_DEAD_LETTER,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    Job,
    JobLock,
    is_write_job,
)
from slove_context.jobs.repository import JobRepository
from slove_context.logging import get_request_id
from slove_context.repair.models import ACTION_HUMAN_REJECT
from slove_context.repair.service import RepairServiceError
from slove_context.scene_draft.service import SceneDraftServiceError
from slove_context.scene_plan.service import ScenePlanServiceError
from slove_context.story.actors import SYSTEM, Actor
from slove_context.summary.service import SummaryServiceError
from slove_context.validation.service import ValidationServiceError

DispatchFn = Callable[[Job, dict[str, Any]], dict[str, Any]]
NowFn = Callable[[], datetime]

_DISPATCH_ERRORS = (
    ScenePlanServiceError,
    SceneDraftServiceError,
    CandidateChangeServiceError,
    ValidationServiceError,
    RepairServiceError,
    SummaryServiceError,
    ContextPackServiceError,
)


class Worker:
    """Optional in-process worker. Tests drive it with tick() / run_once()."""

    def __init__(
        self,
        *,
        job_repository: JobRepository,
        audit_writer: AuditWriter,
        services: ExistingServices | None = None,
        dispatch_fn: DispatchFn | None = None,
        now_fn: NowFn | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        base_backoff_s: float = DEFAULT_BASE_BACKOFF_S,
    ) -> None:
        self._repo = job_repository
        self._audit = audit_writer
        self._services = services
        self._dispatch_fn = dispatch_fn
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._timeout_s = timeout_s
        self._base_backoff_s = base_backoff_s
        self.last_dispatched_inputs: dict[str, dict[str, Any]] = {}

    def tick(self) -> Job | None:
        return self.run_once()

    def run_once(self) -> Job | None:
        job = self.claim_one()
        if job is None:
            return None
        self.execute(job)
        return job

    def claim_one(self) -> Job | None:
        """Move one due queued job to running. Write jobs take a scene lock."""
        self.reclaim_timed_out()
        now = self._now()
        now_text = _format_dt(now)
        for job in self._due_queued(now_text):
            if is_write_job(job.job_type):
                if not job.scene_id:
                    self._fail_terminal(
                        job,
                        error_code="scene_id_required",
                        error_detail="write_job_missing_scene_id",
                        dead_letter=True,
                    )
                    continue
                if not self._try_lock(job, now=now):
                    continue
            before = job.to_audit_dict()
            job.attempt_count += 1
            job.status = STATUS_RUNNING
            job.started_at = now_text
            job.finished_at = None
            job.updated_at = now_text
            job.transitions.append(
                {"from": STATUS_QUEUED, "to": STATUS_RUNNING, "at": now_text}
            )
            self._repo.save_job(job)
            self._audit_transition(job, before=before, action="job.claim")
            return job
        return None

    def execute(self, job: Job) -> Job:
        payload = self._repo.get_payload(job.payload_reference)
        if payload is None:
            self._retry_or_dead_letter(
                job,
                error_code="payload_reference_missing",
                error_detail="replay_requires_stored_payload_reference",
            )
            self._release_lock(job)
            return job
        inputs = dict(payload.inputs)
        self.last_dispatched_inputs[job.id] = dict(inputs)
        try:
            result = self._dispatch(job, inputs)
        except WorkerDispatchError as exc:
            self._retry_or_dead_letter(
                job, error_code=exc.error_code, error_detail=exc.error_detail
            )
            self._release_lock(job)
            return job
        except _DISPATCH_ERRORS as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc)}
            self._retry_or_dead_letter(
                job,
                error_code=str(detail.get("error") or type(exc).__name__),
                error_detail=_short_detail(detail),
            )
            self._release_lock(job)
            return job
        before = job.to_audit_dict()
        now_text = _format_dt(self._now())
        job.status = STATUS_SUCCEEDED
        job.finished_at = now_text
        job.updated_at = now_text
        job.error_code = None
        job.error_detail = None
        job.result_reference = {
            key: value
            for key, value in result.items()
            if isinstance(value, str | int | float | bool | list | dict)
            or value is None
        }
        job.dispatched_resource_type = (
            str(result.get("resource_type")) if result.get("resource_type") else None
        )
        resource_id = result.get("resource_id")
        job.dispatched_resource_id = str(resource_id) if resource_id else None
        job.transitions.append(
            {"from": STATUS_RUNNING, "to": STATUS_SUCCEEDED, "at": now_text}
        )
        self._repo.save_job(job)
        self._audit_transition(job, before=before, action="job.succeed")
        self._release_lock(job)
        return job

    def reclaim_timed_out(self) -> list[Job]:
        reclaimed: list[Job] = []
        now = self._now()
        for job in self._repo.list_by_status(STATUS_RUNNING):
            if job.started_at is None:
                continue
            started = _parse_dt(job.started_at)
            if now < started + timedelta(seconds=self._timeout_s):
                continue
            self._retry_or_dead_letter(
                job,
                error_code="timeout",
                error_detail="job_execution_timed_out",
            )
            self._release_lock(job)
            reclaimed.append(job)
        return reclaimed

    def _due_queued(self, now_text: str) -> list[Job]:
        items = [
            job
            for job in self._repo.list_by_status(STATUS_QUEUED)
            if job.scheduled_at <= now_text
        ]
        items.sort(key=lambda job: (job.scheduled_at, job.id))
        return items

    def _dispatch(self, job: Job, inputs: dict[str, Any]) -> dict[str, Any]:
        if self._dispatch_fn is not None:
            return self._dispatch_fn(job, inputs)
        if self._services is None:
            raise WorkerDispatchError(
                "worker_not_wired",
                "Worker has no existing services and no dispatch_fn.",
            )
        return dispatch_existing(self._services, job, inputs)

    def _try_lock(self, job: Job, *, now: datetime) -> bool:
        assert job.scene_id is not None
        existing = self._repo.get_lock(job.scene_id)
        now_text = _format_dt(now)
        if existing is not None:
            if existing.job_id == job.id:
                return True
            if _parse_dt(existing.expires_at) > now:
                return False
        expires = now + timedelta(seconds=self._timeout_s)
        self._repo.save_lock(
            JobLock(
                scene_id=job.scene_id,
                job_id=job.id,
                locked_at=now_text,
                expires_at=_format_dt(expires),
            )
        )
        return True

    def _release_lock(self, job: Job) -> None:
        if job.scene_id:
            self._repo.delete_lock(job.scene_id, job.id)

    def _retry_or_dead_letter(
        self, job: Job, *, error_code: str, error_detail: str
    ) -> None:
        before = job.to_audit_dict()
        now = self._now()
        now_text = _format_dt(now)
        job.error_code = error_code
        job.error_detail = error_detail
        if job.attempt_count >= job.max_attempts:
            target = STATUS_DEAD_LETTER
            job.finished_at = now_text
            job.scheduled_at = now_text
        else:
            target = STATUS_QUEUED
            delay = self._base_backoff_s * (2 ** max(job.attempt_count - 1, 0))
            job.scheduled_at = _format_dt(now + timedelta(seconds=delay))
            job.finished_at = None
        previous = job.status
        job.status = target
        job.updated_at = now_text
        job.transitions.append({"from": previous, "to": target, "at": now_text})
        self._repo.save_job(job)
        action = "job.dead_letter" if target == STATUS_DEAD_LETTER else "job.retry"
        self._audit_transition(job, before=before, action=action)

    def _fail_terminal(
        self,
        job: Job,
        *,
        error_code: str,
        error_detail: str,
        dead_letter: bool,
    ) -> None:
        before = job.to_audit_dict()
        now_text = _format_dt(self._now())
        target = STATUS_DEAD_LETTER if dead_letter else STATUS_FAILED
        job.transitions.append({"from": job.status, "to": target, "at": now_text})
        job.status = target
        job.error_code = error_code
        job.error_detail = error_detail
        job.finished_at = now_text
        job.updated_at = now_text
        self._repo.save_job(job)
        self._audit_transition(job, before=before, action="job.fail")

    def _audit_transition(
        self, job: Job, *, before: dict[str, Any], action: str
    ) -> None:
        self._audit.write(
            actor_type=SYSTEM,
            actor_id="worker",
            action=action,
            resource_type="job",
            resource_id=job.id,
            before_json=before,
            after_json=job.to_audit_dict(),
            correlation_id=get_request_id() or job.correlation_id,
        )

    def _now(self) -> datetime:
        return self._now_fn()


class WorkerDispatchError(Exception):
    def __init__(self, error_code: str, error_detail: str) -> None:
        self.error_code = error_code
        self.error_detail = error_detail
        super().__init__(error_detail)


def dispatch_existing(
    services: ExistingServices, job: Job, inputs: dict[str, Any]
) -> dict[str, Any]:
    """Call existing services. Never approve, submit, or review-decide."""
    actor = Actor(actor_type=SYSTEM, actor_id="worker")
    if job.job_type == JOB_TYPE_PLAN:
        plan_job = services.plan.trigger_job(
            project_id=job.project_id,
            scene_id=_require_input(inputs, "scene_id"),
            snapshot_id=_require_input(inputs, "snapshot_id"),
            actor=actor,
        )
        return {
            "resource_type": "scene_plan_job",
            "resource_id": plan_job.id,
            "plan_id": plan_job.plan_id,
            "inner_state": plan_job.state,
        }
    if job.job_type == JOB_TYPE_DRAFT:
        draft_job = services.draft.trigger_job(
            project_id=job.project_id,
            scene_id=_require_input(inputs, "scene_id"),
            snapshot_id=_require_input(inputs, "snapshot_id"),
            plan_id=_require_input(inputs, "plan_id"),
            context_pack_id=_require_input(inputs, "context_pack_id"),
            actor=actor,
        )
        return {
            "resource_type": "scene_draft_job",
            "resource_id": draft_job.id,
            "draft_id": draft_job.draft_id,
            "inner_state": draft_job.state,
        }
    if job.job_type == JOB_TYPE_EXTRACT:
        extract_job = services.extract.trigger_job(
            project_id=job.project_id,
            scene_id=_require_input(inputs, "scene_id"),
            revision_id=_require_input(inputs, "revision_id", "draft_revision_id"),
            actor=actor,
        )
        return {
            "resource_type": "extract_job",
            "resource_id": extract_job.id,
            "candidate_ids": list(extract_job.candidate_ids),
            "inner_state": extract_job.state,
        }
    if job.job_type == JOB_TYPE_VALIDATE:
        run = services.validate.trigger_run(
            project_id=job.project_id,
            actor=actor,
            scene_id=_optional_input(inputs, "scene_id") or job.scene_id,
            candidate_ids=_optional_list(inputs.get("candidate_ids")),
            snapshot_id=_optional_input(inputs, "snapshot_id"),
        )
        return {
            "resource_type": "validation_run",
            "resource_id": run.id,
            "report_id": run.report_id,
            "inner_state": run.state,
        }
    if job.job_type == JOB_TYPE_REPAIR:
        return _dispatch_repair(services, job, inputs, actor)
    if job.job_type == JOB_TYPE_SUMMARIZE:
        if _optional_input(inputs, "chapter_id"):
            raise WorkerDispatchError(
                "chapter_generate_forbidden",
                "Worker summarize is scene-level only. No chapter prose generate.",
            )
        summary_job = services.summarize.trigger_scene_job(
            project_id=job.project_id,
            scene_id=_require_input(inputs, "scene_id"),
            draft_revision_id=_require_input(
                inputs, "draft_revision_id", "revision_id"
            ),
            actor=actor,
            content_hash_value=_optional_input(inputs, "content_hash"),
        )
        return {
            "resource_type": "summary_job",
            "resource_id": summary_job.id,
            "summary_id": summary_job.summary_id,
            "inner_state": summary_job.state,
        }
    if job.job_type == JOB_TYPE_CONTEXT_PACK:
        pack = services.context_pack.assemble(
            project_id=job.project_id,
            scene_id=_require_input(inputs, "scene_id"),
            snapshot_id=_require_input(inputs, "snapshot_id"),
            purpose=_optional_input(inputs, "purpose") or "Generate",
            actor=actor,
        )
        return {
            "resource_type": "context_pack",
            "resource_id": pack.id,
            "inner_state": pack.status,
        }
    raise WorkerDispatchError(
        "unsupported_job_type",
        f"Unknown job_type {job.job_type}. Node 8.1 has no Agent registry.",
    )


def _dispatch_repair(
    services: ExistingServices,
    job: Job,
    inputs: dict[str, Any],
    actor: Actor,
) -> dict[str, Any]:
    task_id = _require_input(inputs, "repair_task_id")
    task = services.repair.get_task(job.project_id, task_id)
    if task.action == ACTION_HUMAN_REJECT:
        raise WorkerDispatchError(
            "worker_cannot_human_reject",
            "Worker must not take HumanReject or other human decisions.",
        )
    started = services.repair.start_task(job.project_id, task.id, actor=actor)
    completed = services.repair.complete_task(job.project_id, started.id, actor=actor)
    return {
        "resource_type": "repair_task",
        "resource_id": completed.id,
        "inner_state": completed.state,
        "recheck_status": completed.recheck_status,
    }


def _require_input(inputs: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise WorkerDispatchError(
        "payload_input_missing",
        f"Stored payload_reference is missing {keys[0]}.",
    )


def _optional_input(inputs: dict[str, Any], key: str) -> str | None:
    value = inputs.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    return None


def _short_detail(detail: dict[str, Any]) -> str:
    error = detail.get("error")
    message = detail.get("message")
    if isinstance(error, str) and isinstance(message, str):
        return f"{error}: {message}"[:500]
    if isinstance(error, str):
        return error[:500]
    return "dispatch_failed"


def _format_dt(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    utc = aware.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond:06d}Z"


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)
