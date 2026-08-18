"""HTTP routes for Scene Card / order / dependencies (node 3.1).

Arcs and chapters are structure containers only. There is no
chapter-level or book-level generate endpoint. Scene Plan / Scene Draft
generation is node 3.3 and is not implemented.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from slove_context.scene.service import SceneService, SceneServiceError
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)

router = APIRouter(tags=["scene-card"])


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class CreateArcBody(ActorBody):
    title: str = Field(min_length=1)
    sort_order: int | None = None


class CreateChapterBody(ActorBody):
    arc_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    sort_order: int | None = None


class SetDependenciesBody(ActorBody):
    depends_on: list[str] = Field(default_factory=list)


def _service(request: Request) -> SceneService:
    return SceneService(
        story_repository=request.app.state.repository,
        scene_repository=request.app.state.scene_repository,
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


def _raise(exc: SceneServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/projects/{project_id}/arcs", status_code=201)
def create_arc(
    request: Request, project_id: str, body: CreateArcBody
) -> dict[str, Any]:
    try:
        arc = _service(request).create_arc(
            project_id=project_id,
            title=body.title,
            sort_order=body.sort_order,
            actor=_actor(request, body),
            created_by=body.created_by,
        )
    except SceneServiceError as exc:
        _raise(exc)
    return arc.to_public_dict()


@router.post("/projects/{project_id}/chapters", status_code=201)
def create_chapter(
    request: Request, project_id: str, body: CreateChapterBody
) -> dict[str, Any]:
    try:
        chapter = _service(request).create_chapter(
            project_id=project_id,
            arc_id=body.arc_id,
            title=body.title,
            sort_order=body.sort_order,
            actor=_actor(request, body),
            created_by=body.created_by,
        )
    except SceneServiceError as exc:
        _raise(exc)
    return chapter.to_public_dict()


@router.post("/projects/{project_id}/scenes", status_code=201)
def create_scene(
    request: Request, project_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    try:
        service = _service(request)
        scene = service.create_scene(
            project_id=project_id,
            payload=body,
            actor=_actor(request, body),
        )
    except SceneServiceError as exc:
        _raise(exc)
    return service.public_scene(scene)


@router.get("/projects/{project_id}/scenes/generatable")
def list_generatable(request: Request, project_id: str) -> dict[str, Any]:
    try:
        service = _service(request)
        scenes = service.list_generatable(project_id)
    except SceneServiceError as exc:
        _raise(exc)
    return {
        "project_id": project_id,
        "scenes": [service.public_scene(item) for item in scenes],
    }


@router.get("/projects/{project_id}/scenes")
def list_scenes(request: Request, project_id: str) -> dict[str, Any]:
    try:
        service = _service(request)
        scenes = service.list_scenes(project_id)
    except SceneServiceError as exc:
        _raise(exc)
    return {
        "project_id": project_id,
        "scenes": [service.public_scene(item) for item in scenes],
    }


@router.get("/projects/{project_id}/scenes/{scene_id}")
def get_scene(request: Request, project_id: str, scene_id: str) -> dict[str, Any]:
    try:
        service = _service(request)
        scene = service.get_scene(project_id, scene_id)
    except SceneServiceError as exc:
        _raise(exc)
    return service.public_scene(scene)


@router.patch("/projects/{project_id}/scenes/{scene_id}")
def patch_scene(
    request: Request, project_id: str, scene_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    try:
        service = _service(request)
        scene = service.patch_scene(
            project_id=project_id,
            scene_id=scene_id,
            payload=body,
            actor=_actor(request, body),
        )
    except SceneServiceError as exc:
        _raise(exc)
    return service.public_scene(scene)


@router.post("/projects/{project_id}/scenes/{scene_id}/approve")
def approve_scene(
    request: Request,
    project_id: str,
    scene_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        service = _service(request)
        scene = service.approve_scene(project_id, scene_id, _actor(request, body))
    except SceneServiceError as exc:
        _raise(exc)
    return service.public_scene(scene)


@router.put("/projects/{project_id}/scenes/{scene_id}/dependencies")
def set_dependencies(
    request: Request,
    project_id: str,
    scene_id: str,
    body: SetDependenciesBody,
) -> dict[str, Any]:
    try:
        service = _service(request)
        scene = service.set_dependencies(
            project_id=project_id,
            scene_id=scene_id,
            depends_on=body.depends_on,
            actor=_actor(request, body),
        )
    except SceneServiceError as exc:
        _raise(exc)
    return service.list_dependencies(project_id, scene.id)


@router.get("/projects/{project_id}/scenes/{scene_id}/dependencies")
def get_dependencies(
    request: Request, project_id: str, scene_id: str
) -> dict[str, Any]:
    try:
        return _service(request).list_dependencies(project_id, scene_id)
    except SceneServiceError as exc:
        _raise(exc)
