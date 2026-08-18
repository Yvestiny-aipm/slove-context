"""HTTP routes for the single-scene DAG orchestrator (node 8.3).

POST /projects/{project_id}/scenes/{scene_id}/dags
GET  /projects/{project_id}/dags/{dag_id}
GET  /projects/{project_id}/dags/{dag_id}/graph
POST .../dags/{dag_id}/advance
POST .../dags/{dag_id}/human-review
POST .../dags/{dag_id}/rerun
POST .../dags/{dag_id}/cancel

human_review and canon_commit wait. canon_commit uses 4.2 submit
only after a human 主编 approve. No production seed-status.
No 8.4 batch. No real model.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from slove_context.dags.deps import dag_services_from_state
from slove_context.dags.repository import DagRepository, InMemoryDagRepository
from slove_context.dags.service import DagService, DagServiceError
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)

router = APIRouter(tags=["scene-dags"])


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class CreateDagBody(ActorBody):
    snapshot_id: str
    rebuild_context_pack: bool = False
    start_from: str | None = None


class HumanReviewBody(ActorBody):
    decision: str
    reason_code: str


class RerunBody(ActorBody):
    from_node: str
    rebuild_context_pack: bool = False


def _service(request: Request) -> DagService:
    dags: DagRepository = (
        getattr(request.app.state, "dag_repository", None) or InMemoryDagRepository()
    )
    return DagService(
        story_repository=request.app.state.repository,
        dag_repository=dags,
        audit_writer=request.app.state.audit_writer,
        services=dag_services_from_state(request.app.state),
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


def _raise(exc: DagServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/projects/{project_id}/scenes/{scene_id}/dags")
def list_scene_dags(request: Request, project_id: str, scene_id: str) -> dict[str, Any]:
    try:
        items = _service(request).list_for_scene(project_id, scene_id)
    except DagServiceError as exc:
        _raise(exc)
    return {
        "items": [item.to_public_dict() for item in items],
        "writes_canon": False,
        "auto_approved": False,
        "auto_canon_commit": False,
    }


@router.post("/projects/{project_id}/scenes/{scene_id}/dags", status_code=201)
def create_scene_dag(
    request: Request, project_id: str, scene_id: str, body: CreateDagBody
) -> dict[str, Any]:
    try:
        dag = _service(request).create_dag(
            project_id=project_id,
            scene_id=scene_id,
            snapshot_id=body.snapshot_id,
            actor=_actor(request, body),
            rebuild_context_pack=body.rebuild_context_pack,
            start_from=body.start_from,
        )
    except DagServiceError as exc:
        _raise(exc)
    return dag.to_public_dict()


@router.get("/projects/{project_id}/dags/{dag_id}")
def get_scene_dag(request: Request, project_id: str, dag_id: str) -> dict[str, Any]:
    try:
        dag = _service(request).get_dag(project_id, dag_id)
    except DagServiceError as exc:
        _raise(exc)
    return dag.to_public_dict()


@router.get("/projects/{project_id}/dags/{dag_id}/graph")
def get_scene_dag_graph(
    request: Request, project_id: str, dag_id: str
) -> dict[str, Any]:
    try:
        return _service(request).graph(project_id, dag_id)
    except DagServiceError as exc:
        _raise(exc)


@router.post("/projects/{project_id}/dags/{dag_id}/advance")
def advance_scene_dag(
    request: Request, project_id: str, dag_id: str, body: ActorBody | None = None
) -> dict[str, Any]:
    try:
        dag = _service(request).advance(project_id, dag_id, actor=_actor(request, body))
    except DagServiceError as exc:
        _raise(exc)
    return dag.to_public_dict()


@router.post("/projects/{project_id}/dags/{dag_id}/human-review")
def human_review_scene_dag(
    request: Request, project_id: str, dag_id: str, body: HumanReviewBody
) -> dict[str, Any]:
    try:
        dag = _service(request).human_review(
            project_id,
            dag_id,
            actor=_actor(request, body),
            decision=body.decision,
            reason_code=body.reason_code,
        )
    except DagServiceError as exc:
        _raise(exc)
    return dag.to_public_dict()


@router.post("/projects/{project_id}/dags/{dag_id}/rerun")
def rerun_scene_dag(
    request: Request, project_id: str, dag_id: str, body: RerunBody
) -> dict[str, Any]:
    try:
        dag = _service(request).rerun(
            project_id,
            dag_id,
            actor=_actor(request, body),
            from_node=body.from_node,
            rebuild_context_pack=body.rebuild_context_pack,
        )
    except DagServiceError as exc:
        _raise(exc)
    return dag.to_public_dict()


@router.post("/projects/{project_id}/dags/{dag_id}/cancel")
def cancel_scene_dag(
    request: Request, project_id: str, dag_id: str, body: ActorBody | None = None
) -> dict[str, Any]:
    try:
        dag = _service(request).cancel(project_id, dag_id, actor=_actor(request, body))
    except DagServiceError as exc:
        _raise(exc)
    return {"item": dag.to_public_dict(), "kept": True, "writes_canon": False}
