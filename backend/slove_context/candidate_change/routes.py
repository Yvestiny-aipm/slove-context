"""HTTP routes for Candidate Change extraction and human verdicts.

Node 4.1: POST extract job; GET job or the scene's candidates. Cancel
is terminal and does not delete.

Node 4.2: human approve / reject / submit. Approve records a verdict
only and does not write Canon. Submit writes Canon (create or
supersede). No auto-approve. No Validate / Validation Run.
"""

from __future__ import annotations

from typing import Any, NoReturn, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from slove_context.candidate_change.approval_service import ApprovalService
from slove_context.candidate_change.models import (
    DEFAULT_REPAIR_TASK_TYPE,
    DEFAULT_TASK_TYPE,
    CandidateChange,
)
from slove_context.candidate_change.repository import CandidateChangeRepository
from slove_context.candidate_change.service import (
    CandidateChangeService,
    CandidateChangeServiceError,
)
from slove_context.canon.models import CanonFact
from slove_context.canon.service import CanonService
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway
from slove_context.scene.repository import SceneRepository
from slove_context.scene.service import SceneService
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)
from slove_context.story.repository import StoryRepository

router = APIRouter(tags=["candidate-change"])


class TriggerJobBody(BaseModel):
    idempotency_key: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class CancelBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None


class DecisionBody(BaseModel):
    """Incoming Approval Decision fields. Assembled then schema-validated."""

    schema_version: str | None = None
    id: str | None = None
    project_id: str | None = None
    created_at: str | None = None
    created_by: str | None = None
    candidate_change_id: str | None = None
    decision: str | None = None
    reason: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None


class SubmitBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None
    entity_id: str | None = None
    entity_type: str | None = None
    supersede_fact_id: str | None = None


class SeedStatusBody(BaseModel):
    """Test helper only: skip Validate (5.x). Not approve or submit."""

    status: str
    actor_type: str | None = None
    actor_id: str | None = None


def _service(request: Request) -> CandidateChangeService:
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
        auto_run=bool(getattr(request.app.state, "extract_auto_run", True)),
    )


def _approval_service(request: Request) -> ApprovalService:
    return ApprovalService(
        story_repository=request.app.state.repository,
        extract_repository=request.app.state.candidate_change_repository,
        canon_service=CanonService(
            story_repository=request.app.state.repository,
            canon_repository=request.app.state.canon_repository,
            audit_writer=request.app.state.audit_writer,
        ),
        audit_writer=request.app.state.audit_writer,
    )


def _actor(
    request: Request,
    body: TriggerJobBody
    | CancelBody
    | DecisionBody
    | SubmitBody
    | SeedStatusBody
    | None = None,
) -> Actor:
    body_type = body.actor_type if body is not None else None
    body_id = None
    if isinstance(body, (TriggerJobBody, DecisionBody, SubmitBody)):
        body_id = body.actor_id or body.created_by
    elif body is not None:
        body_id = body.actor_id
    return resolve_actor(
        header_type=request.headers.get(ACTOR_TYPE_HEADER),
        header_id=request.headers.get(ACTOR_ID_HEADER),
        body_type=body_type,
        body_id=body_id,
    )


def _raise(exc: CandidateChangeServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/extract-jobs",
    status_code=201,
)
def trigger_extract_job(
    request: Request,
    project_id: str,
    scene_id: str,
    revision_id: str,
    body: TriggerJobBody | None = None,
) -> dict[str, Any]:
    payload = body or TriggerJobBody()
    try:
        job = _service(request).trigger_job(
            project_id=project_id,
            scene_id=scene_id,
            revision_id=revision_id,
            idempotency_key=payload.idempotency_key,
            actor=_actor(request, payload),
        )
    except CandidateChangeServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.get("/projects/{project_id}/extract-jobs/{job_id}")
def get_extract_job(request: Request, project_id: str, job_id: str) -> dict[str, Any]:
    try:
        job = _service(request).get_job(project_id, job_id)
    except CandidateChangeServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.post("/projects/{project_id}/extract-jobs/{job_id}/cancel")
def cancel_extract_job(
    request: Request, project_id: str, job_id: str, body: CancelBody | None = None
) -> dict[str, Any]:
    try:
        job = _service(request).cancel_job(
            project_id, job_id, actor=_actor(request, body)
        )
    except CandidateChangeServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.get("/projects/{project_id}/scenes/{scene_id}/candidate-changes")
def list_candidate_changes(
    request: Request, project_id: str, scene_id: str
) -> dict[str, Any]:
    try:
        items = _service(request).list_candidates(project_id, scene_id)
    except CandidateChangeServiceError as exc:
        _raise(exc)
    return {
        "items": [item.to_public_dict() for item in items],
        "is_canon": False,
        "auto_approved": False,
        "writes_canon": False,
    }


@router.get("/projects/{project_id}/candidate-changes/{candidate_id}")
def get_candidate_change(
    request: Request, project_id: str, candidate_id: str
) -> dict[str, Any]:
    try:
        item = _approval_service(request).get_candidate(project_id, candidate_id)
    except CandidateChangeServiceError as exc:
        _raise(exc)
    return item.to_public_dict()


@router.post("/projects/{project_id}/candidate-changes/{candidate_id}/seed-status")
def seed_candidate_status(
    request: Request,
    project_id: str,
    candidate_id: str,
    body: SeedStatusBody,
) -> dict[str, Any]:
    """Test/admin helper: set AwaitingVerdict (or other pre-verdict status).

    Skips Validate (5.x). Does not approve, submit, or write Canon.
    """
    try:
        item = _approval_service(request).seed_status(
            project_id, candidate_id, body.status
        )
    except CandidateChangeServiceError as exc:
        _raise(exc)
    return item.to_public_dict()


@router.post("/projects/{project_id}/candidate-changes/{candidate_id}/approve")
def approve_candidate(
    request: Request,
    project_id: str,
    candidate_id: str,
    body: DecisionBody | None = None,
) -> dict[str, Any]:
    payload = body or DecisionBody()
    try:
        candidate, decision = _approval_service(request).approve(
            project_id=project_id,
            candidate_id=candidate_id,
            actor=_actor(request, payload),
            body=payload.model_dump(),
        )
    except CandidateChangeServiceError as exc:
        _raise(exc)
    return {
        "candidate": candidate.to_public_dict(),
        "approval_decision": decision,
        "writes_canon": False,
        "auto_approved": False,
        "auto_submitted": False,
    }


@router.post("/projects/{project_id}/candidate-changes/{candidate_id}/reject")
def reject_candidate(
    request: Request,
    project_id: str,
    candidate_id: str,
    body: DecisionBody | None = None,
) -> dict[str, Any]:
    payload = body or DecisionBody()
    try:
        candidate, decision = _approval_service(request).reject(
            project_id=project_id,
            candidate_id=candidate_id,
            actor=_actor(request, payload),
            body=payload.model_dump(),
        )
    except CandidateChangeServiceError as exc:
        _raise(exc)
    return {
        "candidate": candidate.to_public_dict(),
        "approval_decision": decision,
        "writes_canon": False,
        "auto_approved": False,
    }


@router.post("/projects/{project_id}/candidate-changes/{candidate_id}/submit")
def submit_candidate(
    request: Request,
    project_id: str,
    candidate_id: str,
    body: SubmitBody | None = None,
) -> dict[str, Any]:
    payload = body or SubmitBody()
    try:
        result = _approval_service(request).submit(
            project_id=project_id,
            candidate_id=candidate_id,
            actor=_actor(request, payload),
            body=payload.model_dump(),
        )
    except CandidateChangeServiceError as exc:
        _raise(exc)
    candidate = cast(CandidateChange, result["candidate"])
    fact = cast(CanonFact, result["canon_fact"])
    superseded = result["superseded"]
    superseded_fact = superseded if isinstance(superseded, CanonFact) else None
    return {
        "candidate": candidate.to_public_dict(),
        "canon_fact": fact.to_public_dict(),
        "superseded": (
            superseded_fact.to_public_dict() if superseded_fact is not None else None
        ),
        "writes_canon": True,
        "auto_approved": False,
        "auto_submitted": False,
        "is_canon_fact": False,
    }
