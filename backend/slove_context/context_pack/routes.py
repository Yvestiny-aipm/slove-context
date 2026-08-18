"""HTTP routes for Context Pack assembly (node 6.1).

POST /projects/{project_id}/scenes/{scene_id}/context-packs
POST /projects/{project_id}/context-packs/{pack_id}/freeze
POST /projects/{project_id}/context-packs/{pack_id}/cancel
GET  /projects/{project_id}/context-packs/{pack_id}
GET  /projects/{project_id}/scenes/{scene_id}/context-packs

Per-scene only. No chapter-level or book-level pack. Freeze is not
Canon approval. No production seed-status route.
"""

from __future__ import annotations

from typing import Any, Literal, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from slove_context.candidate_change.repository import CandidateChangeRepository
from slove_context.canon.repository import CanonRepository
from slove_context.canon.service import CanonService
from slove_context.context_pack.repository import (
    ContextPackRepository,
    InMemoryContextPackRepository,
)
from slove_context.context_pack.service import (
    ContextPackService,
    ContextPackServiceError,
)
from slove_context.scene.service import SceneService
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.scene_plan.repository import ScenePlanRepository
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)
from slove_context.story.repository import StoryRepository

router = APIRouter(tags=["context-pack"])

PackPurpose = Literal["Generate", "Validate"]


class AssembleBody(BaseModel):
    snapshot_id: str
    purpose: PackPurpose
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None


def _service(request: Request) -> ContextPackService:
    story: StoryRepository = request.app.state.repository
    packs: ContextPackRepository = (
        getattr(request.app.state, "context_pack_repository", None)
        or InMemoryContextPackRepository()
    )
    canon: CanonRepository = request.app.state.canon_repository
    plans: ScenePlanRepository | None = getattr(
        request.app.state, "scene_plan_repository", None
    )
    drafts: SceneDraftRepository | None = getattr(
        request.app.state, "scene_draft_repository", None
    )
    candidates: CandidateChangeRepository | None = getattr(
        request.app.state, "candidate_change_repository", None
    )
    scene_service = SceneService(
        story_repository=story,
        scene_repository=request.app.state.scene_repository,
        audit_writer=request.app.state.audit_writer,
    )
    return ContextPackService(
        story_repository=story,
        scene_service=scene_service,
        canon_service=CanonService(
            story_repository=story,
            canon_repository=canon,
            audit_writer=request.app.state.audit_writer,
        ),
        canon_repository=canon,
        pack_repository=packs,
        audit_writer=request.app.state.audit_writer,
        plan_repository=plans,
        draft_repository=drafts,
        candidate_repository=candidates,
    )


def _actor(request: Request, body: AssembleBody | ActorBody | None = None) -> Actor:
    body_type = body.actor_type if body is not None else None
    body_id = None
    if isinstance(body, AssembleBody):
        body_id = body.actor_id or body.created_by
    elif body is not None:
        body_id = body.actor_id
    return resolve_actor(
        header_type=request.headers.get(ACTOR_TYPE_HEADER),
        header_id=request.headers.get(ACTOR_ID_HEADER),
        body_type=body_type,
        body_id=body_id,
    )


def _raise(exc: ContextPackServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/projects/{project_id}/scenes/{scene_id}/context-packs", status_code=201)
def assemble_context_pack(
    request: Request, project_id: str, scene_id: str, body: AssembleBody
) -> dict[str, Any]:
    try:
        pack = _service(request).assemble(
            project_id=project_id,
            scene_id=scene_id,
            snapshot_id=body.snapshot_id,
            purpose=body.purpose,
            actor=_actor(request, body),
        )
    except ContextPackServiceError as exc:
        _raise(exc)
    return pack.to_public_dict()


@router.post("/projects/{project_id}/context-packs/{pack_id}/freeze")
def freeze_context_pack(
    request: Request,
    project_id: str,
    pack_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        pack = _service(request).freeze(
            project_id, pack_id, actor=_actor(request, body)
        )
    except ContextPackServiceError as exc:
        _raise(exc)
    return pack.to_public_dict()


@router.post("/projects/{project_id}/context-packs/{pack_id}/cancel")
def cancel_context_pack(
    request: Request,
    project_id: str,
    pack_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        pack = _service(request).cancel(
            project_id, pack_id, actor=_actor(request, body)
        )
    except ContextPackServiceError as exc:
        _raise(exc)
    return pack.to_public_dict()


@router.get("/projects/{project_id}/context-packs/{pack_id}")
def get_context_pack(request: Request, project_id: str, pack_id: str) -> dict[str, Any]:
    try:
        pack = _service(request).get_pack(project_id, pack_id)
    except ContextPackServiceError as exc:
        _raise(exc)
    return pack.to_public_dict()


@router.get("/projects/{project_id}/scenes/{scene_id}/context-packs")
def list_context_packs(
    request: Request, project_id: str, scene_id: str
) -> dict[str, Any]:
    try:
        packs = _service(request).list_packs(project_id, scene_id)
    except ContextPackServiceError as exc:
        _raise(exc)
    return {
        "items": [item.to_public_dict() for item in packs],
        "is_canon": False,
        "writes_canon": False,
        "auto_approved": False,
        "is_outline": False,
    }
