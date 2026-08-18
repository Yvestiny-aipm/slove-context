"""HTTP routes for Validation Runs (node 5.1).

POST /projects/{project_id}/validation-runs
GET  /projects/{project_id}/validation-runs/{run_id}
POST /projects/{project_id}/validation-runs/{run_id}/cancel
GET  /projects/{project_id}/validation-runs/{run_id}/report

Passed is not Approval and does not write Canon. No Repair Task.
No production seed-status route.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from slove_context.canon.service import CanonService
from slove_context.scene.service import SceneService
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)
from slove_context.validation.repository import (
    InMemoryValidationRepository,
    ValidationRepository,
)
from slove_context.validation.rules import DeterministicRuleEngine, RuleEngine
from slove_context.validation.service import ValidationService, ValidationServiceError

router = APIRouter(tags=["validation-run"])


class TriggerRunBody(BaseModel):
    scene_id: str | None = None
    candidate_ids: list[str] | None = None
    snapshot_id: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class CancelBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None


def _service(request: Request) -> ValidationService:
    validation_repo: ValidationRepository = (
        getattr(request.app.state, "validation_repository", None)
        or InMemoryValidationRepository()
    )
    rule_engine: RuleEngine = (
        getattr(request.app.state, "validation_rule_engine", None)
        or DeterministicRuleEngine()
    )
    scene_service = SceneService(
        story_repository=request.app.state.repository,
        scene_repository=request.app.state.scene_repository,
        audit_writer=request.app.state.audit_writer,
    )
    return ValidationService(
        story_repository=request.app.state.repository,
        scene_service=scene_service,
        extract_repository=request.app.state.candidate_change_repository,
        canon_service=CanonService(
            story_repository=request.app.state.repository,
            canon_repository=request.app.state.canon_repository,
            audit_writer=request.app.state.audit_writer,
        ),
        validation_repository=validation_repo,
        audit_writer=request.app.state.audit_writer,
        rule_engine=rule_engine,
        auto_run=bool(getattr(request.app.state, "validation_auto_run", True)),
    )


def _actor(request: Request, body: TriggerRunBody | CancelBody | None = None) -> Actor:
    body_type = body.actor_type if body is not None else None
    body_id = None
    if isinstance(body, TriggerRunBody):
        body_id = body.actor_id or body.created_by
    elif body is not None:
        body_id = body.actor_id
    return resolve_actor(
        header_type=request.headers.get(ACTOR_TYPE_HEADER),
        header_id=request.headers.get(ACTOR_ID_HEADER),
        body_type=body_type,
        body_id=body_id,
    )


def _raise(exc: ValidationServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/projects/{project_id}/validation-runs", status_code=201)
def trigger_validation_run(
    request: Request, project_id: str, body: TriggerRunBody | None = None
) -> dict[str, Any]:
    payload = body or TriggerRunBody()
    try:
        run = _service(request).trigger_run(
            project_id=project_id,
            actor=_actor(request, payload),
            scene_id=payload.scene_id,
            candidate_ids=payload.candidate_ids,
            snapshot_id=payload.snapshot_id,
        )
    except ValidationServiceError as exc:
        _raise(exc)
    return run.to_public_dict()


@router.get("/projects/{project_id}/validation-runs/{run_id}")
def get_validation_run(
    request: Request, project_id: str, run_id: str
) -> dict[str, Any]:
    try:
        run = _service(request).get_run(project_id, run_id)
    except ValidationServiceError as exc:
        _raise(exc)
    return run.to_public_dict()


@router.post("/projects/{project_id}/validation-runs/{run_id}/cancel")
def cancel_validation_run(
    request: Request,
    project_id: str,
    run_id: str,
    body: CancelBody | None = None,
) -> dict[str, Any]:
    try:
        run = _service(request).cancel_run(
            project_id, run_id, actor=_actor(request, body)
        )
    except ValidationServiceError as exc:
        _raise(exc)
    return run.to_public_dict()


@router.get("/projects/{project_id}/validation-runs/{run_id}/report")
def get_validation_report(
    request: Request, project_id: str, run_id: str
) -> dict[str, Any]:
    try:
        report = _service(request).get_report(project_id, run_id)
    except ValidationServiceError as exc:
        _raise(exc)
    return report.to_public_dict()
