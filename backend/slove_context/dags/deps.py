"""Wire existing 3.3–8.2 services for the 8.3 DAG orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from slove_context.candidate_change.approval_service import ApprovalService
from slove_context.canon.service import CanonService
from slove_context.context_pack.service import ContextPackService
from slove_context.jobs.deps import ExistingServices, services_from_state
from slove_context.jobs.service import JobService
from slove_context.jobs.worker import Worker
from slove_context.review_queue.service import ReviewQueueService
from slove_context.scene.service import SceneService


@dataclass
class DagServices:
    existing: ExistingServices
    jobs: JobService
    worker: Worker
    scenes: SceneService
    approval: ApprovalService
    review_queue: ReviewQueueService
    context_pack: ContextPackService
    canon: CanonService


def dag_services_from_state(state: Any) -> DagServices:
    existing = services_from_state(state)
    story = state.repository
    scenes = SceneService(
        story_repository=story,
        scene_repository=state.scene_repository,
        audit_writer=state.audit_writer,
    )
    jobs = JobService(
        story_repository=story,
        job_repository=state.job_repository,
        audit_writer=state.audit_writer,
    )
    worker = getattr(state, "worker", None)
    if worker is None:
        worker = Worker(
            job_repository=state.job_repository,
            audit_writer=state.audit_writer,
            services=existing,
            timeout_s=float(getattr(state, "job_timeout_s", 30.0)),
            base_backoff_s=float(getattr(state, "job_base_backoff_s", 0.0)),
        )
        state.worker = worker
    canon = CanonService(
        story_repository=story,
        canon_repository=state.canon_repository,
        audit_writer=state.audit_writer,
    )
    approval = ApprovalService(
        story_repository=story,
        extract_repository=state.candidate_change_repository,
        canon_service=canon,
        audit_writer=state.audit_writer,
    )
    review_queue = ReviewQueueService(
        story_repository=story,
        scene_repository=state.scene_repository,
        scene_plan_repository=state.scene_plan_repository,
        scene_draft_repository=state.scene_draft_repository,
        candidate_change_repository=state.candidate_change_repository,
        validation_repository=state.validation_repository,
        repair_repository=state.repair_repository,
        style_validation_repository=state.style_validation_repository,
        review_queue_repository=state.review_queue_repository,
        audit_writer=state.audit_writer,
        canon_service=canon,
    )
    return DagServices(
        existing=existing,
        jobs=jobs,
        worker=worker,
        scenes=scenes,
        approval=approval,
        review_queue=review_queue,
        context_pack=existing.context_pack,
        canon=canon,
    )
