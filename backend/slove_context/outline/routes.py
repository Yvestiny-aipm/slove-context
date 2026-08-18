"""HTTP routes for Outline Revision (node 6.2).

POST /projects/{project_id}/outline-revisions
PATCH /projects/{project_id}/outline-revisions/{revision_id}
POST .../outline-revisions/{revision_id}/propose
POST .../outline-revisions/{revision_id}/confirm  (human_editor only)
POST .../outline-revisions/{revision_id}/revise
POST .../outline-revisions/{revision_id}/cancel
POST .../outline-revisions/{revision_id}/fail
POST .../outline-revisions/{revision_id}/rework
POST .../outline-revisions/{revision_id}/resume
GET  /projects/{project_id}/outline-revisions
GET  /projects/{project_id}/outline-revisions/{revision_id}

Confirm usable is not Approval and does not write Canon.
Outline is not a generation unit: there is no chapter- or book-level
generate entrance. No production seed-status route.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from slove_context.outline.repository import (
    InMemoryOutlineRepository,
    OutlineRepository,
)
from slove_context.outline.service import OutlineService, OutlineServiceError
from slove_context.scene.repository import SceneRepository
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)
from slove_context.story.repository import StoryRepository

router = APIRouter(tags=["outline-revision"])


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class CreateOutlineBody(ActorBody):
    nodes: list[dict[str, Any]] = Field(default_factory=list)


class PatchOutlineBody(ActorBody):
    nodes: list[dict[str, Any]] | None = None


class FailBody(ActorBody):
    reason: str | None = None


class ReviseBody(ActorBody):
    nodes: list[dict[str, Any]] | None = None


def _service(request: Request) -> OutlineService:
    story: StoryRepository = request.app.state.repository
    scenes: SceneRepository = request.app.state.scene_repository
    outlines: OutlineRepository = (
        getattr(request.app.state, "outline_repository", None)
        or InMemoryOutlineRepository()
    )
    return OutlineService(
        story_repository=story,
        scene_repository=scenes,
        outline_repository=outlines,
        audit_writer=request.app.state.audit_writer,
    )


def _actor(request: Request, body: ActorBody | dict[str, Any] | None = None) -> Actor:
    body_type: str | None = None
    body_id: str | None = None
    if isinstance(body, ActorBody):
        body_type = body.actor_type
        body_id = body.actor_id or body.created_by
    elif isinstance(body, dict):
        raw_type = body.get("actor_type")
        raw_id = body.get("actor_id") or body.get("created_by")
        body_type = raw_type if isinstance(raw_type, str) else None
        body_id = raw_id if isinstance(raw_id, str) else None
    return resolve_actor(
        header_type=request.headers.get(ACTOR_TYPE_HEADER),
        header_id=request.headers.get(ACTOR_ID_HEADER),
        body_type=body_type,
        body_id=body_id,
    )


def _raise(exc: OutlineServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _envelope(revision_dict: dict[str, Any]) -> dict[str, Any]:
    revision_dict.setdefault("is_canon", False)
    revision_dict.setdefault("is_approval", False)
    revision_dict.setdefault("writes_canon", False)
    revision_dict.setdefault("auto_approved", False)
    revision_dict.setdefault("is_generation_unit", False)
    return revision_dict


@router.post("/projects/{project_id}/outline-revisions", status_code=201)
def create_outline_revision(
    request: Request, project_id: str, body: CreateOutlineBody
) -> dict[str, Any]:
    try:
        revision = _service(request).create(
            project_id=project_id,
            actor=_actor(request, body),
            nodes=body.nodes,
            created_by=body.created_by,
        )
    except OutlineServiceError as exc:
        _raise(exc)
    return _envelope(revision.to_public_dict())


@router.patch("/projects/{project_id}/outline-revisions/{revision_id}")
def patch_outline_revision(
    request: Request,
    project_id: str,
    revision_id: str,
    body: PatchOutlineBody,
) -> dict[str, Any]:
    try:
        revision = _service(request).patch(
            project_id=project_id,
            revision_id=revision_id,
            actor=_actor(request, body),
            nodes=body.nodes,
        )
    except OutlineServiceError as exc:
        _raise(exc)
    return _envelope(revision.to_public_dict())


@router.post("/projects/{project_id}/outline-revisions/{revision_id}/propose")
def propose_outline_revision(
    request: Request,
    project_id: str,
    revision_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        revision = _service(request).propose(
            project_id, revision_id, actor=_actor(request, body)
        )
    except OutlineServiceError as exc:
        _raise(exc)
    return _envelope(revision.to_public_dict())


@router.post("/projects/{project_id}/outline-revisions/{revision_id}/confirm")
def confirm_outline_revision(
    request: Request,
    project_id: str,
    revision_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        revision = _service(request).confirm(
            project_id, revision_id, actor=_actor(request, body)
        )
    except OutlineServiceError as exc:
        _raise(exc)
    return _envelope(revision.to_public_dict())


@router.post("/projects/{project_id}/outline-revisions/{revision_id}/revise")
def revise_outline_revision(
    request: Request,
    project_id: str,
    revision_id: str,
    body: ReviseBody | None = None,
) -> dict[str, Any]:
    payload = body or ReviseBody()
    try:
        revision = _service(request).revise(
            project_id,
            revision_id,
            actor=_actor(request, payload),
            nodes=payload.nodes,
        )
    except OutlineServiceError as exc:
        _raise(exc)
    return _envelope(revision.to_public_dict())


@router.post("/projects/{project_id}/outline-revisions/{revision_id}/cancel")
def cancel_outline_revision(
    request: Request,
    project_id: str,
    revision_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        revision = _service(request).cancel(
            project_id, revision_id, actor=_actor(request, body)
        )
    except OutlineServiceError as exc:
        _raise(exc)
    return _envelope(revision.to_public_dict())


@router.post("/projects/{project_id}/outline-revisions/{revision_id}/fail")
def fail_outline_revision(
    request: Request,
    project_id: str,
    revision_id: str,
    body: FailBody | None = None,
) -> dict[str, Any]:
    payload = body or FailBody()
    try:
        revision = _service(request).fail(
            project_id,
            revision_id,
            actor=_actor(request, payload),
            reason=payload.reason,
        )
    except OutlineServiceError as exc:
        _raise(exc)
    return _envelope(revision.to_public_dict())


@router.post("/projects/{project_id}/outline-revisions/{revision_id}/rework")
def rework_outline_revision(
    request: Request,
    project_id: str,
    revision_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        revision = _service(request).rework(
            project_id, revision_id, actor=_actor(request, body)
        )
    except OutlineServiceError as exc:
        _raise(exc)
    return _envelope(revision.to_public_dict())


@router.post("/projects/{project_id}/outline-revisions/{revision_id}/resume")
def resume_outline_revision(
    request: Request,
    project_id: str,
    revision_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        revision = _service(request).resume(
            project_id, revision_id, actor=_actor(request, body)
        )
    except OutlineServiceError as exc:
        _raise(exc)
    return _envelope(revision.to_public_dict())


@router.get("/projects/{project_id}/outline-revisions")
def list_outline_revisions(request: Request, project_id: str) -> dict[str, Any]:
    try:
        items = _service(request).list_revisions(project_id)
    except OutlineServiceError as exc:
        _raise(exc)
    return {
        "items": [_envelope(item.to_public_dict()) for item in items],
        "is_canon": False,
        "is_approval": False,
        "writes_canon": False,
        "auto_approved": False,
        "is_generation_unit": False,
        "is_outline": True,
    }


@router.get("/projects/{project_id}/outline-revisions/{revision_id}")
def get_outline_revision(
    request: Request, project_id: str, revision_id: str
) -> dict[str, Any]:
    try:
        revision = _service(request).get_revision(project_id, revision_id)
    except OutlineServiceError as exc:
        _raise(exc)
    return _envelope(revision.to_public_dict())
