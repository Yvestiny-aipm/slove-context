"""Human review-queue write path (node 7.3).

Enqueue an existing subject. Human 主编 may approve, reject,
request_revision, or escalate. Each decision needs a reason_code.

Candidate Change approve reuses node 4.2 (verdict only). It never
submits Canon. Style Report approve is not Canon approval and does
not block Canon submit. Writes go through AuditWriter. Records are
kept on failure or cancel. No 8.x workers. No real model calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.candidate_change.approval_service import ApprovalService
from slove_context.candidate_change.models import (
    CANDIDATE_APPROVED,
    CANDIDATE_AWAITING_VERDICT,
)
from slove_context.candidate_change.repository import CandidateChangeRepository
from slove_context.candidate_change.service import CandidateChangeServiceError
from slove_context.canon.service import CanonService
from slove_context.logging import get_request_id
from slove_context.repair.models import TASK_CANCELLED, TASK_RECHECK_PASSED
from slove_context.repair.repository import RepairRepository
from slove_context.review_queue.models import (
    ACTION_APPROVE,
    ACTION_CANCEL,
    ACTION_ESCALATE,
    ACTION_REJECT,
    ACTION_TO_STATUS,
    CANCEL_FROM_STATES,
    DECIDABLE_STATES,
    DECISION_ACTIONS,
    OPEN_STATES,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_OPENED,
    SUBJECT_CANDIDATE_CHANGE,
    SUBJECT_REPAIR_TASK,
    SUBJECT_SCENE_DRAFT,
    SUBJECT_SCENE_PLAN,
    SUBJECT_STYLE_REPORT,
    SUBJECT_TYPES,
    SUBJECT_VALIDATION_REPORT,
    ReviewDecision,
    ReviewQueueItem,
    SubjectSnapshot,
    canon_submit_path,
    normalize_subject_type,
)
from slove_context.review_queue.repository import ReviewQueueRepository
from slove_context.scene.models import Scene
from slove_context.scene.repository import SceneRepository
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.scene_plan.repository import ScenePlanRepository
from slove_context.story.actors import (
    HUMAN_EDITOR,
    SYSTEM,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.repository import StoryRepository
from slove_context.style_validation.repository import StyleValidationRepository
from slove_context.validation.models import RUN_RULE_FAILED, SEVERITY_BLOCKING
from slove_context.validation.repository import ValidationRepository


class ReviewQueueServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class ReviewQueueService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        scene_repository: SceneRepository,
        scene_plan_repository: ScenePlanRepository,
        scene_draft_repository: SceneDraftRepository,
        candidate_change_repository: CandidateChangeRepository,
        validation_repository: ValidationRepository,
        repair_repository: RepairRepository,
        style_validation_repository: StyleValidationRepository,
        review_queue_repository: ReviewQueueRepository,
        audit_writer: AuditWriter,
        canon_service: CanonService,
    ) -> None:
        self._story = story_repository
        self._scenes = scene_repository
        self._plans = scene_plan_repository
        self._drafts = scene_draft_repository
        self._candidates = candidate_change_repository
        self._validations = validation_repository
        self._repairs = repair_repository
        self._styles = style_validation_repository
        self._repo = review_queue_repository
        self._audit = audit_writer
        self._approval = ApprovalService(
            story_repository=story_repository,
            extract_repository=candidate_change_repository,
            canon_service=canon_service,
            audit_writer=audit_writer,
        )

    def enqueue(
        self,
        *,
        project_id: str,
        actor: Actor,
        body: dict[str, Any],
    ) -> ReviewQueueItem:
        self._require_project(project_id)
        subject_type = normalize_subject_type(_optional_str(body.get("subject_type")))
        subject_id = _optional_str(body.get("subject_id"))
        if subject_type is None or subject_type not in SUBJECT_TYPES:
            raise ReviewQueueServiceError(
                422,
                {
                    "error": "invalid_subject_type",
                    "message": (
                        "subject_type must be scene_plan, scene_draft, "
                        "candidate_change, validation_report, repair_task, "
                        "or style_report."
                    ),
                    "subject_type": body.get("subject_type"),
                },
            )
        if subject_id is None:
            raise ReviewQueueServiceError(
                422,
                {
                    "error": "subject_id_required",
                    "message": "Enqueue an existing object by type + id.",
                },
            )
        existing = self._repo.find_open_item(project_id, subject_type, subject_id)
        if existing is not None:
            return existing

        snapshot = self._load_subject(project_id, subject_type, subject_id)
        explicit_blocker = body.get("is_blocker")
        is_blocker = (
            bool(explicit_blocker)
            if explicit_blocker is not None
            else snapshot.is_blocker
        )
        chapter_id = _optional_str(body.get("chapter_id")) or snapshot.chapter_id
        now = _utc_now_z()
        item = ReviewQueueItem(
            id=str(uuid4()),
            project_id=project_id,
            subject_type=subject_type,
            subject_id=subject_id,
            status=STATUS_OPENED,
            created_at=now,
            updated_at=now,
            created_by=actor.actor_id or "system",
            actor_type=actor.actor_type or SYSTEM,
            is_blocker=is_blocker,
            chapter_id=chapter_id,
            scene_id=snapshot.scene_id,
            context_pack_id=snapshot.context_pack_id,
            input_versions=dict(snapshot.input_versions),
            evidence_refs=[dict(item) for item in snapshot.evidence_refs],
            diff=dict(snapshot.diff),
        )
        self._repo.add_item(item)
        self._write_audit(
            actor=actor if actor.actor_type else Actor(SYSTEM, None),
            action="review_queue.enqueue",
            resource_type="review_queue_item",
            resource_id=item.id,
            before_json=None,
            after_json=item.to_audit_dict(),
        )
        return item

    def list_items(
        self,
        project_id: str,
        *,
        blocker: bool | None = None,
        chapter_id: str | None = None,
        status: str | None = None,
        sort: str | None = None,
    ) -> list[ReviewQueueItem]:
        self._require_project(project_id)
        items = self._repo.list_items(project_id)
        if blocker is not None:
            items = [item for item in items if item.is_blocker is blocker]
        if chapter_id:
            items = [item for item in items if item.chapter_id == chapter_id]
        if status:
            items = [item for item in items if item.status == status]
        return _sort_items(items, sort)

    def get_item(self, project_id: str, item_id: str) -> ReviewQueueItem:
        return self._require_item(project_id, item_id)

    def decisions_for(self, item: ReviewQueueItem) -> list[ReviewDecision]:
        return self._repo.list_decisions(item.id)

    def decide(
        self,
        *,
        project_id: str,
        item_id: str,
        action: str,
        actor: Actor,
        body: dict[str, Any],
    ) -> tuple[ReviewQueueItem, ReviewDecision]:
        editor = self._require_human(actor, action=action)
        item = self._require_item(project_id, item_id)
        if action not in DECISION_ACTIONS:
            raise ReviewQueueServiceError(
                422,
                {
                    "error": "invalid_decision_action",
                    "message": (
                        "Decision must be approve, reject, "
                        "request_revision, or escalate."
                    ),
                    "action": action,
                },
            )
        if item.status not in DECIDABLE_STATES:
            raise ReviewQueueServiceError(
                409,
                {
                    "error": "invalid_queue_transition",
                    "message": (
                        "Only Opened or Escalated items can take a "
                        "decision. Failure and cancel keep the record."
                    ),
                    "status": item.status,
                },
            )
        if action == ACTION_ESCALATE and item.status == STATUS_OPENED:
            pass
        elif action == ACTION_ESCALATE and item.status != STATUS_OPENED:
            raise ReviewQueueServiceError(
                409,
                {
                    "error": "invalid_queue_transition",
                    "message": "Only an Opened item can be escalated.",
                    "status": item.status,
                },
            )
        reason_code = _require_reason_code(body)
        comment = _optional_str(body.get("comment"))
        if action == ACTION_APPROVE:
            self._apply_subject_approve(item, editor, body)
        elif action == ACTION_REJECT:
            self._apply_subject_reject(item, editor, body)
        before = item.to_audit_dict()
        now = _utc_now_z()
        decision = ReviewDecision(
            id=str(uuid4()),
            item_id=item.id,
            project_id=item.project_id,
            action=action,
            reason_code=reason_code,
            created_at=now,
            actor_type=editor.actor_type,
            actor_id=editor.actor_id,
            comment=comment,
        )
        item.status = ACTION_TO_STATUS[action]
        item.updated_at = now
        item.decision_ids.append(decision.id)
        self._repo.add_decision(decision)
        self._repo.save_item(item)
        self._write_audit(
            actor=editor,
            action=f"review_queue.{action}",
            resource_type="review_queue_item",
            resource_id=item.id,
            before_json=before,
            after_json=item.to_audit_dict(),
        )
        self._write_audit(
            actor=editor,
            action="review_decision.create",
            resource_type="review_decision",
            resource_id=decision.id,
            before_json=None,
            after_json=decision.to_audit_dict(),
        )
        return item, decision

    def cancel(
        self,
        *,
        project_id: str,
        item_id: str,
        actor: Actor,
        body: dict[str, Any],
    ) -> tuple[ReviewQueueItem, ReviewDecision]:
        editor = self._require_human(actor, action="cancel")
        item = self._require_item(project_id, item_id)
        if item.status not in CANCEL_FROM_STATES:
            raise ReviewQueueServiceError(
                409,
                {
                    "error": "invalid_queue_transition",
                    "message": (
                        "Cancel is allowed from Opened or Escalated. "
                        "The record is kept."
                    ),
                    "status": item.status,
                },
            )
        reason_code = _require_reason_code(body)
        before = item.to_audit_dict()
        now = _utc_now_z()
        decision = ReviewDecision(
            id=str(uuid4()),
            item_id=item.id,
            project_id=item.project_id,
            action=ACTION_CANCEL,
            reason_code=reason_code,
            created_at=now,
            actor_type=editor.actor_type,
            actor_id=editor.actor_id,
            comment=_optional_str(body.get("comment")),
        )
        item.status = STATUS_CANCELLED
        item.updated_at = now
        item.decision_ids.append(decision.id)
        self._repo.add_decision(decision)
        self._repo.save_item(item)
        self._write_audit(
            actor=editor,
            action="review_queue.cancel",
            resource_type="review_queue_item",
            resource_id=item.id,
            before_json=before,
            after_json=item.to_audit_dict(),
        )
        return item, decision

    def mark_failed(
        self,
        *,
        project_id: str,
        item_id: str,
        actor: Actor,
        reason: str,
    ) -> ReviewQueueItem:
        item = self._require_item(project_id, item_id)
        if item.status not in OPEN_STATES:
            raise ReviewQueueServiceError(
                409,
                {
                    "error": "invalid_queue_transition",
                    "message": "Only an open item can be marked Failed.",
                    "status": item.status,
                },
            )
        before = item.to_audit_dict()
        item.status = STATUS_FAILED
        item.failure_reason = reason
        item.updated_at = _utc_now_z()
        self._repo.save_item(item)
        self._write_audit(
            actor=actor,
            action="review_queue.fail",
            resource_type="review_queue_item",
            resource_id=item.id,
            before_json=before,
            after_json=item.to_audit_dict(),
        )
        return item

    def export_pack(self, project_id: str, item_id: str) -> dict[str, Any]:
        item = self._require_item(project_id, item_id)
        decisions = self._repo.list_decisions(item.id)
        snapshot = self._load_subject(project_id, item.subject_type, item.subject_id)
        is_candidate = item.subject_type == SUBJECT_CANDIDATE_CHANGE
        is_style = item.subject_type == SUBJECT_STYLE_REPORT
        return {
            "schema": "review-pack.v1",
            "item": item.to_public_dict(decisions),
            "subject": {
                "subject_type": snapshot.subject_type,
                "subject_id": snapshot.subject_id,
                "scene_id": snapshot.scene_id,
                "chapter_id": snapshot.chapter_id,
                "subject_status": snapshot.subject_status,
                "input_versions": dict(snapshot.input_versions),
                "context_pack_id": snapshot.context_pack_id,
                "evidence_refs": [dict(ref) for ref in snapshot.evidence_refs],
                "diff": dict(snapshot.diff),
            },
            "decisions": [item.to_public_dict() for item in decisions],
            "writes_canon": False,
            "auto_approved": False,
            "is_canon": False,
            "is_canon_approval": False,
            "blocks_canon_submit": False,
            "style_report_approve_is_canon_approve": False,
            "style_approve_is_canon_approve": False,
            "canon_commit_required": is_candidate,
            "canon_commit_path": (
                canon_submit_path(item.project_id, item.subject_id)
                if is_candidate
                else None
            ),
            "subject_is_style_report": is_style,
            "note": (
                "Review-queue approve on a candidate is 4.2 approve "
                "(AwaitingVerdict→Approved), not submit. Canon commit "
                "remains POST .../candidate-changes/{id}/submit."
            ),
        }

    def _apply_subject_approve(
        self, item: ReviewQueueItem, editor: Actor, body: dict[str, Any]
    ) -> None:
        if item.subject_type != SUBJECT_CANDIDATE_CHANGE:
            return
        candidate = self._candidates.get_candidate(item.subject_id)
        if candidate is None or candidate.project_id != item.project_id:
            raise ReviewQueueServiceError(404, {"error": "candidate_change_not_found"})
        if candidate.status == CANDIDATE_APPROVED:
            return
        if candidate.status != CANDIDATE_AWAITING_VERDICT:
            raise ReviewQueueServiceError(
                409,
                {
                    "error": "invalid_candidate_transition",
                    "message": (
                        "Review-queue approve on a candidate reuses 4.2 "
                        "approve. Only AwaitingVerdict can be approved. "
                        "Approve does not submit Canon."
                    ),
                    "status": candidate.status,
                    "writes_canon": False,
                },
            )
        try:
            self._approval.approve(
                project_id=item.project_id,
                candidate_id=item.subject_id,
                actor=editor,
                body=_approval_body(editor, body, item),
            )
        except CandidateChangeServiceError as exc:
            raise ReviewQueueServiceError(exc.status_code, exc.detail) from exc

    def _apply_subject_reject(
        self, item: ReviewQueueItem, editor: Actor, body: dict[str, Any]
    ) -> None:
        if item.subject_type != SUBJECT_CANDIDATE_CHANGE:
            return
        candidate = self._candidates.get_candidate(item.subject_id)
        if candidate is None or candidate.project_id != item.project_id:
            raise ReviewQueueServiceError(404, {"error": "candidate_change_not_found"})
        if candidate.status not in {
            CANDIDATE_AWAITING_VERDICT,
            CANDIDATE_APPROVED,
        }:
            return
        try:
            self._approval.reject(
                project_id=item.project_id,
                candidate_id=item.subject_id,
                actor=editor,
                body=_approval_body(editor, body, item),
            )
        except CandidateChangeServiceError as exc:
            raise ReviewQueueServiceError(exc.status_code, exc.detail) from exc

    def _load_subject(
        self, project_id: str, subject_type: str, subject_id: str
    ) -> SubjectSnapshot:
        if subject_type == SUBJECT_SCENE_PLAN:
            return self._snapshot_plan(project_id, subject_id)
        if subject_type == SUBJECT_SCENE_DRAFT:
            return self._snapshot_draft(project_id, subject_id)
        if subject_type == SUBJECT_CANDIDATE_CHANGE:
            return self._snapshot_candidate(project_id, subject_id)
        if subject_type == SUBJECT_VALIDATION_REPORT:
            return self._snapshot_report(project_id, subject_id)
        if subject_type == SUBJECT_REPAIR_TASK:
            return self._snapshot_repair(project_id, subject_id)
        return self._snapshot_style(project_id, subject_id)

    def _snapshot_plan(self, project_id: str, plan_id: str) -> SubjectSnapshot:
        plan = self._plans.get_plan(plan_id)
        if plan is None or plan.project_id != project_id:
            raise ReviewQueueServiceError(404, {"error": "scene_plan_not_found"})
        scene = self._scene(plan.scene_id)
        beats = plan.payload.get("beats")
        beat_count = len(beats) if isinstance(beats, list) else 0
        return SubjectSnapshot(
            subject_type=SUBJECT_SCENE_PLAN,
            subject_id=plan.id,
            scene_id=plan.scene_id,
            chapter_id=scene.chapter_id if scene else None,
            context_pack_id=_draft_pack(self._drafts, project_id, plan.scene_id),
            input_versions={
                "scene_id": plan.scene_id,
                "scene_card_id": plan.scene_card_id,
                "snapshot_id": plan.snapshot_id,
                "plan_id": plan.id,
                "job_id": plan.job_id,
                "prompt_version": plan.prompt_version,
            },
            evidence_refs=[
                {"kind": "scene_plan", "id": plan.id},
                {"kind": "scene_card", "id": plan.scene_card_id},
                {"kind": "canon_snapshot", "id": plan.snapshot_id},
            ],
            diff={
                "kind": SUBJECT_SCENE_PLAN,
                "plan_id": plan.id,
                "status": plan.status,
                "beat_count": beat_count,
                "snapshot_id": plan.snapshot_id,
            },
            is_blocker=False,
            subject_status=plan.status,
        )

    def _snapshot_draft(self, project_id: str, draft_id: str) -> SubjectSnapshot:
        draft = self._drafts.get_draft(draft_id)
        if draft is None or draft.project_id != project_id:
            raise ReviewQueueServiceError(404, {"error": "scene_draft_not_found"})
        scene = self._scene(draft.scene_id)
        return SubjectSnapshot(
            subject_type=SUBJECT_SCENE_DRAFT,
            subject_id=draft.id,
            scene_id=draft.scene_id,
            chapter_id=scene.chapter_id if scene else None,
            context_pack_id=draft.context_pack_id,
            input_versions={
                "scene_id": draft.scene_id,
                "scene_card_id": draft.scene_card_id,
                "plan_id": draft.plan_id,
                "snapshot_id": draft.snapshot_id,
                "context_pack_id": draft.context_pack_id,
                "revision": draft.revision,
                "content_hash": draft.content_hash,
                "prompt_version": draft.prompt_version,
            },
            evidence_refs=[
                {"kind": "scene_draft", "id": draft.id},
                {"kind": "content_hash", "id": draft.content_hash},
            ],
            diff={
                "kind": SUBJECT_SCENE_DRAFT,
                "draft_id": draft.id,
                "revision": draft.revision,
                "status": draft.status,
                "content_hash": draft.content_hash,
            },
            is_blocker=False,
            subject_status=draft.status,
        )

    def _snapshot_candidate(
        self, project_id: str, candidate_id: str
    ) -> SubjectSnapshot:
        candidate = self._candidates.get_candidate(candidate_id)
        if candidate is None or candidate.project_id != project_id:
            raise ReviewQueueServiceError(404, {"error": "candidate_change_not_found"})
        scene = self._scene(candidate.scene_id)
        draft = self._drafts.get_draft(candidate.draft_id)
        pack_id = draft.context_pack_id if draft is not None else None
        return SubjectSnapshot(
            subject_type=SUBJECT_CANDIDATE_CHANGE,
            subject_id=candidate.id,
            scene_id=candidate.scene_id,
            chapter_id=scene.chapter_id if scene else None,
            context_pack_id=pack_id,
            input_versions={
                "scene_id": candidate.scene_id,
                "draft_id": candidate.draft_id,
                "job_id": candidate.job_id,
                "extract_batch": candidate.extract_batch,
                "schema_version": candidate.schema_version,
                "source_scene_id": candidate.source_scene_id,
            },
            evidence_refs=[
                {
                    "kind": "candidate_change",
                    "id": candidate.id,
                    "has_evidence_quote": bool(candidate.evidence_quote),
                },
                {"kind": "source_scene", "id": candidate.source_scene_id},
                {"kind": "scene_draft", "id": candidate.draft_id},
            ],
            diff={
                "kind": SUBJECT_CANDIDATE_CHANGE,
                "candidate_id": candidate.id,
                "predicate": candidate.predicate,
                "subject": candidate.subject,
                "status": candidate.status,
                "has_evidence": bool(candidate.evidence_quote),
            },
            is_blocker=False,
            subject_status=candidate.status,
        )

    def _snapshot_report(self, project_id: str, report_id: str) -> SubjectSnapshot:
        report = self._validations.get_report(report_id)
        if report is None or report.project_id != project_id:
            raise ReviewQueueServiceError(404, {"error": "validation_report_not_found"})
        scene = self._scene(report.scene_id)
        run = self._validations.get_run(report.run_id)
        blocking = any(item.severity == SEVERITY_BLOCKING for item in report.violations)
        is_blocker = report.outcome == RUN_RULE_FAILED or blocking
        refs = [
            {"kind": "validation_report", "id": report.id},
            {"kind": "validation_run", "id": report.run_id},
        ]
        for candidate_id in report.candidate_change_ids:
            refs.append({"kind": "candidate_change", "id": candidate_id})
        return SubjectSnapshot(
            subject_type=SUBJECT_VALIDATION_REPORT,
            subject_id=report.id,
            scene_id=report.scene_id,
            chapter_id=scene.chapter_id if scene else None,
            context_pack_id=_draft_pack(self._drafts, project_id, report.scene_id),
            input_versions={
                "scene_id": report.scene_id,
                "run_id": report.run_id,
                "snapshot_id": run.snapshot_id if run is not None else None,
                "spec_id": run.spec_id if run is not None else None,
                "candidate_change_ids": list(report.candidate_change_ids),
                "schema_version": report.schema_version,
            },
            evidence_refs=refs,
            diff={
                "kind": SUBJECT_VALIDATION_REPORT,
                "report_id": report.id,
                "outcome": report.outcome,
                "violation_count": len(report.violations),
                "violation_rule_ids": [item.rule_id for item in report.violations],
            },
            is_blocker=is_blocker,
            subject_status=report.outcome,
        )

    def _snapshot_repair(self, project_id: str, task_id: str) -> SubjectSnapshot:
        task = self._repairs.get_task(task_id)
        if task is None or task.project_id != project_id:
            raise ReviewQueueServiceError(404, {"error": "repair_task_not_found"})
        scene = self._scene(task.scene_id)
        terminal = task.state in {TASK_RECHECK_PASSED, TASK_CANCELLED}
        refs = [
            {"kind": "repair_task", "id": task.id},
            {"kind": "validation_run", "id": task.validation_run_id},
        ]
        if task.report_id:
            refs.append({"kind": "validation_report", "id": task.report_id})
        for candidate_id in task.candidate_ids:
            refs.append({"kind": "candidate_change", "id": candidate_id})
        return SubjectSnapshot(
            subject_type=SUBJECT_REPAIR_TASK,
            subject_id=task.id,
            scene_id=task.scene_id,
            chapter_id=scene.chapter_id if scene else None,
            context_pack_id=_draft_pack(self._drafts, project_id, task.scene_id),
            input_versions={
                "scene_id": task.scene_id,
                "validation_run_id": task.validation_run_id,
                "report_id": task.report_id,
                "action": task.action,
                "candidate_ids": list(task.candidate_ids),
            },
            evidence_refs=refs,
            diff={
                "kind": SUBJECT_REPAIR_TASK,
                "task_id": task.id,
                "action": task.action,
                "state": task.state,
                "recheck_status": task.recheck_status,
            },
            is_blocker=not terminal,
            subject_status=task.state,
        )

    def _snapshot_style(self, project_id: str, run_id: str) -> SubjectSnapshot:
        run = self._styles.get(run_id)
        if run is None or run.project_id != project_id:
            raise ReviewQueueServiceError(404, {"error": "style_report_not_found"})
        scene = self._scene(run.scene_id)
        draft = self._drafts.get_draft(run.draft_revision_id)
        pack_id = draft.context_pack_id if draft is not None else None
        return SubjectSnapshot(
            subject_type=SUBJECT_STYLE_REPORT,
            subject_id=run.id,
            scene_id=run.scene_id,
            chapter_id=scene.chapter_id if scene else None,
            context_pack_id=pack_id,
            input_versions={
                "scene_id": run.scene_id,
                "draft_revision_id": run.draft_revision_id,
                "style_guide_revision_id": run.style_guide_revision_id,
                "style_sample_ids": list(run.style_sample_ids),
                "rule_version": run.rule_version,
                "llm_score_version": run.llm_score_version,
            },
            evidence_refs=[
                {"kind": "style_report", "id": run.id},
                {"kind": "scene_draft", "id": run.draft_revision_id},
                {
                    "kind": "finding_rule_ids",
                    "ids": [item.rule_id for item in run.findings],
                },
            ],
            diff={
                "kind": SUBJECT_STYLE_REPORT,
                "report_id": run.id,
                "status": run.status,
                "finding_count": len(run.findings),
                "finding_rule_ids": [item.rule_id for item in run.findings],
                "blocks_canon_submit": False,
            },
            is_blocker=False,
            subject_status=run.status,
        )

    def _scene(self, scene_id: str | None) -> Scene | None:
        if scene_id is None:
            return None
        return self._scenes.get_scene(scene_id)

    def _require_item(self, project_id: str, item_id: str) -> ReviewQueueItem:
        self._require_project(project_id)
        item = self._repo.get_item(item_id)
        if item is None or item.project_id != project_id:
            raise ReviewQueueServiceError(404, {"error": "review_queue_item_not_found"})
        return item

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise ReviewQueueServiceError(404, {"error": "project_not_found"})

    def _require_human(self, actor: Actor, *, action: str) -> Actor:
        try:
            return require_human_editor(
                actor, action=action, resource="Review Queue item"
            )
        except ActorError as exc:
            raise ReviewQueueServiceError(
                403,
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                    "actor_type": actor.actor_type or None,
                },
            ) from exc

    def _write_audit(
        self,
        *,
        actor: Actor,
        action: str,
        resource_type: str,
        resource_id: str,
        before_json: dict[str, Any] | None,
        after_json: dict[str, Any] | None,
    ) -> None:
        self._audit.write(
            actor_type=actor.actor_type or HUMAN_EDITOR,
            actor_id=actor.actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            correlation_id=get_request_id(),
        )


def _approval_body(
    editor: Actor, body: dict[str, Any], item: ReviewQueueItem
) -> dict[str, Any]:
    created_by = _optional_str(body.get("created_by")) or editor.actor_id or "主编"
    reason = _optional_str(body.get("comment")) or _optional_str(
        body.get("reason_code")
    )
    payload: dict[str, Any] = {
        "created_by": created_by,
        "candidate_change_id": item.subject_id,
        "project_id": item.project_id,
    }
    if reason is not None:
        payload["reason"] = reason
    return payload


def _require_reason_code(body: dict[str, Any]) -> str:
    reason = _optional_str(body.get("reason_code"))
    if reason is None:
        raise ReviewQueueServiceError(
            422,
            {
                "error": "reason_code_required",
                "message": (
                    "Each review decision must include a reason_code. "
                    "A text comment is optional."
                ),
            },
        )
    return reason


def _draft_pack(
    drafts: SceneDraftRepository, project_id: str, scene_id: str
) -> str | None:
    current = drafts.current_generated_draft(project_id, scene_id)
    if current is None:
        return None
    return current.context_pack_id


def _sort_items(
    items: list[ReviewQueueItem], sort: str | None
) -> list[ReviewQueueItem]:
    keys = [part.strip() for part in (sort or "").split(",") if part.strip()]
    if not keys:
        keys = ["-blocker", "created_at", "id"]

    def sort_tuple(item: ReviewQueueItem) -> tuple[Any, ...]:
        values: list[Any] = []
        for key in keys:
            descending = key.startswith("-")
            name = key[1:] if descending else key
            raw = _sort_value(item, name)
            if descending:
                if isinstance(raw, bool):
                    values.append(not raw)
                elif isinstance(raw, (int, float)):
                    values.append(-raw)
                else:
                    values.append(_invert_text(str(raw)))
            else:
                values.append(raw)
        return tuple(values)

    return sorted(items, key=sort_tuple)


def _sort_value(item: ReviewQueueItem, name: str) -> Any:
    aliases = {
        "blocker": "is_blocker",
        "is_blocker": "is_blocker",
        "chapter": "chapter_id",
        "chapter_id": "chapter_id",
        "status": "status",
        "task_status": "status",
        "created_at": "created_at",
        "subject_type": "subject_type",
        "id": "id",
    }
    field = aliases.get(name, name)
    if field == "is_blocker":
        return item.is_blocker
    if field == "chapter_id":
        return item.chapter_id or ""
    if field == "status":
        return item.status
    if field == "created_at":
        return item.created_at
    if field == "subject_type":
        return item.subject_type
    return item.id


def _invert_text(value: str) -> str:
    return "".join(chr(0x10FFFF - ord(char)) for char in value)


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
