"""HTTP routes for the minimal Canon API (node 2.2 + 2.3).

No PATCH that mutates an Active fact body.
Node 2.3: snapshot create / freeze / facts / diff / replay.
Snapshot queries never replace live GET /canon-facts.
No Scene Card, Context Pack, or generator.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from slove_context.canon.service import CanonService, CanonServiceError
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)

router = APIRouter(tags=["canon"])


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class CreateEntityBody(ActorBody):
    name: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)


class CreateEvidenceBody(ActorBody):
    source_type: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    scene_id: str | None = None


class CreateFactBody(ActorBody):
    entity_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    value_json: Any
    effective_story_time: str = Field(min_length=1)
    valid_from_scene_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    status: str | None = None


class SupersedeFactBody(ActorBody):
    entity_id: str | None = None
    predicate: str | None = None
    value_json: Any
    effective_story_time: str = Field(min_length=1)
    valid_from_scene_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    status: str | None = None


class CreateSnapshotBody(ActorBody):
    as_of_scene_seq: int | None = None
    as_of_story_time: str | None = None
    note: str | None = None


def _service(request: Request) -> CanonService:
    return CanonService(
        story_repository=request.app.state.repository,
        canon_repository=request.app.state.canon_repository,
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


def _raise(exc: CanonServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/projects/{project_id}/entities", status_code=201)
def create_entity(
    request: Request, project_id: str, body: CreateEntityBody
) -> dict[str, Any]:
    try:
        entity = _service(request).create_entity(
            project_id=project_id,
            name=body.name,
            entity_type=body.entity_type,
            actor=_actor(request, body),
            created_by=body.created_by,
        )
    except CanonServiceError as exc:
        _raise(exc)
    return entity.to_public_dict()


@router.get("/projects/{project_id}/entities")
def list_entities(request: Request, project_id: str) -> dict[str, Any]:
    try:
        entities = _service(request).list_entities(project_id)
    except CanonServiceError as exc:
        _raise(exc)
    return {
        "project_id": project_id,
        "entities": [item.to_public_dict() for item in entities],
    }


@router.post("/projects/{project_id}/evidence", status_code=201)
def create_evidence(
    request: Request, project_id: str, body: CreateEvidenceBody
) -> dict[str, Any]:
    try:
        evidence = _service(request).create_evidence(
            project_id=project_id,
            source_type=body.source_type,
            quote=body.quote,
            actor=_actor(request, body),
            scene_id=body.scene_id,
            created_by=body.created_by,
        )
    except CanonServiceError as exc:
        _raise(exc)
    return evidence.to_public_dict()


@router.post("/projects/{project_id}/canon-facts", status_code=201)
def create_fact(
    request: Request, project_id: str, body: CreateFactBody
) -> dict[str, Any]:
    try:
        fact = _service(request).create_fact(
            project_id=project_id,
            payload=body.model_dump(),
            actor=_actor(request, body),
        )
    except CanonServiceError as exc:
        _raise(exc)
    return fact.to_public_dict()


@router.get("/projects/{project_id}/canon-facts")
def list_facts(
    request: Request,
    project_id: str,
    entity_id: str | None = None,
    predicate: str | None = None,
    as_of_story_time: str | None = None,
) -> dict[str, Any]:
    try:
        facts = _service(request).list_facts_in_effect(
            project_id=project_id,
            entity_id=entity_id,
            predicate=predicate,
            as_of_story_time=as_of_story_time,
        )
    except CanonServiceError as exc:
        _raise(exc)
    return {
        "project_id": project_id,
        "facts": [item.to_public_dict() for item in facts],
    }


@router.post("/projects/{project_id}/canon-facts/{fact_id}/approve")
def approve_fact(
    request: Request,
    project_id: str,
    fact_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        fact = _service(request).approve_fact(
            project_id, fact_id, _actor(request, body)
        )
    except CanonServiceError as exc:
        _raise(exc)
    return fact.to_public_dict()


@router.post("/projects/{project_id}/canon-facts/{fact_id}/abandon")
def abandon_fact(
    request: Request,
    project_id: str,
    fact_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        fact = _service(request).abandon_fact(
            project_id, fact_id, _actor(request, body)
        )
    except CanonServiceError as exc:
        _raise(exc)
    return fact.to_public_dict()


@router.post("/projects/{project_id}/canon-facts/{fact_id}/supersede")
def supersede_fact(
    request: Request,
    project_id: str,
    fact_id: str,
    body: SupersedeFactBody,
) -> dict[str, Any]:
    try:
        result = _service(request).supersede_fact(
            project_id=project_id,
            fact_id=fact_id,
            payload=body.model_dump(),
            actor=_actor(request, body),
        )
    except CanonServiceError as exc:
        _raise(exc)
    return {
        "superseded": result["old"].to_public_dict(),
        "fact": result["new"].to_public_dict(),
    }


@router.post("/projects/{project_id}/canon-snapshots", status_code=201)
def create_snapshot(
    request: Request, project_id: str, body: CreateSnapshotBody
) -> dict[str, Any]:
    try:
        snapshot = _service(request).create_snapshot(
            project_id=project_id,
            payload=body.model_dump(),
            actor=_actor(request, body),
        )
    except CanonServiceError as exc:
        _raise(exc)
    return snapshot.to_public_dict()


@router.post("/projects/{project_id}/canon-snapshots/{snapshot_id}/freeze")
def freeze_snapshot(
    request: Request,
    project_id: str,
    snapshot_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        snapshot = _service(request).freeze_snapshot(
            project_id, snapshot_id, _actor(request, body)
        )
    except CanonServiceError as exc:
        _raise(exc)
    return snapshot.to_public_dict()


@router.get("/projects/{project_id}/canon-snapshots/{snapshot_id}")
def get_snapshot(request: Request, project_id: str, snapshot_id: str) -> dict[str, Any]:
    try:
        snapshot = _service(request).get_snapshot(project_id, snapshot_id)
    except CanonServiceError as exc:
        _raise(exc)
    return snapshot.to_public_dict()


@router.get("/projects/{project_id}/canon-snapshots/{snapshot_id}/facts")
def list_snapshot_facts(
    request: Request, project_id: str, snapshot_id: str
) -> dict[str, Any]:
    try:
        facts = _service(request).list_snapshot_facts(project_id, snapshot_id)
    except CanonServiceError as exc:
        _raise(exc)
    return {
        "project_id": project_id,
        "snapshot_id": snapshot_id,
        "facts": [item.to_public_dict() for item in facts],
    }


@router.get(
    "/projects/{project_id}/canon-snapshots/{snapshot_id_a}/diff/{snapshot_id_b}"
)
def diff_snapshots(
    request: Request,
    project_id: str,
    snapshot_id_a: str,
    snapshot_id_b: str,
) -> dict[str, Any]:
    try:
        result = _service(request).diff_snapshots(
            project_id, snapshot_id_a, snapshot_id_b
        )
    except CanonServiceError as exc:
        _raise(exc)
    return {
        "project_id": project_id,
        "from_snapshot_id": snapshot_id_a,
        "to_snapshot_id": snapshot_id_b,
        "added": [item.to_public_dict() for item in result["added"]],
        "removed": [item.to_public_dict() for item in result["removed"]],
        "superseded": [item.to_public_dict() for item in result["superseded"]],
    }


@router.get("/projects/{project_id}/canon-replay")
def replay_canon(
    request: Request,
    project_id: str,
    snapshot_id: str,
    scene_id: str | None = None,
    as_of_story_time: str | None = None,
) -> dict[str, Any]:
    try:
        facts = _service(request).replay_snapshot(
            project_id=project_id,
            snapshot_id=snapshot_id,
            scene_id=scene_id.strip() if scene_id else None,
            as_of_story_time=(as_of_story_time.strip() if as_of_story_time else None),
        )
    except CanonServiceError as exc:
        _raise(exc)
    return {
        "project_id": project_id,
        "snapshot_id": snapshot_id,
        "scene_id": scene_id,
        "as_of_story_time": as_of_story_time,
        "facts": [item.to_public_dict() for item in facts],
    }
