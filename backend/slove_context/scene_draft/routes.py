"""HTTP routes for Scene Draft generation jobs (node 3.4).

POST triggers one per-scene job. GET reads the job or draft revisions.
Cancel is terminal and does not delete. No auto-approve. No fact
extraction. No chapter-level generate. No Canon writes.
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
from slove_context.scene_draft.models import DEFAULT_TASK_TYPE
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.scene_draft.service import SceneDraftService, SceneDraftServiceError
from slove_context.scene_plan.repository import ScenePlanRepository
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)
from slove_context.story.repository import StoryRepository

router = APIRouter(tags=["scene-draft"])


class TriggerJobBody(BaseModel):
    snapshot_id: str
    plan_id: str
    context_pack_id: str
    idempotency_key: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class CancelBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None


def _service(request: Request) -> SceneDraftService:
    story: StoryRepository = request.app.state.repository
    scenes: SceneRepository = request.app.state.scene_repository
    plans: ScenePlanRepository = request.app.state.scene_plan_repository
    drafts: SceneDraftRepository = request.app.state.scene_draft_repository
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
    return SceneDraftService(
        story_repository=story,
        canon_repository=canon,
        scene_service=scene_service,
        plan_repository=plans,
        draft_repository=drafts,
        audit_writer=request.app.state.audit_writer,
        llm_gateway=gateway,
        task_type=getattr(
            request.app.state, "scene_draft_task_type", DEFAULT_TASK_TYPE
        ),
        auto_run=bool(getattr(request.app.state, "scene_draft_auto_run", True)),
    )


def _actor(request: Request, body: TriggerJobBody | CancelBody | None = None) -> Actor:
    body_type = body.actor_type if body is not None else None
    body_id = None
    if isinstance(body, TriggerJobBody):
        body_id = body.actor_id or body.created_by
    elif body is not None:
        body_id = body.actor_id
    return resolve_actor(
        header_type=request.headers.get(ACTOR_TYPE_HEADER),
        header_id=request.headers.get(ACTOR_ID_HEADER),
        body_type=body_type,
        body_id=body_id,
    )


def _raise(exc: SceneDraftServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/projects/{project_id}/scenes/{scene_id}/drafts/jobs", status_code=201)
def trigger_scene_draft_job(
    request: Request, project_id: str, scene_id: str, body: TriggerJobBody
) -> dict[str, Any]:
    try:
        job = _service(request).trigger_job(
            project_id=project_id,
            scene_id=scene_id,
            snapshot_id=body.snapshot_id,
            plan_id=body.plan_id,
            context_pack_id=body.context_pack_id,
            idempotency_key=body.idempotency_key,
            actor=_actor(request, body),
        )
    except SceneDraftServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.get("/projects/{project_id}/scene-draft-jobs/{job_id}")
def get_scene_draft_job(
    request: Request, project_id: str, job_id: str
) -> dict[str, Any]:
    try:
        job = _service(request).get_job(project_id, job_id)
    except SceneDraftServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.post("/projects/{project_id}/scene-draft-jobs/{job_id}/cancel")
def cancel_scene_draft_job(
    request: Request, project_id: str, job_id: str, body: CancelBody | None = None
) -> dict[str, Any]:
    try:
        job = _service(request).cancel_job(
            project_id, job_id, actor=_actor(request, body)
        )
    except SceneDraftServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.get("/projects/{project_id}/scenes/{scene_id}/drafts")
def list_scene_drafts(
    request: Request, project_id: str, scene_id: str
) -> dict[str, Any]:
    try:
        drafts = _service(request).list_drafts(project_id, scene_id)
    except SceneDraftServiceError as exc:
        _raise(exc)
    return {
        "items": [draft.to_public_dict() for draft in drafts],
        "is_canon": False,
        "auto_approved": False,
    }


@router.get("/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}")
def get_scene_draft(
    request: Request, project_id: str, scene_id: str, revision_id: str
) -> dict[str, Any]:
    try:
        draft = _service(request).get_draft(project_id, scene_id, revision_id)
    except SceneDraftServiceError as exc:
        _raise(exc)
    return draft.to_public_dict()
