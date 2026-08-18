"""HTTP routes for Candidate Change extraction jobs (node 4.1).

POST triggers one per-scene extract job against one immutable draft.
GET reads the job or the scene's candidates. Cancel is terminal and
does not delete. No Validate. No auto-approve. No Canon writes.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from slove_context.candidate_change.models import (
    DEFAULT_REPAIR_TASK_TYPE,
    DEFAULT_TASK_TYPE,
)
from slove_context.candidate_change.repository import CandidateChangeRepository
from slove_context.candidate_change.service import (
    CandidateChangeService,
    CandidateChangeServiceError,
)
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


def _actor(request: Request, body: TriggerJobBody | CancelBody | None = None) -> Actor:
    body_type = body.actor_type if body is not None else None
    body_id = None
    if isinstance(body, TriggerJobBody):
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
