"""HTTP routes for Scene / Chapter summary jobs (node 4.3).

Scene jobs summarize one existing Scene Draft revision.
Chapter jobs roll up existing Scene Summaries only.
No chapter-level prose generate. No auto-approve. No Canon writes.
Cancel is terminal and does not delete.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

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
from slove_context.summary.models import (
    DEFAULT_CHAPTER_TASK_TYPE,
    DEFAULT_SCENE_TASK_TYPE,
)
from slove_context.summary.repository import SummaryRepository
from slove_context.summary.service import SummaryService, SummaryServiceError

router = APIRouter(tags=["summaries"])


class TriggerSceneSummaryBody(BaseModel):
    draft_revision_id: str
    content_hash: str | None = None
    idempotency_key: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class TriggerChapterSummaryBody(BaseModel):
    idempotency_key: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class CancelBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None


def _service(request: Request) -> SummaryService:
    story: StoryRepository = request.app.state.repository
    scenes: SceneRepository = request.app.state.scene_repository
    drafts: SceneDraftRepository = request.app.state.scene_draft_repository
    summaries: SummaryRepository = request.app.state.summary_repository
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
    return SummaryService(
        story_repository=story,
        scene_service=scene_service,
        draft_repository=drafts,
        summary_repository=summaries,
        audit_writer=request.app.state.audit_writer,
        llm_gateway=gateway,
        scene_task_type=getattr(
            request.app.state, "scene_summary_task_type", DEFAULT_SCENE_TASK_TYPE
        ),
        chapter_task_type=getattr(
            request.app.state, "chapter_summary_task_type", DEFAULT_CHAPTER_TASK_TYPE
        ),
        auto_run=bool(getattr(request.app.state, "summary_auto_run", True)),
    )


def _actor(
    request: Request,
    body: TriggerSceneSummaryBody
    | TriggerChapterSummaryBody
    | CancelBody
    | None = None,
) -> Actor:
    body_type = body.actor_type if body is not None else None
    body_id = None
    if isinstance(body, (TriggerSceneSummaryBody, TriggerChapterSummaryBody)):
        body_id = body.actor_id or body.created_by
    elif body is not None:
        body_id = body.actor_id
    return resolve_actor(
        header_type=request.headers.get(ACTOR_TYPE_HEADER),
        header_id=request.headers.get(ACTOR_ID_HEADER),
        body_type=body_type,
        body_id=body_id,
    )


def _raise(exc: SummaryServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/projects/{project_id}/scenes/{scene_id}/summaries/jobs", status_code=201)
def trigger_scene_summary_job(
    request: Request,
    project_id: str,
    scene_id: str,
    body: TriggerSceneSummaryBody,
) -> dict[str, Any]:
    try:
        job = _service(request).trigger_scene_job(
            project_id=project_id,
            scene_id=scene_id,
            draft_revision_id=body.draft_revision_id,
            content_hash_value=body.content_hash,
            idempotency_key=body.idempotency_key,
            actor=_actor(request, body),
        )
    except SummaryServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.get("/projects/{project_id}/scene-summary-jobs/{job_id}")
def get_scene_summary_job(
    request: Request, project_id: str, job_id: str
) -> dict[str, Any]:
    try:
        job = _service(request).get_scene_job(project_id, job_id)
    except SummaryServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.post("/projects/{project_id}/scene-summary-jobs/{job_id}/cancel")
def cancel_scene_summary_job(
    request: Request, project_id: str, job_id: str, body: CancelBody | None = None
) -> dict[str, Any]:
    try:
        job = _service(request).cancel_scene_job(
            project_id, job_id, actor=_actor(request, body)
        )
    except SummaryServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.get("/projects/{project_id}/scenes/{scene_id}/summaries")
def list_scene_summaries(
    request: Request, project_id: str, scene_id: str
) -> dict[str, Any]:
    try:
        items = _service(request).list_scene_summaries(project_id, scene_id)
    except SummaryServiceError as exc:
        _raise(exc)
    return {
        "items": [item.to_public_dict() for item in items],
        "is_canon": False,
        "is_candidate_change": False,
        "auto_approved": False,
    }


@router.get("/projects/{project_id}/scenes/{scene_id}/summaries/{revision_id}")
def get_scene_summary(
    request: Request, project_id: str, scene_id: str, revision_id: str
) -> dict[str, Any]:
    try:
        summary = _service(request).get_scene_summary(project_id, scene_id, revision_id)
    except SummaryServiceError as exc:
        _raise(exc)
    return summary.to_public_dict()


@router.post(
    "/projects/{project_id}/chapters/{chapter_id}/summaries/jobs", status_code=201
)
def trigger_chapter_summary_job(
    request: Request,
    project_id: str,
    chapter_id: str,
    body: TriggerChapterSummaryBody | None = None,
) -> dict[str, Any]:
    payload = body or TriggerChapterSummaryBody()
    try:
        job = _service(request).trigger_chapter_job(
            project_id=project_id,
            chapter_id=chapter_id,
            idempotency_key=payload.idempotency_key,
            actor=_actor(request, payload),
        )
    except SummaryServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.get("/projects/{project_id}/chapter-summary-jobs/{job_id}")
def get_chapter_summary_job(
    request: Request, project_id: str, job_id: str
) -> dict[str, Any]:
    try:
        job = _service(request).get_chapter_job(project_id, job_id)
    except SummaryServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.post("/projects/{project_id}/chapter-summary-jobs/{job_id}/cancel")
def cancel_chapter_summary_job(
    request: Request, project_id: str, job_id: str, body: CancelBody | None = None
) -> dict[str, Any]:
    try:
        job = _service(request).cancel_chapter_job(
            project_id, job_id, actor=_actor(request, body)
        )
    except SummaryServiceError as exc:
        _raise(exc)
    return job.to_public_dict()


@router.get("/projects/{project_id}/chapters/{chapter_id}/summaries")
def list_chapter_summaries(
    request: Request, project_id: str, chapter_id: str
) -> dict[str, Any]:
    try:
        items = _service(request).list_chapter_summaries(project_id, chapter_id)
    except SummaryServiceError as exc:
        _raise(exc)
    return {
        "items": [item.to_public_dict() for item in items],
        "is_canon": False,
        "is_candidate_change": False,
        "auto_approved": False,
        "is_chapter_prose_generate": False,
    }


@router.get("/projects/{project_id}/chapters/{chapter_id}/summaries/{revision_id}")
def get_chapter_summary(
    request: Request, project_id: str, chapter_id: str, revision_id: str
) -> dict[str, Any]:
    try:
        summary = _service(request).get_chapter_summary(
            project_id, chapter_id, revision_id
        )
    except SummaryServiceError as exc:
        _raise(exc)
    return summary.to_public_dict()
