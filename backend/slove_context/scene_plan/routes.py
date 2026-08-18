"""HTTP routes for Scene Plan generation jobs (node 3.3).

POST triggers one per-scene job. GET reads the job or the current plan.
No Scene Draft generation. No chapter-level generate. No Canon writes.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from slove_context.canon.repository import CanonRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway
from slove_context.scene.repository import SceneRepository
from slove_context.scene.service import SceneService
from slove_context.scene_plan.models import DEFAULT_REPAIR_TASK_TYPE, DEFAULT_TASK_TYPE
from slove_context.scene_plan.repository import ScenePlanRepository
from slove_context.scene_plan.service import ScenePlanService, ScenePlanServiceError
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)
from slove_context.story.repository import StoryRepository

router = APIRouter(tags=["scene-plan"])


class TriggerJobBody(BaseModel):
    snapshot_id: str
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


def _service(request: Request) -> ScenePlanService:
    story: StoryRepository = request.app.state.repository
    scenes: SceneRepository = request.app.state.scene_repository
    plans: ScenePlanRepository = request.app.state.scene_plan_repository
    canon: CanonRepository = request.app.state.canon_repository
    gateway: LlmGateway = request.app.state.llm_gateway
    if gateway is None:
        gateway = LlmGateway(
            FakeProvider(), audit_writer=request.app.state.audit_writer
        )
    scene_service = SceneService(
        story_repository=story,
        scene_repository=scenes,
        audit_writer=request.app.state.audit_writer,
    )
    return ScenePlanService(
        story_repository=story,
        canon_repository=canon,
        scene_service=scene_service,
        plan_repository=plans,
        audit_writer=request.app.state.audit_writer,
        llm_gateway=gateway,
        task_type=getattr(request.app.state, "scene_plan_task_type", DEFAULT_TASK_TYPE),
        repair_task_type=getattr(
            request.app.state,
            "scene_plan_repair_task_type",
            DEFAULT_REPAIR_TASK_TYPE,
        ),
    )


def _actor(request: Request, body: TriggerJobBody | None = None) -> Actor:
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


def _raise(exc: ScenePlanServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/projects/{project_id}/scenes/{scene_id}/plans/jobs", status_code=201)
def trigger_scene_plan_job(
    request: Request, project_id: str, scene_id: str, body: TriggerJobBody
) -> dict[str, Any]:
    try:
        job = _service(request).trigger_job(
            project_id=project_id,
            scene_id=scene_id,
            snapshot_id=body.snapshot_id,
            actor=_actor(request, body),
        )
    except ScenePlanServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.get("/projects/{project_id}/scene-plan-jobs/{job_id}")
def get_scene_plan_job(
    request: Request, project_id: str, job_id: str
) -> dict[str, Any]:
    try:
        job = _service(request).get_job(project_id, job_id)
    except ScenePlanServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.get("/projects/{project_id}/scenes/{scene_id}/plans/current")
def get_current_scene_plan(
    request: Request, project_id: str, scene_id: str
) -> dict[str, Any]:
    try:
        service = _service(request)
        plan = service.get_current_plan(project_id, scene_id)
        job = service.get_job(project_id, plan.job_id)
    except ScenePlanServiceError as exc:
        _raise(exc)
    return {
        "plan": plan.to_public_dict(),
        "job_id": plan.job_id,
        "snapshot_id": plan.snapshot_id,
        "scene_id": plan.scene_id,
        "scene_card_id": plan.scene_card_id,
        "prompt_version": plan.prompt_version,
        "job_state": job.state,
        "is_canon": False,
        "is_scene_draft": False,
    }
