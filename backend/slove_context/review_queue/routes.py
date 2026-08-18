"""HTTP routes for the human review queue (node 7.3).

POST /projects/{project_id}/review-queue/items
GET  /projects/{project_id}/review-queue
GET  /projects/{project_id}/review-queue/{item_id}
POST .../approve | reject | request-revision | escalate
GET  .../export

Only human 主编 may take decisions. Approve on a Candidate Change
reuses 4.2 approve (not submit). No production seed-status route.
No chapter-level generate. No 8.x workers.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from slove_context.canon.service import CanonService
from slove_context.review_queue.models import (
    ACTION_APPROVE,
    ACTION_ESCALATE,
    ACTION_REJECT,
    ACTION_REQUEST_REVISION,
)
from slove_context.review_queue.repository import (
    InMemoryReviewQueueRepository,
    ReviewQueueRepository,
)
from slove_context.review_queue.service import (
    ReviewQueueService,
    ReviewQueueServiceError,
)
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)

router = APIRouter(tags=["review-queue"])


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class EnqueueBody(ActorBody):
    subject_type: str | None = None
    subject_id: str | None = None
    is_blocker: bool | None = None
    chapter_id: str | None = None


class DecisionBody(ActorBody):
    reason_code: str | None = None
    comment: str | None = None


def _service(request: Request) -> ReviewQueueService:
    queue: ReviewQueueRepository = (
        getattr(request.app.state, "review_queue_repository", None)
        or InMemoryReviewQueueRepository()
    )
    return ReviewQueueService(
        story_repository=request.app.state.repository,
        scene_repository=request.app.state.scene_repository,
        scene_plan_repository=request.app.state.scene_plan_repository,
        scene_draft_repository=request.app.state.scene_draft_repository,
        candidate_change_repository=(request.app.state.candidate_change_repository),
        validation_repository=request.app.state.validation_repository,
        repair_repository=request.app.state.repair_repository,
        style_validation_repository=(request.app.state.style_validation_repository),
        review_queue_repository=queue,
        audit_writer=request.app.state.audit_writer,
        canon_service=CanonService(
            story_repository=request.app.state.repository,
            canon_repository=request.app.state.canon_repository,
            audit_writer=request.app.state.audit_writer,
        ),
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


def _raise(exc: ReviewQueueServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _public_item(service: ReviewQueueService, item: Any) -> dict[str, Any]:
    payload = item.to_public_dict(service.decisions_for(item))
    payload.setdefault("writes_canon", False)
    payload.setdefault("auto_approved", False)
    payload.setdefault("is_canon", False)
    payload.setdefault("is_canon_approval", False)
    payload.setdefault("blocks_canon_submit", False)
    return payload


def _parse_blocker(raw: str | None) -> bool | None:
    if raw is None or not raw.strip():
        return None
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y"}:
        return True
    if value in {"0", "false", "no", "n"}:
        return False
    raise HTTPException(
        status_code=422,
        detail={
            "error": "invalid_blocker_filter",
            "message": "blocker must be true or false.",
        },
    )


@router.post("/projects/{project_id}/review-queue/items", status_code=201)
def enqueue_review_item(
    request: Request, project_id: str, body: EnqueueBody | None = None
) -> dict[str, Any]:
    payload = body or EnqueueBody()
    service = _service(request)
    try:
        item = service.enqueue(
            project_id=project_id,
            actor=_actor(request, payload),
            body=payload.model_dump(),
        )
    except ReviewQueueServiceError as exc:
        _raise(exc)
    return _public_item(service, item)


@router.get("/projects/{project_id}/review-queue")
def list_review_queue(
    request: Request,
    project_id: str,
    blocker: str | None = Query(default=None),
    chapter_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    task_status: str | None = Query(default=None),
    sort: str | None = Query(default=None),
) -> dict[str, Any]:
    service = _service(request)
    try:
        items = service.list_items(
            project_id,
            blocker=_parse_blocker(blocker),
            chapter_id=chapter_id,
            status=status or task_status,
            sort=sort,
        )
    except ReviewQueueServiceError as exc:
        _raise(exc)
    return {
        "items": [_public_item(service, item) for item in items],
        "writes_canon": False,
        "auto_approved": False,
        "is_canon": False,
        "is_canon_approval": False,
        "blocks_canon_submit": False,
    }


@router.get("/projects/{project_id}/review-queue/{item_id}")
def get_review_item(request: Request, project_id: str, item_id: str) -> dict[str, Any]:
    service = _service(request)
    try:
        item = service.get_item(project_id, item_id)
    except ReviewQueueServiceError as exc:
        _raise(exc)
    return _public_item(service, item)


@router.post("/projects/{project_id}/review-queue/{item_id}/approve")
def approve_review_item(
    request: Request,
    project_id: str,
    item_id: str,
    body: DecisionBody | None = None,
) -> dict[str, Any]:
    return _decide(request, project_id, item_id, ACTION_APPROVE, body)


@router.post("/projects/{project_id}/review-queue/{item_id}/reject")
def reject_review_item(
    request: Request,
    project_id: str,
    item_id: str,
    body: DecisionBody | None = None,
) -> dict[str, Any]:
    return _decide(request, project_id, item_id, ACTION_REJECT, body)


@router.post("/projects/{project_id}/review-queue/{item_id}/request-revision")
def request_revision_review_item(
    request: Request,
    project_id: str,
    item_id: str,
    body: DecisionBody | None = None,
) -> dict[str, Any]:
    return _decide(request, project_id, item_id, ACTION_REQUEST_REVISION, body)


@router.post("/projects/{project_id}/review-queue/{item_id}/escalate")
def escalate_review_item(
    request: Request,
    project_id: str,
    item_id: str,
    body: DecisionBody | None = None,
) -> dict[str, Any]:
    return _decide(request, project_id, item_id, ACTION_ESCALATE, body)


@router.post("/projects/{project_id}/review-queue/{item_id}/cancel")
def cancel_review_item(
    request: Request,
    project_id: str,
    item_id: str,
    body: DecisionBody | None = None,
) -> dict[str, Any]:
    payload = body or DecisionBody()
    service = _service(request)
    try:
        item, decision = service.cancel(
            project_id=project_id,
            item_id=item_id,
            actor=_actor(request, payload),
            body=payload.model_dump(),
        )
    except ReviewQueueServiceError as exc:
        _raise(exc)
    return {
        "item": _public_item(service, item),
        "decision": decision.to_public_dict(),
        "writes_canon": False,
        "auto_approved": False,
        "is_canon": False,
        "kept": True,
    }


@router.get("/projects/{project_id}/review-queue/{item_id}/export")
def export_review_pack(
    request: Request, project_id: str, item_id: str
) -> dict[str, Any]:
    service = _service(request)
    try:
        pack = service.export_pack(project_id, item_id)
    except ReviewQueueServiceError as exc:
        _raise(exc)
    return pack


def _decide(
    request: Request,
    project_id: str,
    item_id: str,
    action: str,
    body: DecisionBody | None,
) -> dict[str, Any]:
    payload = body or DecisionBody()
    service = _service(request)
    try:
        item, decision = service.decide(
            project_id=project_id,
            item_id=item_id,
            action=action,
            actor=_actor(request, payload),
            body=payload.model_dump(),
        )
    except ReviewQueueServiceError as exc:
        _raise(exc)
    return {
        "item": _public_item(service, item),
        "decision": decision.to_public_dict(),
        "writes_canon": False,
        "auto_approved": False,
        "auto_submitted": False,
        "is_canon": False,
        "is_canon_approval": False,
        "blocks_canon_submit": False,
        "style_report_approve_is_canon_approve": False,
        "canon_commit_path": item.to_public_dict().get("canon_commit_path"),
    }
