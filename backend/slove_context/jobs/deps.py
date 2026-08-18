"""Build existing 3.3–6.1 services for the 8.1 Worker dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from slove_context.candidate_change.models import (
    DEFAULT_REPAIR_TASK_TYPE as EXTRACT_REPAIR_TASK_TYPE,
)
from slove_context.candidate_change.models import DEFAULT_TASK_TYPE as EXTRACT_TASK_TYPE
from slove_context.candidate_change.service import CandidateChangeService
from slove_context.canon.service import CanonService
from slove_context.context_pack.service import ContextPackService
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway
from slove_context.repair.service import RepairService
from slove_context.scene.service import SceneService
from slove_context.scene_draft.models import DEFAULT_TASK_TYPE as DRAFT_TASK_TYPE
from slove_context.scene_draft.service import SceneDraftService
from slove_context.scene_plan.models import DEFAULT_REPAIR_TASK_TYPE, DEFAULT_TASK_TYPE
from slove_context.scene_plan.service import ScenePlanService
from slove_context.summary.models import (
    DEFAULT_CHAPTER_TASK_TYPE as CHAPTER_SUMMARY_TASK_TYPE,
)
from slove_context.summary.models import (
    DEFAULT_SCENE_TASK_TYPE as SCENE_SUMMARY_TASK_TYPE,
)
from slove_context.summary.service import SummaryService
from slove_context.validation.rules import DeterministicRuleEngine, RuleEngine
from slove_context.validation.service import ValidationService


@dataclass
class ExistingServices:
    plan: ScenePlanService
    draft: SceneDraftService
    extract: CandidateChangeService
    validate: ValidationService
    repair: RepairService
    summarize: SummaryService
    context_pack: ContextPackService


def services_from_state(state: Any) -> ExistingServices:
    """Wire existing services from FastAPI app.state. No new generators."""
    story = state.repository
    scenes = SceneService(
        story_repository=story,
        scene_repository=state.scene_repository,
        audit_writer=state.audit_writer,
    )
    gateway: LlmGateway | None = getattr(state, "llm_gateway", None)
    if gateway is None:
        gateway = LlmGateway(FakeProvider(), audit_writer=state.audit_writer)
    canon = CanonService(
        story_repository=story,
        canon_repository=state.canon_repository,
        audit_writer=state.audit_writer,
    )
    plan = ScenePlanService(
        story_repository=story,
        canon_repository=state.canon_repository,
        scene_service=scenes,
        plan_repository=state.scene_plan_repository,
        audit_writer=state.audit_writer,
        llm_gateway=gateway,
        task_type=getattr(state, "scene_plan_task_type", DEFAULT_TASK_TYPE),
        repair_task_type=getattr(
            state, "scene_plan_repair_task_type", DEFAULT_REPAIR_TASK_TYPE
        ),
    )
    draft = SceneDraftService(
        story_repository=story,
        canon_repository=state.canon_repository,
        scene_service=scenes,
        plan_repository=state.scene_plan_repository,
        draft_repository=state.scene_draft_repository,
        audit_writer=state.audit_writer,
        llm_gateway=gateway,
        task_type=getattr(state, "scene_draft_task_type", DRAFT_TASK_TYPE),
        auto_run=bool(getattr(state, "scene_draft_auto_run", True)),
        context_pack_repository=getattr(state, "context_pack_repository", None),
    )
    extract = CandidateChangeService(
        story_repository=story,
        scene_service=scenes,
        draft_repository=state.scene_draft_repository,
        extract_repository=state.candidate_change_repository,
        audit_writer=state.audit_writer,
        llm_gateway=gateway,
        task_type=getattr(state, "extract_task_type", EXTRACT_TASK_TYPE),
        repair_task_type=getattr(
            state, "extract_repair_task_type", EXTRACT_REPAIR_TASK_TYPE
        ),
        auto_run=bool(getattr(state, "extract_auto_run", True)),
    )
    rule_engine: RuleEngine = (
        getattr(state, "validation_rule_engine", None) or DeterministicRuleEngine()
    )
    validate = ValidationService(
        story_repository=story,
        scene_service=scenes,
        extract_repository=state.candidate_change_repository,
        canon_service=canon,
        validation_repository=state.validation_repository,
        audit_writer=state.audit_writer,
        rule_engine=rule_engine,
        auto_run=bool(getattr(state, "validation_auto_run", True)),
    )
    repair = RepairService(
        story_repository=story,
        scene_service=scenes,
        extract_repository=state.candidate_change_repository,
        plan_repository=state.scene_plan_repository,
        draft_repository=state.scene_draft_repository,
        repair_repository=state.repair_repository,
        validation_service=validate,
        plan_service=plan,
        draft_service=draft,
        extract_service=extract,
        audit_writer=state.audit_writer,
    )
    summarize = SummaryService(
        story_repository=story,
        scene_service=scenes,
        draft_repository=state.scene_draft_repository,
        summary_repository=state.summary_repository,
        audit_writer=state.audit_writer,
        llm_gateway=gateway,
        scene_task_type=getattr(
            state, "scene_summary_task_type", SCENE_SUMMARY_TASK_TYPE
        ),
        chapter_task_type=getattr(
            state, "chapter_summary_task_type", CHAPTER_SUMMARY_TASK_TYPE
        ),
        auto_run=bool(getattr(state, "summary_auto_run", True)),
    )
    context_pack = ContextPackService(
        story_repository=story,
        scene_service=scenes,
        canon_service=canon,
        canon_repository=state.canon_repository,
        pack_repository=state.context_pack_repository,
        audit_writer=state.audit_writer,
        plan_repository=state.scene_plan_repository,
        draft_repository=state.scene_draft_repository,
        candidate_repository=state.candidate_change_repository,
    )
    return ExistingServices(
        plan=plan,
        draft=draft,
        extract=extract,
        validate=validate,
        repair=repair,
        summarize=summarize,
        context_pack=context_pack,
    )
