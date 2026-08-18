"""HTTP routes for Style Validation (node 7.2).

POST /projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/style-validations
GET  .../style-validations
GET  .../style-validations/{validation_id}
POST .../style-validations/{validation_id}/cancel

Style findings do not block Canon submit. Not a 5.x Validation Run.
No production seed-status route. No review queue (7.3).
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)
from slove_context.style.repository import InMemoryStyleRepository, StyleRepository
from slove_context.style.service import StyleService
from slove_context.style_validation.repository import (
    InMemoryStyleValidationRepository,
    StyleValidationRepository,
)
from slove_context.style_validation.service import (
    StyleValidationService,
    StyleValidationServiceError,
)

router = APIRouter(tags=["style-validation"])


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class TriggerBody(ActorBody):
    style_guide_revision_id: str | None = None
    style_sample_ids: list[str] = Field(default_factory=list)
    thresholds: dict[str, Any] | None = None
    include_llm: bool = True
    imitate_author: str | None = None
    living_author: str | None = None

    model_config = {"extra": "allow"}


class CancelBody(ActorBody):
    pass


def _service(request: Request) -> StyleValidationService:
    styles: StyleRepository = (
        getattr(request.app.state, "style_repository", None)
        or InMemoryStyleRepository()
    )
    validations: StyleValidationRepository = (
        getattr(request.app.state, "style_validation_repository", None)
        or InMemoryStyleValidationRepository()
    )
    gateway: LlmGateway = getattr(request.app.state, "llm_gateway", None) or LlmGateway(
        FakeProvider(), audit_writer=request.app.state.audit_writer
    )
    return StyleValidationService(
        story_repository=request.app.state.repository,
        scene_repository=request.app.state.scene_repository,
        draft_repository=request.app.state.scene_draft_repository,
        style_repository=styles,
        validation_repository=validations,
        audit_writer=request.app.state.audit_writer,
        llm_gateway=gateway,
        style_service=StyleService(
            story_repository=request.app.state.repository,
            style_repository=styles,
            audit_writer=request.app.state.audit_writer,
            scene_repository=request.app.state.scene_repository,
            draft_repository=request.app.state.scene_draft_repository,
        ),
        auto_run=bool(getattr(request.app.state, "style_validation_auto_run", True)),
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


def _raise(exc: StyleValidationServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    payload.setdefault("is_canon", False)
    payload.setdefault("is_approval", False)
    payload.setdefault("is_canon_approval", False)
    payload.setdefault("writes_canon", False)
    payload.setdefault("auto_approved", False)
    payload.setdefault("blocks_canon_submit", False)
    payload.setdefault("is_validation_run", False)
    payload.setdefault("is_review_queue", False)
    return payload


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/style-validations",
    status_code=201,
)
def trigger_style_validation(
    request: Request,
    project_id: str,
    scene_id: str,
    revision_id: str,
    body: TriggerBody | None = None,
) -> dict[str, Any]:
    payload = body or TriggerBody()
    extra = payload.model_dump(exclude_unset=True)
    try:
        run = _service(request).trigger(
            project_id=project_id,
            scene_id=scene_id,
            revision_id=revision_id,
            actor=_actor(request, payload),
            style_guide_revision_id=payload.style_guide_revision_id,
            style_sample_ids=payload.style_sample_ids,
            thresholds=payload.thresholds,
            include_llm=payload.include_llm,
            extra=extra,
        )
    except StyleValidationServiceError as exc:
        _raise(exc)
    return _envelope(run.to_public_dict())


@router.get(
    "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/style-validations"
)
def list_style_validations(
    request: Request, project_id: str, scene_id: str, revision_id: str
) -> dict[str, Any]:
    try:
        items = _service(request).list_for_draft(project_id, scene_id, revision_id)
    except StyleValidationServiceError as exc:
        _raise(exc)
    return {
        "items": [_envelope(item.to_public_dict()) for item in items],
        "is_canon": False,
        "writes_canon": False,
        "blocks_canon_submit": False,
        "is_validation_run": False,
        "is_review_queue": False,
    }


@router.get(
    "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}"
    "/style-validations/{validation_id}"
)
def get_style_validation(
    request: Request,
    project_id: str,
    scene_id: str,
    revision_id: str,
    validation_id: str,
) -> dict[str, Any]:
    try:
        run = _service(request).get(project_id, scene_id, revision_id, validation_id)
    except StyleValidationServiceError as exc:
        _raise(exc)
    return _envelope(run.to_public_dict())


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}"
    "/style-validations/{validation_id}/cancel"
)
def cancel_style_validation(
    request: Request,
    project_id: str,
    scene_id: str,
    revision_id: str,
    validation_id: str,
    body: CancelBody | None = None,
) -> dict[str, Any]:
    try:
        run = _service(request).cancel(
            project_id,
            scene_id,
            revision_id,
            validation_id,
            actor=_actor(request, body),
        )
    except StyleValidationServiceError as exc:
        _raise(exc)
    return _envelope(run.to_public_dict())
