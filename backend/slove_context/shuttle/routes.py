"""HTTP routes for the human shuttle (node UI.2).

Four doors: copy draft prompt, paste draft, copy extract prompt,
paste extract JSON. Human editor only. No Gateway / Fake calls.
Paste-back is not approval and does not write Canon.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from slove_context.candidate_change.models import (
    DEFAULT_REPAIR_TASK_TYPE,
    DEFAULT_TASK_TYPE,
)
from slove_context.candidate_change.repository import CandidateChangeRepository
from slove_context.candidate_change.service import CandidateChangeService
from slove_context.canon.repository import CanonRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway
from slove_context.scene.repository import SceneRepository
from slove_context.scene.service import SceneService
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.scene_plan.repository import ScenePlanRepository
from slove_context.shuttle.service import ShuttleService, ShuttleServiceError
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)
from slove_context.story.repository import StoryRepository

router = APIRouter(tags=["shuttle"])


class ImportDraftBody(BaseModel):
    body: str
    snapshot_id: str
    plan_id: str | None = None
    context_pack_id: str | None = None
    idempotency_key: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class ImportExtractBody(BaseModel):
    candidates: list[Any]
    idempotency_key: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


def _extract_service(request: Request) -> CandidateChangeService:
    story: StoryRepository = request.app.state.repository
    scenes: SceneRepository = request.app.state.scene_repository
    drafts: SceneDraftRepository = request.app.state.scene_draft_repository
    extracts: CandidateChangeRepository = request.app.state.candidate_change_repository
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
    return CandidateChangeService(
        story_repository=story,
        scene_service=scene_service,
        draft_repository=drafts,
        extract_repository=extracts,
        audit_writer=request.app.state.audit_writer,
        llm_gateway=gateway,
        task_type=getattr(request.app.state, "extract_task_type", DEFAULT_TASK_TYPE),
        repair_task_type=getattr(
            request.app.state, "extract_repair_task_type", DEFAULT_REPAIR_TASK_TYPE
        ),
        auto_run=False,
    )


def _service(request: Request) -> ShuttleService:
    story: StoryRepository = request.app.state.repository
    scenes: SceneRepository = request.app.state.scene_repository
    drafts: SceneDraftRepository = request.app.state.scene_draft_repository
    extracts: CandidateChangeRepository = request.app.state.candidate_change_repository
    canon: CanonRepository = request.app.state.canon_repository
    plans: ScenePlanRepository = request.app.state.scene_plan_repository
    scene_service = SceneService(
        story_repository=story,
        scene_repository=scenes,
        audit_writer=request.app.state.audit_writer,
    )
    return ShuttleService(
        story_repository=story,
        canon_repository=canon,
        scene_service=scene_service,
        plan_repository=plans,
        draft_repository=drafts,
        extract_repository=extracts,
        extract_service=_extract_service(request),
        audit_writer=request.app.state.audit_writer,
    )


def _actor(
    request: Request,
    body: ImportDraftBody | ImportExtractBody | ActorBody | None = None,
) -> Actor:
    body_type = body.actor_type if body is not None else None
    body_id = None
    if isinstance(body, (ImportDraftBody, ImportExtractBody, ActorBody)):
        body_id = body.actor_id or body.created_by
    return resolve_actor(
        header_type=request.headers.get(ACTOR_TYPE_HEADER),
        header_id=request.headers.get(ACTOR_ID_HEADER),
        body_type=body_type,
        body_id=body_id,
    )


def _raise(exc: ShuttleServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/projects/{project_id}/scenes/{scene_id}/shuttle/draft-prompt")
def get_draft_prompt(
    request: Request, project_id: str, scene_id: str
) -> dict[str, Any]:
    try:
        return _service(request).draft_prompt(
            project_id, scene_id, actor=_actor(request)
        )
    except ShuttleServiceError as exc:
        _raise(exc)


@router.post("/projects/{project_id}/scenes/{scene_id}/shuttle/drafts", status_code=201)
def import_draft(
    request: Request, project_id: str, scene_id: str, body: ImportDraftBody
) -> dict[str, Any]:
    try:
        return _service(request).import_draft(
            project_id=project_id,
            scene_id=scene_id,
            body=body.body,
            snapshot_id=body.snapshot_id,
            plan_id=body.plan_id,
            context_pack_id=body.context_pack_id,
            idempotency_key=body.idempotency_key,
            actor=_actor(request, body),
        )
    except ShuttleServiceError as exc:
        _raise(exc)


@router.get(
    "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/shuttle/extract-prompt"
)
def get_extract_prompt(
    request: Request, project_id: str, scene_id: str, revision_id: str
) -> dict[str, Any]:
    try:
        return _service(request).extract_prompt(
            project_id, scene_id, revision_id, actor=_actor(request)
        )
    except ShuttleServiceError as exc:
        _raise(exc)


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/shuttle/extracts",
    status_code=201,
)
def import_extract(
    request: Request,
    project_id: str,
    scene_id: str,
    revision_id: str,
    body: ImportExtractBody,
) -> dict[str, Any]:
    try:
        return _service(request).import_extract(
            project_id=project_id,
            scene_id=scene_id,
            revision_id=revision_id,
            candidates=body.candidates,
            idempotency_key=body.idempotency_key,
            actor=_actor(request, body),
        )
    except ShuttleServiceError as exc:
        _raise(exc)
