"""HTTP routes for Repair Tasks (node 5.2).

POST /projects/{project_id}/repair-tasks
GET  /projects/{project_id}/repair-tasks
GET  /projects/{project_id}/repair-tasks/{task_id}
POST /projects/{project_id}/repair-tasks/{task_id}/start
POST /projects/{project_id}/repair-tasks/{task_id}/complete
POST /projects/{project_id}/repair-tasks/{task_id}/cancel
GET  /projects/{project_id}/validation-runs/{run_id}/repair-tasks

Repair complete is not approve and does not write Canon.
No production seed-status route. No chapter-level generate.
"""

from __future__ import annotations

from typing import Any, Literal, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from slove_context.candidate_change.models import (
    DEFAULT_REPAIR_TASK_TYPE as EXTRACT_REPAIR_TASK_TYPE,
)
from slove_context.candidate_change.models import DEFAULT_TASK_TYPE as EXTRACT_TASK_TYPE
from slove_context.candidate_change.repository import (
    CandidateChangeRepository,
    InMemoryCandidateChangeRepository,
)
from slove_context.candidate_change.service import CandidateChangeService
from slove_context.canon.repository import CanonRepository, InMemoryCanonRepository
from slove_context.canon.service import CanonService
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway
from slove_context.repair.repository import InMemoryRepairRepository, RepairRepository
from slove_context.repair.service import RepairService, RepairServiceError
from slove_context.scene.repository import InMemorySceneRepository, SceneRepository
from slove_context.scene.service import SceneService
from slove_context.scene_draft.models import DEFAULT_TASK_TYPE as DRAFT_TASK_TYPE
from slove_context.scene_draft.repository import (
    InMemorySceneDraftRepository,
    SceneDraftRepository,
)
from slove_context.scene_draft.service import SceneDraftService
from slove_context.scene_plan.models import DEFAULT_REPAIR_TASK_TYPE, DEFAULT_TASK_TYPE
from slove_context.scene_plan.repository import (
    InMemoryScenePlanRepository,
    ScenePlanRepository,
)
from slove_context.scene_plan.service import ScenePlanService
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)
from slove_context.story.repository import InMemoryStoryRepository, StoryRepository
from slove_context.validation.repository import (
    InMemoryValidationRepository,
    ValidationRepository,
)
from slove_context.validation.rules import DeterministicRuleEngine, RuleEngine
from slove_context.validation.service import ValidationService

router = APIRouter(tags=["repair-task"])

RepairAction = Literal["ReviseScenePlan", "Regenerate", "Reextract", "HumanReject"]


class OpenTaskBody(BaseModel):
    validation_run_id: str
    action: RepairAction
    violation_id: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = Field(default=None)


def _service(request: Request) -> RepairService:
    story: StoryRepository = (
        getattr(request.app.state, "repository", None) or InMemoryStoryRepository()
    )
    scenes: SceneRepository = (
        getattr(request.app.state, "scene_repository", None)
        or InMemorySceneRepository()
    )
    canon: CanonRepository = (
        getattr(request.app.state, "canon_repository", None)
        or InMemoryCanonRepository()
    )
    plans: ScenePlanRepository = (
        getattr(request.app.state, "scene_plan_repository", None)
        or InMemoryScenePlanRepository()
    )
    drafts: SceneDraftRepository = (
        getattr(request.app.state, "scene_draft_repository", None)
        or InMemorySceneDraftRepository()
    )
    extracts: CandidateChangeRepository = (
        getattr(request.app.state, "candidate_change_repository", None)
        or InMemoryCandidateChangeRepository()
    )
    validation_repo: ValidationRepository = (
        getattr(request.app.state, "validation_repository", None)
        or InMemoryValidationRepository()
    )
    repair_repo: RepairRepository = (
        getattr(request.app.state, "repair_repository", None)
        or InMemoryRepairRepository()
    )
    rule_engine: RuleEngine = (
        getattr(request.app.state, "validation_rule_engine", None)
        or DeterministicRuleEngine()
    )
    gateway: LlmGateway = getattr(request.app.state, "llm_gateway", None) or LlmGateway(
        FakeProvider(), audit_writer=request.app.state.audit_writer
    )
    scene_service = SceneService(
        story_repository=story,
        scene_repository=scenes,
        audit_writer=request.app.state.audit_writer,
    )
    validation_service = ValidationService(
        story_repository=story,
        scene_service=scene_service,
        extract_repository=extracts,
        canon_service=CanonService(
            story_repository=story,
            canon_repository=canon,
            audit_writer=request.app.state.audit_writer,
        ),
        validation_repository=validation_repo,
        audit_writer=request.app.state.audit_writer,
        rule_engine=rule_engine,
        auto_run=bool(getattr(request.app.state, "validation_auto_run", True)),
    )
    plan_service = ScenePlanService(
        story_repository=story,
        canon_repository=canon,
        scene_service=scene_service,
        plan_repository=plans,
        audit_writer=request.app.state.audit_writer,
        llm_gateway=gateway,
        task_type=getattr(request.app.state, "scene_plan_task_type", DEFAULT_TASK_TYPE),
        repair_task_type=getattr(
            request.app.state,
            "scene_plan_repair_task_type",
            DEFAULT_REPAIR_TASK_TYPE,
        ),
    )
    draft_service = SceneDraftService(
        story_repository=story,
        canon_repository=canon,
        scene_service=scene_service,
        plan_repository=plans,
        draft_repository=drafts,
        audit_writer=request.app.state.audit_writer,
        llm_gateway=gateway,
        task_type=getattr(request.app.state, "scene_draft_task_type", DRAFT_TASK_TYPE),
        auto_run=bool(getattr(request.app.state, "scene_draft_auto_run", True)),
        context_pack_repository=getattr(
            request.app.state, "context_pack_repository", None
        ),
    )
    extract_service = CandidateChangeService(
        story_repository=story,
        scene_service=scene_service,
        draft_repository=drafts,
        extract_repository=extracts,
        audit_writer=request.app.state.audit_writer,
        llm_gateway=gateway,
        task_type=getattr(request.app.state, "extract_task_type", EXTRACT_TASK_TYPE),
        repair_task_type=getattr(
            request.app.state, "extract_repair_task_type", EXTRACT_REPAIR_TASK_TYPE
        ),
        auto_run=bool(getattr(request.app.state, "extract_auto_run", True)),
    )
    return RepairService(
        story_repository=story,
        scene_service=scene_service,
        extract_repository=extracts,
        plan_repository=plans,
        draft_repository=drafts,
        repair_repository=repair_repo,
        validation_service=validation_service,
        plan_service=plan_service,
        draft_service=draft_service,
        extract_service=extract_service,
        audit_writer=request.app.state.audit_writer,
    )


def _actor(request: Request, body: OpenTaskBody | ActorBody | None = None) -> Actor:
    body_type = body.actor_type if body is not None else None
    body_id = None
    if body is not None:
        body_id = body.actor_id or getattr(body, "created_by", None)
    return resolve_actor(
        header_type=request.headers.get(ACTOR_TYPE_HEADER),
        header_id=request.headers.get(ACTOR_ID_HEADER),
        body_type=body_type,
        body_id=body_id,
    )


def _raise(exc: RepairServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/projects/{project_id}/repair-tasks", status_code=201)
def open_repair_task(
    request: Request, project_id: str, body: OpenTaskBody
) -> dict[str, Any]:
    try:
        task = _service(request).open_task(
            project_id=project_id,
            actor=_actor(request, body),
            validation_run_id=body.validation_run_id,
            action=body.action,
            violation_id=body.violation_id,
        )
    except RepairServiceError as exc:
        _raise(exc)
    return task.to_public_dict()


@router.get("/projects/{project_id}/repair-tasks")
def list_repair_tasks(
    request: Request,
    project_id: str,
    validation_run_id: str | None = None,
) -> dict[str, Any]:
    try:
        items = _service(request).list_tasks(
            project_id, validation_run_id=validation_run_id
        )
    except RepairServiceError as exc:
        _raise(exc)
    return {
        "items": [item.to_public_dict() for item in items],
        "is_canon": False,
        "writes_canon": False,
        "auto_approved": False,
        "is_approval": False,
    }


@router.get("/projects/{project_id}/validation-runs/{run_id}/repair-tasks")
def list_repair_tasks_for_run(
    request: Request, project_id: str, run_id: str
) -> dict[str, Any]:
    try:
        items = _service(request).list_tasks(project_id, validation_run_id=run_id)
    except RepairServiceError as exc:
        _raise(exc)
    return {
        "items": [item.to_public_dict() for item in items],
        "validation_run_id": run_id,
        "is_canon": False,
        "writes_canon": False,
        "auto_approved": False,
        "is_approval": False,
    }


@router.get("/projects/{project_id}/repair-tasks/{task_id}")
def get_repair_task(request: Request, project_id: str, task_id: str) -> dict[str, Any]:
    try:
        task = _service(request).get_task(project_id, task_id)
    except RepairServiceError as exc:
        _raise(exc)
    return task.to_public_dict()


@router.post("/projects/{project_id}/repair-tasks/{task_id}/start")
def start_repair_task(
    request: Request,
    project_id: str,
    task_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        task = _service(request).start_task(
            project_id, task_id, actor=_actor(request, body)
        )
    except RepairServiceError as exc:
        _raise(exc)
    return task.to_public_dict()


@router.post("/projects/{project_id}/repair-tasks/{task_id}/complete")
def complete_repair_task(
    request: Request,
    project_id: str,
    task_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        task = _service(request).complete_task(
            project_id, task_id, actor=_actor(request, body)
        )
    except RepairServiceError as exc:
        _raise(exc)
    return task.to_public_dict()


@router.post("/projects/{project_id}/repair-tasks/{task_id}/cancel")
def cancel_repair_task(
    request: Request,
    project_id: str,
    task_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        task = _service(request).cancel_task(
            project_id, task_id, actor=_actor(request, body)
        )
    except RepairServiceError as exc:
        _raise(exc)
    return task.to_public_dict()
