"""HTTP routes for release checks and formal book export (node 9.3).

POST /projects/{project_id}/release-checks
GET  /projects/{project_id}/release-checks
GET  /projects/{project_id}/release-checks/{check_id}
POST /projects/{project_id}/release-checks/{check_id}/cancel
GET  /projects/{project_id}/release-checks/{check_id}/manifest
PATCH/PUT .../manifest  (always 409)
POST /projects/{project_id}/release-checks/{check_id}/export
POST /projects/{project_id}/release-due-items
POST /projects/{project_id}/release-due-items/{due_item_id}/handle
POST /projects/{project_id}/release-due-items/{due_item_id}/waive
POST /projects/{project_id}/release-safety-checks
POST /projects/{project_id}/release-waivers
POST /projects/{project_id}/release-checks/{check_id}/approve-canon  (always 403)
POST /projects/{project_id}/release-checks/{check_id}/submit-canon   (always 403)

No production seed-status. No real models. Not 10.x.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from slove_context.release.repository import InMemoryReleaseRepository
from slove_context.release.service import ReleaseService, ReleaseServiceError
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)

router = APIRouter(tags=["release"])


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class RunCheckBody(ActorBody):
    snapshot_id: str
    scene_ids: list[str] | None = None
    chapter_ids: list[str] | None = None


class ExportBody(ActorBody):
    format: str = "json"


class DueItemBody(ActorBody):
    title: str
    scene_id: str | None = None
    chapter_id: str | None = None
    note: str | None = None


class WaiverBody(ActorBody):
    kind: str | None = None
    subject_id: str | None = None
    reason_code: str
    comment: str | None = None


class SafetyBody(ActorBody):
    scene_ids: list[str] | None = None
    result: str = "placeholder_ok"


def _service(request: Request) -> ReleaseService:
    repository = (
        getattr(request.app.state, "release_repository", None)
        or InMemoryReleaseRepository()
    )
    return ReleaseService(
        story_repository=request.app.state.repository,
        canon_repository=request.app.state.canon_repository,
        scene_repository=request.app.state.scene_repository,
        scene_draft_repository=request.app.state.scene_draft_repository,
        candidate_change_repository=request.app.state.candidate_change_repository,
        validation_repository=request.app.state.validation_repository,
        repair_repository=request.app.state.repair_repository,
        summary_repository=request.app.state.summary_repository,
        style_validation_repository=request.app.state.style_validation_repository,
        review_queue_repository=request.app.state.review_queue_repository,
        release_repository=repository,
        audit_writer=request.app.state.audit_writer,
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


def _raise(exc: ReleaseServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/projects/{project_id}/release-checks", status_code=201)
def run_release_check(
    request: Request, project_id: str, body: RunCheckBody
) -> dict[str, Any]:
    try:
        check = _service(request).run_check(
            project_id=project_id,
            actor=_actor(request, body),
            snapshot_id=body.snapshot_id,
            scene_ids=body.scene_ids,
            chapter_ids=body.chapter_ids,
        )
    except ReleaseServiceError as exc:
        _raise(exc)
    return check.to_public_dict()


@router.get("/projects/{project_id}/release-checks")
def list_release_checks(request: Request, project_id: str) -> dict[str, Any]:
    try:
        items = _service(request).list_checks(project_id)
    except ReleaseServiceError as exc:
        _raise(exc)
    return {"items": [item.to_public_dict() for item in items]}


@router.get("/projects/{project_id}/release-checks/{check_id}")
def get_release_check(
    request: Request, project_id: str, check_id: str
) -> dict[str, Any]:
    try:
        check = _service(request).get_check(project_id, check_id)
    except ReleaseServiceError as exc:
        _raise(exc)
    return check.to_public_dict()


@router.post("/projects/{project_id}/release-checks/{check_id}/cancel")
def cancel_release_check(
    request: Request,
    project_id: str,
    check_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        check = _service(request).cancel_check(
            project_id, check_id, actor=_actor(request, body)
        )
    except ReleaseServiceError as exc:
        _raise(exc)
    return check.to_public_dict()


@router.get("/projects/{project_id}/release-checks/{check_id}/manifest")
def get_release_manifest(
    request: Request, project_id: str, check_id: str
) -> dict[str, Any]:
    try:
        manifest = _service(request).get_manifest(project_id, check_id)
    except ReleaseServiceError as exc:
        _raise(exc)
    return manifest.to_public_dict()


@router.patch("/projects/{project_id}/release-checks/{check_id}/manifest")
@router.put("/projects/{project_id}/release-checks/{check_id}/manifest")
def mutate_release_manifest(
    request: Request,
    project_id: str,
    check_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    del body
    try:
        _service(request).reject_mutate_manifest(project_id, check_id)
    except ReleaseServiceError as exc:
        _raise(exc)
    raise HTTPException(status_code=409, detail={"error": "release_manifest_immutable"})


@router.post("/projects/{project_id}/release-checks/{check_id}/export", status_code=201)
def export_formal_release(
    request: Request,
    project_id: str,
    check_id: str,
    body: ExportBody | None = None,
    format: str = Query(default="json", alias="format"),
) -> dict[str, Any]:
    payload = body or ExportBody(format=format)
    fmt = payload.format or format
    try:
        export = _service(request).export(
            project_id=project_id,
            check_id=check_id,
            actor=_actor(request, payload),
            fmt=fmt,
        )
    except ReleaseServiceError as exc:
        _raise(exc)
    return export.to_public_dict()


@router.post("/projects/{project_id}/release-due-items", status_code=201)
def create_due_item(
    request: Request, project_id: str, body: DueItemBody
) -> dict[str, Any]:
    try:
        item = _service(request).create_due_item(
            project_id=project_id,
            actor=_actor(request, body),
            title=body.title,
            scene_id=body.scene_id,
            chapter_id=body.chapter_id,
            note=body.note,
        )
    except ReleaseServiceError as exc:
        _raise(exc)
    return item.to_public_dict()


@router.post("/projects/{project_id}/release-due-items/{due_item_id}/handle")
def handle_due_item(
    request: Request,
    project_id: str,
    due_item_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        item = _service(request).handle_due_item(
            project_id, due_item_id, actor=_actor(request, body)
        )
    except ReleaseServiceError as exc:
        _raise(exc)
    return item.to_public_dict()


@router.post("/projects/{project_id}/release-due-items/{due_item_id}/waive")
def waive_due_item(
    request: Request,
    project_id: str,
    due_item_id: str,
    body: WaiverBody,
) -> dict[str, Any]:
    try:
        waiver = _service(request).waive(
            project_id=project_id,
            actor=_actor(request, body),
            kind=WAIVER_KIND_DUE,
            subject_id=due_item_id,
            reason_code=body.reason_code,
            comment=body.comment,
        )
    except ReleaseServiceError as exc:
        _raise(exc)
    return waiver.to_public_dict()


@router.post("/projects/{project_id}/release-safety-checks", status_code=201)
def record_safety_check(
    request: Request, project_id: str, body: SafetyBody | None = None
) -> dict[str, Any]:
    payload = body or SafetyBody()
    try:
        check = _service(request).record_safety_check(
            project_id=project_id,
            actor=_actor(request, payload),
            scene_ids=payload.scene_ids,
            result=payload.result,
        )
    except ReleaseServiceError as exc:
        _raise(exc)
    return check.to_public_dict()


@router.post("/projects/{project_id}/release-waivers", status_code=201)
def create_waiver(
    request: Request, project_id: str, body: WaiverBody
) -> dict[str, Any]:
    try:
        waiver = _service(request).waive(
            project_id=project_id,
            actor=_actor(request, body),
            kind=body.kind or "",
            subject_id=body.subject_id or "",
            reason_code=body.reason_code,
            comment=body.comment,
        )
    except ReleaseServiceError as exc:
        _raise(exc)
    return waiver.to_public_dict()


@router.post("/projects/{project_id}/release-checks/{check_id}/approve-canon")
def approve_canon(
    request: Request,
    project_id: str,
    check_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    del project_id, check_id
    try:
        _service(request).reject_canon_write(_actor(request, body), action="approve")
    except ReleaseServiceError as exc:
        _raise(exc)
    raise HTTPException(status_code=403, detail={"error": "release_cannot_write_canon"})


@router.post("/projects/{project_id}/release-checks/{check_id}/submit-canon")
def submit_canon(
    request: Request,
    project_id: str,
    check_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    del project_id, check_id
    try:
        _service(request).reject_canon_write(_actor(request, body), action="submit")
    except ReleaseServiceError as exc:
        _raise(exc)
    raise HTTPException(status_code=403, detail={"error": "release_cannot_write_canon"})


WAIVER_KIND_DUE = "due_item"
