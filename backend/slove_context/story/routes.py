"""HTTP routes for Story Project / Story Spec (node 2.1)."""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)
from slove_context.story.service import StoryService, StoryServiceError

router = APIRouter(tags=["story-project"])


class CreateProjectBody(BaseModel):
    title: str = Field(min_length=1)
    language: str
    created_by: str | None = None


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


def _service(request: Request) -> StoryService:
    return StoryService(
        repository=request.app.state.repository,
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


def _raise(exc: StoryServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/projects", status_code=201)
def create_project(request: Request, body: CreateProjectBody) -> dict[str, Any]:
    try:
        project = _service(request).create_project(
            title=body.title,
            language=body.language,
            actor=_actor(request, ActorBody(created_by=body.created_by)),
            created_by=body.created_by,
        )
    except StoryServiceError as exc:
        _raise(exc)
    return project.to_public_dict()


@router.get("/projects/{project_id}")
def get_project(request: Request, project_id: str) -> dict[str, Any]:
    try:
        project = _service(request).get_project(project_id)
    except StoryServiceError as exc:
        _raise(exc)
    return project.to_public_dict()


@router.post("/projects/{project_id}/specs", status_code=201)
def create_spec_draft(
    request: Request, project_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    try:
        spec = _service(request).create_spec_draft(
            project_id=project_id,
            payload=body,
            actor=_actor(request, body),
        )
    except StoryServiceError as exc:
        _raise(exc)
    return spec.to_public_dict()


@router.get("/projects/{project_id}/specs/current")
def get_current_spec(request: Request, project_id: str) -> dict[str, Any]:
    try:
        spec = _service(request).get_current_spec(project_id)
    except StoryServiceError as exc:
        _raise(exc)
    return spec.to_public_dict()


@router.get("/projects/{project_id}/specs/{spec_id}")
def get_spec(request: Request, project_id: str, spec_id: str) -> dict[str, Any]:
    try:
        spec = _service(request).get_spec(project_id, spec_id)
    except StoryServiceError as exc:
        _raise(exc)
    return spec.to_public_dict()


@router.post("/projects/{project_id}/specs/{spec_id}/submit")
def submit_spec(
    request: Request,
    project_id: str,
    spec_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        spec = _service(request).submit_spec(project_id, spec_id, _actor(request, body))
    except StoryServiceError as exc:
        _raise(exc)
    return spec.to_public_dict()


@router.post("/projects/{project_id}/specs/{spec_id}/approve")
def approve_spec(
    request: Request,
    project_id: str,
    spec_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        spec = _service(request).approve_spec(
            project_id, spec_id, _actor(request, body)
        )
    except StoryServiceError as exc:
        _raise(exc)
    return spec.to_public_dict()


@router.get("/projects/{project_id}/specs/{spec_id}/versions")
def list_versions(request: Request, project_id: str, spec_id: str) -> dict[str, Any]:
    try:
        versions = _service(request).list_versions(project_id, spec_id)
    except StoryServiceError as exc:
        _raise(exc)
    return {
        "spec_id": spec_id,
        "project_id": project_id,
        "versions": [item.to_summary_dict() for item in versions],
    }


@router.post("/projects/{project_id}/specs/{spec_id}/drafts", status_code=201)
def create_next_draft(
    request: Request,
    project_id: str,
    spec_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    try:
        spec = _service(request).create_next_draft(
            project_id=project_id,
            spec_id=spec_id,
            payload=body,
            actor=_actor(request, body),
        )
    except StoryServiceError as exc:
        _raise(exc)
    return spec.to_public_dict()


@router.patch("/projects/{project_id}/specs/{spec_id}")
def patch_spec(
    request: Request,
    project_id: str,
    spec_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """In-place edit is allowed only for Draft. Approved Specs are rejected."""
    try:
        spec = _service(request).patch_spec(
            project_id=project_id,
            spec_id=spec_id,
            payload=body,
            actor=_actor(request, body),
        )
    except StoryServiceError as exc:
        _raise(exc)
    return spec.to_public_dict()
