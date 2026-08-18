"""Job queue write path (node 8.1).

Enqueue stores input refs under payload_reference. Cancel and rerun
keep the original row. The Worker (not this service) dispatches to
existing 3.3–6.1 services. No Canon write. No auto-approve.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.jobs.models import (
    ACTIVE_STATUSES,
    CANCELLABLE_STATUSES,
    DEFAULT_MAX_ATTEMPTS,
    JOB_TYPES,
    RERUNNABLE_STATUSES,
    STATUS_CANCELLED,
    STATUS_QUEUED,
    Job,
    JobPayload,
    is_write_job,
    normalize_job_type,
)
from slove_context.jobs.repository import JobRepository
from slove_context.logging import get_request_id
from slove_context.story.actors import (
    GENERATION_AGENT,
    HUMAN_EDITOR,
    REVIEW_AGENT,
    SYSTEM,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.repository import StoryRepository

ALLOWED_ENQUEUE_ACTORS = frozenset({HUMAN_EDITOR, GENERATION_AGENT, SYSTEM})


class JobServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class JobService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        job_repository: JobRepository,
        audit_writer: AuditWriter,
    ) -> None:
        self._story = story_repository
        self._repo = job_repository
        self._audit = audit_writer

    def enqueue(
        self,
        *,
        project_id: str,
        job_type: str,
        actor: Actor,
        payload_reference: str | None = None,
        payload: dict[str, Any] | None = None,
        scene_id: str | None = None,
        idempotency_key: str | None = None,
        max_attempts: int | None = None,
        correlation_id: str | None = None,
    ) -> Job:
        self._require_project(project_id)
        trigger = _require_enqueue_actor(actor)
        cleaned_type = _require_job_type(job_type)
        stored = self._resolve_payload(
            project_id=project_id,
            job_type=cleaned_type,
            payload_reference=payload_reference,
            payload=payload,
        )
        resolved_scene = _clean_optional(scene_id) or _scene_from_inputs(stored.inputs)
        if is_write_job(cleaned_type) and not resolved_scene:
            raise JobServiceError(
                422,
                {
                    "error": "scene_id_required",
                    "message": (
                        "Write jobs (plan / draft / extract / repair) "
                        "require a scene_id so the Worker can serialize "
                        "mutually exclusive writes."
                    ),
                    "job_type": cleaned_type,
                },
            )
        attempts = _require_max_attempts(max_attempts)
        key = _clean_optional(idempotency_key)
        if key is not None:
            existing = self._repo.find_by_idempotency_key(project_id, cleaned_type, key)
            if existing is not None and existing.status in ACTIVE_STATUSES:
                return existing

        now = _utc_now_z()
        job = Job(
            id=str(uuid4()),
            project_id=project_id,
            job_type=cleaned_type,
            payload_reference=stored.id,
            status=STATUS_QUEUED,
            scene_id=resolved_scene,
            idempotency_key=key,
            attempt_count=0,
            max_attempts=attempts,
            scheduled_at=now,
            created_at=now,
            updated_at=now,
            created_by=trigger.actor_id or "queue",
            actor_type=trigger.actor_type,
            correlation_id=correlation_id or get_request_id() or str(uuid4()),
        )
        self._repo.add_job(job)
        self._write_audit(
            actor=trigger,
            action="job.enqueue",
            resource_type="job",
            resource_id=job.id,
            before_json=None,
            after_json=job.to_audit_dict(),
        )
        return job

    def get_job(self, project_id: str, job_id: str) -> Job:
        self._require_project(project_id)
        job = self._repo.get_job(job_id)
        if job is None or job.project_id != project_id:
            raise JobServiceError(404, {"error": "job_not_found"})
        return job

    def list_jobs(
        self,
        project_id: str,
        *,
        status: str | None = None,
        job_type: str | None = None,
        scene_id: str | None = None,
    ) -> list[Job]:
        self._require_project(project_id)
        cleaned_type = None
        if job_type is not None:
            cleaned_type = _require_job_type(job_type)
        cleaned_status = _clean_optional(status)
        return self._repo.list_jobs(
            project_id,
            status=cleaned_status,
            job_type=cleaned_type,
            scene_id=_clean_optional(scene_id),
        )

    def cancel_job(self, project_id: str, job_id: str, *, actor: Actor) -> Job:
        editor = self._require_human(actor, action="cancel")
        job = self.get_job(project_id, job_id)
        if job.status not in CANCELLABLE_STATUSES:
            raise JobServiceError(
                409,
                {
                    "error": "job_not_cancellable",
                    "message": (
                        "Cancel applies to queued or running jobs. "
                        "Failure / cancel / dead_letter keep the record."
                    ),
                    "status": job.status,
                    "kept": True,
                },
            )
        before = job.to_audit_dict()
        now = _utc_now_z()
        job.transitions.append({"from": job.status, "to": STATUS_CANCELLED, "at": now})
        job.status = STATUS_CANCELLED
        job.finished_at = now
        job.updated_at = now
        job.error_code = "cancelled"
        job.error_detail = "cancelled_by_human_editor"
        self._repo.save_job(job)
        if job.scene_id:
            self._repo.delete_lock(job.scene_id, job.id)
        self._write_audit(
            actor=editor,
            action="job.cancel",
            resource_type="job",
            resource_id=job.id,
            before_json=before,
            after_json=job.to_audit_dict(),
        )
        return job

    def rerun_job(self, project_id: str, job_id: str, *, actor: Actor) -> Job:
        editor = self._require_human(actor, action="rerun")
        source = self.get_job(project_id, job_id)
        if source.status not in RERUNNABLE_STATUSES:
            raise JobServiceError(
                409,
                {
                    "error": "job_not_rerunnable",
                    "message": (
                        "Manual rerun applies to failed or dead_letter. "
                        "The new job reuses the same payload_reference."
                    ),
                    "status": source.status,
                    "kept": True,
                },
            )
        payload = self._repo.get_payload(source.payload_reference)
        if payload is None:
            raise JobServiceError(
                409,
                {
                    "error": "payload_reference_missing",
                    "message": (
                        "Rerun requires the stored payload_reference. "
                        "Jobs replay from saved input refs only."
                    ),
                    "payload_reference": source.payload_reference,
                },
            )
        now = _utc_now_z()
        job = Job(
            id=str(uuid4()),
            project_id=source.project_id,
            job_type=source.job_type,
            payload_reference=source.payload_reference,
            status=STATUS_QUEUED,
            scene_id=source.scene_id,
            idempotency_key=None,
            attempt_count=0,
            max_attempts=source.max_attempts,
            scheduled_at=now,
            created_at=now,
            updated_at=now,
            created_by=editor.actor_id or source.created_by,
            actor_type=editor.actor_type,
            correlation_id=get_request_id() or source.correlation_id,
            rerun_of_job_id=source.id,
        )
        self._repo.add_job(job)
        self._write_audit(
            actor=editor,
            action="job.rerun",
            resource_type="job",
            resource_id=job.id,
            before_json=source.to_audit_dict(),
            after_json=job.to_audit_dict(),
        )
        return job

    def get_payload(self, project_id: str, payload_id: str) -> JobPayload:
        self._require_project(project_id)
        payload = self._repo.get_payload(payload_id)
        if payload is None or payload.project_id != project_id:
            raise JobServiceError(404, {"error": "payload_not_found"})
        return payload

    def _resolve_payload(
        self,
        *,
        project_id: str,
        job_type: str,
        payload_reference: str | None,
        payload: dict[str, Any] | None,
    ) -> JobPayload:
        ref = _clean_optional(payload_reference)
        body = _clean_payload(payload)
        if ref is not None:
            stored = self._repo.get_payload(ref)
            if stored is None:
                if body is None:
                    raise JobServiceError(
                        404,
                        {
                            "error": "payload_not_found",
                            "message": (
                                "payload_reference must point at stored "
                                "input refs. Ephemeral bodies are rejected."
                            ),
                            "payload_reference": ref,
                        },
                    )
                stored = self._store_payload(
                    payload_id=ref,
                    project_id=project_id,
                    job_type=job_type,
                    inputs=body,
                )
                return stored
            if stored.project_id != project_id:
                raise JobServiceError(404, {"error": "payload_not_found"})
            if body is not None and body != stored.inputs:
                raise JobServiceError(
                    409,
                    {
                        "error": "payload_immutable",
                        "message": (
                            "Stored payload_reference cannot be overwritten. "
                            "Replay uses the original input refs."
                        ),
                        "payload_reference": ref,
                    },
                )
            return stored
        if body is None:
            raise JobServiceError(
                422,
                {
                    "error": "payload_required",
                    "message": (
                        "Provide payload (stored as payload_reference) "
                        "or an existing payload_reference."
                    ),
                },
            )
        return self._store_payload(
            payload_id=str(uuid4()),
            project_id=project_id,
            job_type=job_type,
            inputs=body,
        )

    def _store_payload(
        self,
        *,
        payload_id: str,
        project_id: str,
        job_type: str,
        inputs: dict[str, Any],
    ) -> JobPayload:
        stored = JobPayload(
            id=payload_id,
            project_id=project_id,
            job_type=job_type,
            inputs=inputs,
            created_at=_utc_now_z(),
        )
        self._repo.add_payload(stored)
        self._write_audit(
            actor=Actor(actor_type=SYSTEM, actor_id=None),
            action="job_payload.create",
            resource_type="job_payload",
            resource_id=stored.id,
            before_json=None,
            after_json=stored.to_audit_dict(),
        )
        return stored

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise JobServiceError(404, {"error": "project_not_found"})

    def _require_human(self, actor: Actor, *, action: str) -> Actor:
        try:
            return require_human_editor(actor, action=action, resource="job")
        except ActorError as exc:
            raise JobServiceError(
                403,
                {
                    "error": "actor_not_allowed",
                    "message": str(exc),
                    "actor_type": actor.actor_type,
                },
            ) from exc

    def _write_audit(
        self,
        *,
        actor: Actor,
        action: str,
        resource_type: str,
        resource_id: str,
        before_json: dict[str, Any] | None,
        after_json: dict[str, Any] | None,
    ) -> None:
        self._audit.write(
            actor_type=actor.actor_type or SYSTEM,
            actor_id=actor.actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            correlation_id=get_request_id(),
        )


def _require_enqueue_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or GENERATION_AGENT
    if actor_type == REVIEW_AGENT:
        raise JobServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Review agents cannot enqueue Worker jobs. "
                    "The Worker is a dispatcher, not a decision-maker."
                ),
                "actor_type": actor_type,
            },
        )
    if actor_type not in ALLOWED_ENQUEUE_ACTORS:
        raise JobServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Jobs may be enqueued by the human 主编, a "
                    "generation agent, or the system. This is not "
                    "Canon approval."
                ),
                "actor_type": actor_type,
            },
        )
    return Actor(actor_type=actor_type, actor_id=actor.actor_id)


def _require_job_type(raw: str | None) -> str:
    cleaned = normalize_job_type(raw)
    if cleaned is None:
        raise JobServiceError(
            422,
            {
                "error": "invalid_job_type",
                "message": (
                    "job_type must be one of: plan, draft, extract, "
                    "validate, repair, summarize, context_pack."
                ),
                "allowed": sorted(JOB_TYPES),
            },
        )
    return cleaned


def _require_max_attempts(value: int | None) -> int:
    if value is None:
        return DEFAULT_MAX_ATTEMPTS
    if value < 1:
        raise JobServiceError(
            422,
            {
                "error": "invalid_max_attempts",
                "message": "max_attempts must be at least 1.",
            },
        )
    return value


def _clean_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise JobServiceError(
            422,
            {
                "error": "invalid_payload",
                "message": "payload must be an object of stored input refs.",
            },
        )
    return dict(payload)


def _scene_from_inputs(inputs: dict[str, Any]) -> str | None:
    value = inputs.get("scene_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
