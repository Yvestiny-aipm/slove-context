"""HTTP routes for Style Guide / Style Sample (node 7.1).

POST /projects/{project_id}/style-guides
PATCH .../style-guides/{guide_id}          (draft only)
POST .../style-guides/{guide_id}/approve   (human_editor only → frozen)
POST .../style-guides/{guide_id}/revise
POST .../style-guides/{guide_id}/cancel
POST .../style-guides/{guide_id}/fail
GET  /projects/{project_id}/style-guides
GET  /projects/{project_id}/style-guides/{guide_id}

POST /projects/{project_id}/style-samples
PATCH .../style-samples/{sample_id}        (draft only)
POST .../style-samples/{sample_id}/authorize  (human_editor only)
POST .../style-samples/{sample_id}/revise
POST .../style-samples/{sample_id}/cancel
POST .../style-samples/{sample_id}/fail
GET  /projects/{project_id}/style-samples
GET  /projects/{project_id}/style-samples/{sample_id}

POST .../scenes/{scene_id}/drafts/{revision_id}/style
  body: { style_guide_revision_id, style_sample_ids[] }
  validates approved / authorized / version. Reference only.

Approving a style asset is not Canon approval and does not write Canon.
No production seed-status route. No style scoring (7.2).
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from slove_context.scene.repository import SceneRepository
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)
from slove_context.story.repository import StoryRepository
from slove_context.style.repository import InMemoryStyleRepository, StyleRepository
from slove_context.style.service import StyleService, StyleServiceError

router = APIRouter(tags=["style"])


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class StyleGuideBody(ActorBody):
    pov: str | None = None
    POV: str | None = None
    person: str | None = None
    tense: str | None = None
    narrative_distance: str | None = None
    tone: str | None = None
    rhythm: str | None = None
    dialogue_rules: list[str] | str | None = None
    vocabulary_preferences: list[str] | str | None = None
    forbidden_expressions: list[str] | str | None = None
    positive_examples: list[str] | str | None = None
    negative_examples: list[str] | str | None = None

    model_config = {"extra": "allow"}


class StyleSampleBody(ActorBody):
    source: str | None = None
    copyright_mark: str | None = None
    authorization_mark: str | None = None
    scope_of_use: str | None = None
    body: str | None = None
    sample_body: str | None = None
    sample_text: str | None = None

    model_config = {"extra": "allow"}


class FailBody(ActorBody):
    reason: str | None = None


class AssociateStyleBody(ActorBody):
    style_guide_revision_id: str | None = None
    style_sample_ids: list[str] = Field(default_factory=list)


def _service(request: Request) -> StyleService:
    story: StoryRepository = request.app.state.repository
    styles: StyleRepository = (
        getattr(request.app.state, "style_repository", None)
        or InMemoryStyleRepository()
    )
    scenes: SceneRepository | None = getattr(
        request.app.state, "scene_repository", None
    )
    drafts: SceneDraftRepository | None = getattr(
        request.app.state, "scene_draft_repository", None
    )
    return StyleService(
        story_repository=story,
        style_repository=styles,
        audit_writer=request.app.state.audit_writer,
        scene_repository=scenes,
        draft_repository=drafts,
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


def _raise(exc: StyleServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    payload.setdefault("is_canon", False)
    payload.setdefault("is_approval", False)
    payload.setdefault("is_canon_approval", False)
    payload.setdefault("writes_canon", False)
    payload.setdefault("auto_approved", False)
    payload.setdefault("is_style_scoring", False)
    return payload


def _guide_payload(body: StyleGuideBody) -> dict[str, Any]:
    extra = body.model_dump(exclude_unset=True)
    extra.pop("actor_type", None)
    extra.pop("actor_id", None)
    extra.pop("created_by", None)
    return extra


def _sample_payload(body: StyleSampleBody) -> dict[str, Any]:
    extra = body.model_dump(exclude_unset=True)
    extra.pop("actor_type", None)
    extra.pop("actor_id", None)
    extra.pop("created_by", None)
    return extra


@router.post("/projects/{project_id}/style-guides", status_code=201)
def create_style_guide(
    request: Request, project_id: str, body: StyleGuideBody
) -> dict[str, Any]:
    try:
        guide = _service(request).create_guide(
            project_id=project_id,
            actor=_actor(request, body),
            payload=_guide_payload(body),
            created_by=body.created_by,
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(guide.to_public_dict())


@router.patch("/projects/{project_id}/style-guides/{guide_id}")
def patch_style_guide(
    request: Request, project_id: str, guide_id: str, body: StyleGuideBody
) -> dict[str, Any]:
    try:
        guide = _service(request).patch_guide(
            project_id=project_id,
            guide_id=guide_id,
            actor=_actor(request, body),
            payload=_guide_payload(body),
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(guide.to_public_dict())


@router.post("/projects/{project_id}/style-guides/{guide_id}/approve")
def approve_style_guide(
    request: Request,
    project_id: str,
    guide_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        guide = _service(request).approve_guide(
            project_id, guide_id, actor=_actor(request, body)
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(guide.to_public_dict())


@router.post("/projects/{project_id}/style-guides/{guide_id}/revise")
def revise_style_guide(
    request: Request,
    project_id: str,
    guide_id: str,
    body: StyleGuideBody | None = None,
) -> dict[str, Any]:
    payload = body or StyleGuideBody()
    try:
        guide = _service(request).revise_guide(
            project_id,
            guide_id,
            actor=_actor(request, payload),
            payload=_guide_payload(payload),
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(guide.to_public_dict())


@router.post("/projects/{project_id}/style-guides/{guide_id}/cancel")
def cancel_style_guide(
    request: Request,
    project_id: str,
    guide_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        guide = _service(request).cancel_guide(
            project_id, guide_id, actor=_actor(request, body)
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(guide.to_public_dict())


@router.post("/projects/{project_id}/style-guides/{guide_id}/fail")
def fail_style_guide(
    request: Request,
    project_id: str,
    guide_id: str,
    body: FailBody | None = None,
) -> dict[str, Any]:
    payload = body or FailBody()
    try:
        guide = _service(request).fail_guide(
            project_id,
            guide_id,
            actor=_actor(request, payload),
            reason=payload.reason,
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(guide.to_public_dict())


@router.get("/projects/{project_id}/style-guides")
def list_style_guides(request: Request, project_id: str) -> dict[str, Any]:
    try:
        items = _service(request).list_guides(project_id)
    except StyleServiceError as exc:
        _raise(exc)
    return {
        "items": [_envelope(item.to_public_dict()) for item in items],
        "is_canon": False,
        "is_approval": False,
        "is_canon_approval": False,
        "writes_canon": False,
        "auto_approved": False,
        "is_style_scoring": False,
    }


@router.get("/projects/{project_id}/style-guides/{guide_id}")
def get_style_guide(
    request: Request, project_id: str, guide_id: str
) -> dict[str, Any]:
    try:
        guide = _service(request).get_guide(project_id, guide_id)
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(guide.to_public_dict())


@router.post("/projects/{project_id}/style-samples", status_code=201)
def create_style_sample(
    request: Request, project_id: str, body: StyleSampleBody
) -> dict[str, Any]:
    try:
        sample = _service(request).create_sample(
            project_id=project_id,
            actor=_actor(request, body),
            payload=_sample_payload(body),
            created_by=body.created_by,
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(sample.to_public_dict())


@router.patch("/projects/{project_id}/style-samples/{sample_id}")
def patch_style_sample(
    request: Request, project_id: str, sample_id: str, body: StyleSampleBody
) -> dict[str, Any]:
    try:
        sample = _service(request).patch_sample(
            project_id=project_id,
            sample_id=sample_id,
            actor=_actor(request, body),
            payload=_sample_payload(body),
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(sample.to_public_dict())


@router.post("/projects/{project_id}/style-samples/{sample_id}/authorize")
def authorize_style_sample(
    request: Request,
    project_id: str,
    sample_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        sample = _service(request).authorize_sample(
            project_id, sample_id, actor=_actor(request, body)
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(sample.to_public_dict())


@router.post("/projects/{project_id}/style-samples/{sample_id}/revise")
def revise_style_sample(
    request: Request,
    project_id: str,
    sample_id: str,
    body: StyleSampleBody | None = None,
) -> dict[str, Any]:
    payload = body or StyleSampleBody()
    try:
        sample = _service(request).revise_sample(
            project_id,
            sample_id,
            actor=_actor(request, payload),
            payload=_sample_payload(payload),
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(sample.to_public_dict())


@router.post("/projects/{project_id}/style-samples/{sample_id}/cancel")
def cancel_style_sample(
    request: Request,
    project_id: str,
    sample_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        sample = _service(request).cancel_sample(
            project_id, sample_id, actor=_actor(request, body)
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(sample.to_public_dict())


@router.post("/projects/{project_id}/style-samples/{sample_id}/fail")
def fail_style_sample(
    request: Request,
    project_id: str,
    sample_id: str,
    body: FailBody | None = None,
) -> dict[str, Any]:
    payload = body or FailBody()
    try:
        sample = _service(request).fail_sample(
            project_id,
            sample_id,
            actor=_actor(request, payload),
            reason=payload.reason,
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(sample.to_public_dict())


@router.get("/projects/{project_id}/style-samples")
def list_style_samples(request: Request, project_id: str) -> dict[str, Any]:
    try:
        items = _service(request).list_samples(project_id)
    except StyleServiceError as exc:
        _raise(exc)
    return {
        "items": [_envelope(item.to_public_dict()) for item in items],
        "is_canon": False,
        "is_approval": False,
        "is_canon_approval": False,
        "writes_canon": False,
        "auto_approved": False,
        "is_style_scoring": False,
    }


@router.get("/projects/{project_id}/style-samples/{sample_id}")
def get_style_sample(
    request: Request, project_id: str, sample_id: str
) -> dict[str, Any]:
    try:
        sample = _service(request).get_sample(project_id, sample_id)
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(sample.to_public_dict())


@router.post("/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/style")
def associate_style_on_draft(
    request: Request,
    project_id: str,
    scene_id: str,
    revision_id: str,
    body: AssociateStyleBody,
) -> dict[str, Any]:
    try:
        draft = _service(request).associate_on_draft(
            project_id=project_id,
            scene_id=scene_id,
            revision_id=revision_id,
            actor=_actor(request, body),
            style_guide_revision_id=body.style_guide_revision_id,
            style_sample_ids=body.style_sample_ids,
        )
    except StyleServiceError as exc:
        _raise(exc)
    return _envelope(draft.to_public_dict())
