"""HTTP routes for batch schedule (node 8.4).

PUT  /projects/{project_id}/schedule/config
GET  /projects/{project_id}/schedule/config
POST /projects/{project_id}/schedule/start
POST /projects/{project_id}/schedule/dry-run
POST /projects/{project_id}/schedule/runs/{run_id}/pause
POST /projects/{project_id}/schedule/runs/{run_id}/resume
POST /projects/{project_id}/schedule/runs/{run_id}/cancel
GET  /projects/{project_id}/schedule/runs
GET  /projects/{project_id}/schedule/runs/{run_id}
GET  /projects/{project_id}/schedule/alerts
GET  /projects/{project_id}/schedule/decisions
POST /schedules/tick
POST /projects/{project_id}/schedule/approve-canon  (always 403)
POST /projects/{project_id}/schedule/submit-canon   (always 403)

Resume / pause-override are human-only. Scheduler never writes Canon.
No production seed-status. No 9.x eval. No real model.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from slove_context.scene.service import SceneService
from slove_context.scheduler.deps import scheduler_services_from_state
from slove_context.scheduler.repository import (
    InMemoryScheduleRepository,
    ScheduleRepository,
)
from slove_context.scheduler.service import ScheduleService, ScheduleServiceError
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)

router = APIRouter(tags=["batch-schedule"])


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class ConfigBody(ActorBody):
    concurrency: int | None = None
    daily_token_budget: int | None = None
    per_scene_cost_cap: float | None = None
    failure_threshold: int | None = None


class StartBody(ActorBody):
    snapshot_id: str
    chapter_id: str | None = None


class InspectBody(ActorBody):
    scene_id: str
    snapshot_id: str | None = None
    task_kind: str = "prose_write"


def _service(request: Request) -> ScheduleService:
    schedules: ScheduleRepository = (
        getattr(request.app.state, "schedule_repository", None)
        or InMemoryScheduleRepository()
    )
    scenes = SceneService(
        story_repository=request.app.state.repository,
        scene_repository=request.app.state.scene_repository,
        audit_writer=request.app.state.audit_writer,
    )
    return ScheduleService(
        story_repository=request.app.state.repository,
        scene_service=scenes,
        schedule_repository=schedules,
        audit_writer=request.app.state.audit_writer,
        services=scheduler_services_from_state(request.app.state),
    )


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


def _raise(exc: ScheduleServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.put("/projects/{project_id}/schedule/config")
def put_schedule_config(
    request: Request, project_id: str, body: ConfigBody
) -> dict[str, Any]:
    try:
        config = _service(request).configure(
            project_id,
            actor=_actor(request, body),
            concurrency=body.concurrency,
            daily_token_budget=body.daily_token_budget,
            per_scene_cost_cap=body.per_scene_cost_cap,
            failure_threshold=body.failure_threshold,
        )
    except ScheduleServiceError as exc:
        _raise(exc)
    return config.to_public_dict()


@router.get("/projects/{project_id}/schedule/config")
def get_schedule_config(request: Request, project_id: str) -> dict[str, Any]:
    try:
        return _service(request).get_config(project_id).to_public_dict()
    except ScheduleServiceError as exc:
        _raise(exc)


@router.post("/projects/{project_id}/schedule/dry-run", status_code=201)
def dry_run_schedule(
    request: Request, project_id: str, body: StartBody
) -> dict[str, Any]:
    try:
        return _service(request).dry_run(
            project_id,
            actor=_actor(request, body),
            snapshot_id=body.snapshot_id,
            chapter_id=body.chapter_id,
        )
    except ScheduleServiceError as exc:
        _raise(exc)


@router.post("/projects/{project_id}/schedule/start", status_code=201)
def start_schedule(
    request: Request, project_id: str, body: StartBody
) -> dict[str, Any]:
    try:
        run = _service(request).start(
            project_id,
            actor=_actor(request, body),
            snapshot_id=body.snapshot_id,
            chapter_id=body.chapter_id,
        )
    except ScheduleServiceError as exc:
        _raise(exc)
    return run.to_public_dict()


@router.post("/projects/{project_id}/schedule/runs/{run_id}/pause")
def pause_schedule(
    request: Request,
    project_id: str,
    run_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        run = _service(request).pause(project_id, run_id, actor=_actor(request, body))
    except ScheduleServiceError as exc:
        _raise(exc)
    return {"item": run.to_public_dict(), "kept": True, "writes_canon": False}


@router.post("/projects/{project_id}/schedule/runs/{run_id}/resume")
def resume_schedule(
    request: Request,
    project_id: str,
    run_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        run = _service(request).resume(project_id, run_id, actor=_actor(request, body))
    except ScheduleServiceError as exc:
        _raise(exc)
    return run.to_public_dict()


@router.post("/projects/{project_id}/schedule/runs/{run_id}/cancel")
def cancel_schedule(
    request: Request,
    project_id: str,
    run_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        run = _service(request).cancel(project_id, run_id, actor=_actor(request, body))
    except ScheduleServiceError as exc:
        _raise(exc)
    return {"item": run.to_public_dict(), "kept": True, "writes_canon": False}


@router.get("/projects/{project_id}/schedule/runs")
def list_schedule_runs(request: Request, project_id: str) -> dict[str, Any]:
    try:
        items = _service(request).list_runs(project_id)
    except ScheduleServiceError as exc:
        _raise(exc)
    return {
        "items": [item.to_public_dict() for item in items],
        "writes_canon": False,
    }


@router.get("/projects/{project_id}/schedule/runs/{run_id}")
def get_schedule_run(request: Request, project_id: str, run_id: str) -> dict[str, Any]:
    try:
        return _service(request).get_run(project_id, run_id).to_public_dict()
    except ScheduleServiceError as exc:
        _raise(exc)


@router.get("/projects/{project_id}/schedule/alerts")
def list_schedule_alerts(request: Request, project_id: str) -> dict[str, Any]:
    try:
        items = _service(request).list_alerts(project_id)
    except ScheduleServiceError as exc:
        _raise(exc)
    return {
        "items": [item.to_public_dict() for item in items],
        "writes_canon": False,
        "auto_resumed": False,
    }


@router.get("/projects/{project_id}/schedule/decisions")
def list_schedule_decisions(
    request: Request, project_id: str, run_id: str | None = None
) -> dict[str, Any]:
    try:
        items = _service(request).list_decisions(project_id, run_id=run_id)
    except ScheduleServiceError as exc:
        _raise(exc)
    return {
        "items": [item.to_public_dict() for item in items],
        "writes_canon": False,
        "auto_approved": False,
    }


@router.post("/projects/{project_id}/schedule/inspect")
def inspect_schedule_scene(
    request: Request, project_id: str, body: InspectBody
) -> dict[str, Any]:
    try:
        return _service(request).inspect_scene(
            project_id,
            scene_id=body.scene_id,
            snapshot_id=body.snapshot_id,
            task_kind=body.task_kind,
        )
    except ScheduleServiceError as exc:
        _raise(exc)


@router.post("/schedules/tick")
def tick_schedules(request: Request, body: ActorBody | None = None) -> dict[str, Any]:
    try:
        return _service(request).tick(actor=_actor(request, body))
    except ScheduleServiceError as exc:
        _raise(exc)


@router.post("/projects/{project_id}/schedule/approve-canon")
def schedule_approve_canon(
    request: Request, project_id: str, body: ActorBody | None = None
) -> dict[str, Any]:
    try:
        _service(request).reject_canon_write(
            project_id, actor=_actor(request, body), action="approve"
        )
    except ScheduleServiceError as exc:
        _raise(exc)
    raise HTTPException(
        status_code=403, detail={"error": "scheduler_cannot_write_canon"}
    )


@router.post("/projects/{project_id}/schedule/submit-canon")
def schedule_submit_canon(
    request: Request, project_id: str, body: ActorBody | None = None
) -> dict[str, Any]:
    try:
        _service(request).reject_canon_write(
            project_id, actor=_actor(request, body), action="submit"
        )
    except ScheduleServiceError as exc:
        _raise(exc)
    raise HTTPException(
        status_code=403, detail={"error": "scheduler_cannot_write_canon"}
    )
