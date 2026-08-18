"""HTTP routes for the local job queue (node 8.1).

POST /projects/{project_id}/jobs
GET  /projects/{project_id}/jobs
GET  /projects/{project_id}/jobs/{job_id}
POST .../jobs/{job_id}/cancel
POST .../jobs/{job_id}/rerun

Worker.tick() / run_once() is in-process for tests. No background
daemon. No Agent registry. No production seed-status. Worker does
not approve Candidate Changes or submit Canon.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from slove_context.jobs.deps import services_from_state
from slove_context.jobs.models import STATUS_QUEUED
from slove_context.jobs.repository import InMemoryJobRepository, JobRepository
from slove_context.jobs.service import JobService, JobServiceError
from slove_context.jobs.worker import Worker
from slove_context.logging import get_request_id
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)

router = APIRouter(tags=["jobs"])


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class EnqueueBody(ActorBody):
    job_type: str
    payload_reference: str | None = None
    payload: dict[str, Any] | None = None
    scene_id: str | None = None
    idempotency_key: str | None = None
    max_attempts: int | None = None


def _service(request: Request) -> JobService:
    jobs: JobRepository = (
        getattr(request.app.state, "job_repository", None) or InMemoryJobRepository()
    )
    return JobService(
        story_repository=request.app.state.repository,
        job_repository=jobs,
        audit_writer=request.app.state.audit_writer,
    )


def _worker(request: Request) -> Worker:
    existing = getattr(request.app.state, "worker", None)
    if isinstance(existing, Worker):
        return existing
    jobs: JobRepository = (
        getattr(request.app.state, "job_repository", None) or InMemoryJobRepository()
    )
    worker = Worker(
        job_repository=jobs,
        audit_writer=request.app.state.audit_writer,
        services=services_from_state(request.app.state),
        timeout_s=float(getattr(request.app.state, "job_timeout_s", 30.0)),
        base_backoff_s=float(getattr(request.app.state, "job_base_backoff_s", 0.0)),
    )
    request.app.state.worker = worker
    return worker


def _actor(request: Request, body: ActorBody | None = None) -> Actor:
    body_type = body.actor_type if body is not None else None
    body_id = None
    if body is not None:
        body_id = body.actor_id or body.created_by
    return resolve_actor(
        header_type=request.headers.get(ACTOR_TYPE_HEADER),
        header_id=request.headers.get(ACTOR_ID_HEADER),
        body_type=body_type,
        body_id=body_id,
    )


def _raise(exc: JobServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _maybe_run(request: Request, job: Any) -> None:
    if not bool(getattr(request.app.state, "job_auto_run", False)):
        return
    worker = _worker(request)
    for _ in range(8):
        current = _service(request).get_job(job.project_id, job.id)
        if current.status != STATUS_QUEUED:
            return
        progressed = worker.run_once()
        if progressed is None:
            return


@router.post("/projects/{project_id}/jobs", status_code=201)
def enqueue_job(request: Request, project_id: str, body: EnqueueBody) -> dict[str, Any]:
    try:
        job = _service(request).enqueue(
            project_id=project_id,
            job_type=body.job_type,
            actor=_actor(request, body),
            payload_reference=body.payload_reference,
            payload=body.payload,
            scene_id=body.scene_id,
            idempotency_key=body.idempotency_key,
            max_attempts=body.max_attempts,
            correlation_id=get_request_id(),
        )
    except JobServiceError as exc:
        _raise(exc)
    _maybe_run(request, job)
    refreshed = _service(request).get_job(project_id, job.id)
    return refreshed.to_public_dict()


@router.get("/projects/{project_id}/jobs")
def list_jobs(
    request: Request,
    project_id: str,
    status: str | None = Query(default=None),
    job_type: str | None = Query(default=None),
    scene_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        items = _service(request).list_jobs(
            project_id, status=status, job_type=job_type, scene_id=scene_id
        )
    except JobServiceError as exc:
        _raise(exc)
    return {
        "items": [item.to_public_dict() for item in items],
        "writes_canon": False,
        "auto_approved": False,
    }


@router.get("/projects/{project_id}/jobs/{job_id}")
def get_job(request: Request, project_id: str, job_id: str) -> dict[str, Any]:
    try:
        job = _service(request).get_job(project_id, job_id)
    except JobServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.post("/projects/{project_id}/jobs/{job_id}/cancel")
def cancel_job(
    request: Request, project_id: str, job_id: str, body: ActorBody | None = None
) -> dict[str, Any]:
    try:
        job = _service(request).cancel_job(
            project_id, job_id, actor=_actor(request, body)
        )
    except JobServiceError as exc:
        _raise(exc)
    return {"item": job.to_public_dict(), "kept": True, "writes_canon": False}


@router.post("/projects/{project_id}/jobs/{job_id}/rerun")
def rerun_job(
    request: Request, project_id: str, job_id: str, body: ActorBody | None = None
) -> dict[str, Any]:
    try:
        job = _service(request).rerun_job(
            project_id, job_id, actor=_actor(request, body)
        )
    except JobServiceError as exc:
        _raise(exc)
    _maybe_run(request, job)
    refreshed = _service(request).get_job(project_id, job.id)
    return {
        "item": refreshed.to_public_dict(),
        "payload_reference": refreshed.payload_reference,
        "rerun_of_job_id": refreshed.rerun_of_job_id,
        "writes_canon": False,
    }
