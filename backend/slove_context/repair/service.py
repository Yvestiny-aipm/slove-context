"""Repair Task write path (node 5.2).

A task can be opened only from a RuleFailed Validation Report that
contains at least one Violation. Passed / ExecFailed-only / missing
violation are rejected.

After Completed (ReviseScenePlan / Regenerate / Reextract) this service
must start a 5.1 Validation Run. Recheck cannot be skipped. Completed
transitions to Rechecking when that run starts.

RecheckPassed means new Extracted candidates may be AwaitingVerdict
via 5.1. It is not Approval and does not write Canon.

HumanReject records reject-without-Canon on FailedValidation
candidates (4.2 reject requires AwaitingVerdict). No new extract is
produced, so recheck is N/A. Completing HumanReject does not approve
and does not write Canon.

May invoke existing 3.3 / 3.4 / 4.1 jobs. No chapter-level generate.
No real model. Fake Provider / in-process only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.candidate_change.models import (
    CANDIDATE_EXTRACTED,
    CANDIDATE_FAILED_VALIDATION,
    CANDIDATE_REJECTED,
    DECISION_REJECT,
    DEFAULT_SCHEMA_VERSION,
    CandidateChange,
)
from slove_context.candidate_change.repository import CandidateChangeRepository
from slove_context.candidate_change.service import (
    CandidateChangeService,
    CandidateChangeServiceError,
)
from slove_context.candidate_change.validate import (
    ApprovalDecisionSchemaError,
    validate_approval_decision,
)
from slove_context.logging import get_request_id
from slove_context.repair.models import (
    HUMAN_REJECT_SKIP_REASON,
    JOB_KIND_EXTRACT,
    JOB_KIND_SCENE_DRAFT,
    JOB_KIND_SCENE_PLAN,
    RECHECK_EXEC_FAILED,
    RECHECK_NOT_APPLICABLE,
    RECHECK_PASSED,
    RECHECK_RULE_FAILED,
    RECOMMENDED_ACTIONS,
    TASK_CANCELLABLE_STATES,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_IN_PROGRESS,
    TASK_OPENED,
    TASK_RECHECK_PASSED,
    TASK_RECHECKING,
    TASK_REWORK,
    RepairTask,
)
from slove_context.repair.repository import RepairRepository
from slove_context.scene.service import SceneService
from slove_context.scene_draft.context_pack import STATIC_CONTEXT_PACK_ID
from slove_context.scene_draft.models import (
    EXTRACTABLE_DRAFT_STATUSES,
    SceneDraft,
)
from slove_context.scene_draft.models import (
    JOB_SUCCEEDED as DRAFT_JOB_SUCCEEDED,
)
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.scene_draft.service import SceneDraftService, SceneDraftServiceError
from slove_context.scene_plan.models import JOB_SUCCEEDED as PLAN_JOB_SUCCEEDED
from slove_context.scene_plan.repository import ScenePlanRepository
from slove_context.scene_plan.service import ScenePlanService, ScenePlanServiceError
from slove_context.story.actors import (
    GENERATION_AGENT,
    HUMAN_EDITOR,
    SYSTEM,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.repository import StoryRepository
from slove_context.validation.models import (
    ACTION_HUMAN_REJECT,
    ACTION_REEXTRACT,
    ACTION_REGENERATE,
    ACTION_REVISE_SCENE_PLAN,
    OUTCOME_PASSED,
    OUTCOME_RULE_FAILED,
    RUN_PASSED,
    RUN_RULE_FAILED,
    ValidationReport,
    ValidationRun,
    Violation,
)
from slove_context.validation.service import ValidationService, ValidationServiceError

ALLOWED_WORK_ACTORS = frozenset({HUMAN_EDITOR, GENERATION_AGENT, SYSTEM})


class RepairServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class RepairService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        scene_service: SceneService,
        extract_repository: CandidateChangeRepository,
        plan_repository: ScenePlanRepository,
        draft_repository: SceneDraftRepository,
        repair_repository: RepairRepository,
        validation_service: ValidationService,
        plan_service: ScenePlanService,
        draft_service: SceneDraftService,
        extract_service: CandidateChangeService,
        audit_writer: AuditWriter,
    ) -> None:
        self._story = story_repository
        self._scenes = scene_service
        self._candidates = extract_repository
        self._plans = plan_repository
        self._drafts = draft_repository
        self._repo = repair_repository
        self._validation = validation_service
        self._plan_jobs = plan_service
        self._draft_jobs = draft_service
        self._extract_jobs = extract_service
        self._audit = audit_writer

    def open_task(
        self,
        *,
        project_id: str,
        actor: Actor,
        validation_run_id: str,
        action: str,
        violation_id: str | None = None,
    ) -> RepairTask:
        self._require_project(project_id)
        editor = self._require_human(actor, action="open")
        cleaned_action = _require_action(action)
        run = self._require_rule_failed_run(project_id, validation_run_id)
        report = self._require_rule_failed_report(project_id, run)
        index, violation = _select_violation(report, violation_id)
        now = _utc_now_z()
        task = RepairTask(
            id=str(uuid4()),
            project_id=project_id,
            scene_id=run.scene_id,
            validation_run_id=run.id,
            report_id=report.id,
            violation_id=_violation_ref(report.id, index),
            violation_index=index,
            action=cleaned_action,
            recommended_action=violation.recommended_action,
            state=TASK_OPENED,
            candidate_ids=list(run.candidate_ids),
            created_at=now,
            updated_at=now,
            created_by=editor.actor_id or "主编",
            actor_type=editor.actor_type,
        )
        self._repo.add_task(task)
        self._write_audit(
            actor=editor,
            action="repair_task.create",
            resource_type="repair_task",
            resource_id=task.id,
            before_json=None,
            after_json=task.to_audit_dict(),
        )
        return task

    def get_task(self, project_id: str, task_id: str) -> RepairTask:
        self._require_project(project_id)
        task = self._repo.get_task(task_id)
        if task is None or task.project_id != project_id:
            raise RepairServiceError(404, {"error": "repair_task_not_found"})
        return task

    def list_tasks(
        self, project_id: str, *, validation_run_id: str | None = None
    ) -> list[RepairTask]:
        self._require_project(project_id)
        if validation_run_id is not None:
            self._require_run(project_id, validation_run_id)
        return self._repo.list_tasks(project_id, validation_run_id=validation_run_id)

    def start_task(self, project_id: str, task_id: str, *, actor: Actor) -> RepairTask:
        task = self.get_task(project_id, task_id)
        worker = self._require_work_actor(actor, task.action, verb="start")
        if task.state not in {TASK_OPENED, TASK_REWORK}:
            raise RepairServiceError(
                409,
                {
                    "error": "repair_task_not_startable",
                    "message": (
                        "Start applies to Opened or Rework. "
                        "Failure / cancel keep the record."
                    ),
                    "state": task.state,
                },
            )
        self._transition(task, TASK_IN_PROGRESS, actor=worker)
        try:
            self._invoke_action(task, actor=worker)
        except RepairServiceError as exc:
            task.failure_reason = _error_reason(exc)
            self._transition(task, TASK_FAILED, actor=worker)
            raise
        except (
            ScenePlanServiceError,
            SceneDraftServiceError,
            CandidateChangeServiceError,
        ) as exc:
            task.failure_reason = _nested_reason(exc)
            self._transition(task, TASK_FAILED, actor=worker)
            raise RepairServiceError(exc.status_code, exc.detail) from exc
        return task

    def complete_task(
        self, project_id: str, task_id: str, *, actor: Actor
    ) -> RepairTask:
        task = self.get_task(project_id, task_id)
        worker = self._require_work_actor(actor, task.action, verb="complete")
        if task.state != TASK_IN_PROGRESS:
            raise RepairServiceError(
                409,
                {
                    "error": "repair_task_not_completable",
                    "message": (
                        "Complete applies to InProgress only. "
                        "Completed must start a Validation Run; recheck "
                        "cannot be skipped except HumanReject with no "
                        "new extract (still not approve, still no Canon)."
                    ),
                    "state": task.state,
                },
            )
        self._transition(task, TASK_COMPLETED, actor=worker)
        if task.action == ACTION_HUMAN_REJECT:
            if not task.rejected_candidate_ids:
                self._human_reject(task, actor=worker)
            task.recheck_status = RECHECK_NOT_APPLICABLE
            task.recheck_skipped_reason = HUMAN_REJECT_SKIP_REASON
            self._repo.save_task(task)
            self._write_audit(
                actor=worker,
                action="repair_task.complete",
                resource_type="repair_task",
                resource_id=task.id,
                before_json=None,
                after_json=task.to_audit_dict(),
            )
            return task
        self._start_recheck(task, actor=worker)
        return task

    def cancel_task(self, project_id: str, task_id: str, *, actor: Actor) -> RepairTask:
        editor = self._require_human(actor, action="cancel")
        task = self.get_task(project_id, task_id)
        if task.state not in TASK_CANCELLABLE_STATES:
            raise RepairServiceError(
                409,
                {
                    "error": "repair_task_not_cancellable",
                    "message": (
                        "Cancel keeps the record and does not delete it. "
                        "RecheckPassed / Cancelled are kept."
                    ),
                    "state": task.state,
                },
            )
        self._transition(task, TASK_CANCELLED, actor=editor)
        return task

    def _invoke_action(self, task: RepairTask, *, actor: Actor) -> None:
        if task.action == ACTION_HUMAN_REJECT:
            self._human_reject(task, actor=actor)
            return
        if task.action == ACTION_REVISE_SCENE_PLAN:
            self._revise_scene_plan(task, actor=actor)
            self._regenerate(task, actor=actor)
            self._reextract(task, actor=actor)
            return
        if task.action == ACTION_REGENERATE:
            self._regenerate(task, actor=actor)
            self._reextract(task, actor=actor)
            return
        if task.action == ACTION_REEXTRACT:
            self._reextract(task, actor=actor)
            return
        raise RepairServiceError(
            422,
            {
                "error": "invalid_recommended_action",
                "message": (
                    "recommended_action allowed values ONLY: "
                    "ReviseScenePlan / Regenerate / Reextract / HumanReject."
                ),
                "action": task.action,
            },
        )

    def _revise_scene_plan(self, task: RepairTask, *, actor: Actor) -> None:
        snapshot_id = self._require_snapshot_id(task)
        job = self._plan_jobs.trigger_job(
            project_id=task.project_id,
            scene_id=task.scene_id,
            snapshot_id=snapshot_id,
            actor=actor,
        )
        self._record_job(task, JOB_KIND_SCENE_PLAN, job.id)
        if job.state != PLAN_JOB_SUCCEEDED:
            raise RepairServiceError(
                409,
                {
                    "error": "repair_job_failed",
                    "message": "ReviseScenePlan did not produce a valid Scene Plan.",
                    "job_id": job.id,
                    "job_state": job.state,
                },
            )

    def _regenerate(self, task: RepairTask, *, actor: Actor) -> None:
        plan = self._plans.current_plan(task.project_id, task.scene_id)
        if plan is None:
            raise RepairServiceError(
                409,
                {
                    "error": "scene_plan_required",
                    "message": (
                        "Regenerate requires a current Scene Plan. "
                        "There is no chapter-level generate entrance."
                    ),
                },
            )
        job = self._draft_jobs.trigger_job(
            project_id=task.project_id,
            scene_id=task.scene_id,
            snapshot_id=plan.snapshot_id,
            plan_id=plan.id,
            context_pack_id=STATIC_CONTEXT_PACK_ID,
            actor=actor,
        )
        self._record_job(task, JOB_KIND_SCENE_DRAFT, job.id)
        if job.state != DRAFT_JOB_SUCCEEDED or job.draft_id is None:
            raise RepairServiceError(
                409,
                {
                    "error": "repair_job_failed",
                    "message": "Regenerate did not produce a Scene Draft revision.",
                    "job_id": job.id,
                    "job_state": job.state,
                },
            )

    def _reextract(self, task: RepairTask, *, actor: Actor) -> None:
        draft = self._require_extractable_draft(task.project_id, task.scene_id)
        job = self._extract_jobs.trigger_job(
            project_id=task.project_id,
            scene_id=task.scene_id,
            revision_id=draft.id,
            actor=actor,
        )
        self._record_job(task, JOB_KIND_EXTRACT, job.id)
        if job.state != "succeeded":
            raise RepairServiceError(
                409,
                {
                    "error": "repair_job_failed",
                    "message": "Reextract did not produce Extracted candidates.",
                    "job_id": job.id,
                    "job_state": job.state,
                },
            )
        task.produced_candidate_ids = list(job.candidate_ids)
        self._repo.save_task(task)

    def _human_reject(self, task: RepairTask, *, actor: Actor) -> None:
        editor = self._require_human(actor, action="HumanReject")
        rejected: list[str] = []
        for candidate_id in task.candidate_ids:
            candidate = self._candidates.get_candidate(candidate_id)
            if candidate is None or candidate.project_id != task.project_id:
                continue
            if candidate.status != CANDIDATE_FAILED_VALIDATION:
                continue
            self._reject_without_canon(candidate, editor)
            rejected.append(candidate.id)
        if not rejected:
            raise RepairServiceError(
                409,
                {
                    "error": "human_reject_targets_missing",
                    "message": (
                        "HumanReject records reject-without-Canon on "
                        "FailedValidation candidates from the RuleFailed "
                        "run. 4.2 reject requires AwaitingVerdict; this "
                        "path covers FailedValidation. No Canon write."
                    ),
                },
            )
        task.rejected_candidate_ids = rejected
        self._repo.save_task(task)

    def _reject_without_canon(self, candidate: CandidateChange, editor: Actor) -> None:
        decision = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "id": str(uuid4()),
            "project_id": candidate.project_id,
            "created_at": _utc_now_z(),
            "created_by": editor.actor_id or "主编",
            "candidate_change_id": candidate.id,
            "decision": DECISION_REJECT,
            "reason": (
                "HumanReject Repair Task: reject without writing Canon. "
                "Not auto-approve. Not submit."
            ),
        }
        try:
            validate_approval_decision(decision)
        except ApprovalDecisionSchemaError as exc:
            raise RepairServiceError(
                422,
                {
                    "error": "approval_decision_schema_failed",
                    "message": (
                        "HumanReject records a Reject decision without writing Canon."
                    ),
                    "errors": exc.errors,
                },
            ) from exc
        before = candidate.to_audit_dict()
        candidate.status = CANDIDATE_REJECTED
        candidate.payload["status"] = CANDIDATE_REJECTED
        candidate.approval_decision = dict(decision)
        self._candidates.save_candidate(candidate)
        self._write_audit(
            actor=editor,
            action="candidate_change.reject",
            resource_type="candidate_change",
            resource_id=candidate.id,
            before_json=before,
            after_json=candidate.to_audit_dict(),
        )

    def _start_recheck(self, task: RepairTask, *, actor: Actor) -> None:
        self._transition(
            task, TASK_RECHECKING, actor=Actor(actor_type=SYSTEM, actor_id=None)
        )
        candidate_ids = list(task.produced_candidate_ids) or [
            item.id
            for item in self._candidates.list_candidates(task.project_id, task.scene_id)
            if item.status == CANDIDATE_EXTRACTED
        ]
        try:
            run = self._validation.trigger_run(
                project_id=task.project_id,
                actor=Actor(actor_type=SYSTEM, actor_id=None),
                scene_id=task.scene_id,
                candidate_ids=candidate_ids or None,
                snapshot_id=self._source_run(task).snapshot_id,
            )
        except ValidationServiceError as exc:
            task.failure_reason = _nested_reason(exc)
            task.recheck_status = RECHECK_EXEC_FAILED
            self._transition(
                task, TASK_FAILED, actor=Actor(actor_type=SYSTEM, actor_id=None)
            )
            raise RepairServiceError(exc.status_code, exc.detail) from exc
        task.recheck_run_id = run.id
        self._apply_recheck_outcome(task, run)

    def _apply_recheck_outcome(self, task: RepairTask, run: ValidationRun) -> None:
        if run.state == RUN_PASSED or run.outcome == OUTCOME_PASSED:
            task.recheck_status = RECHECK_PASSED
            self._transition(
                task,
                TASK_RECHECK_PASSED,
                actor=Actor(actor_type=SYSTEM, actor_id=None),
            )
            return
        if run.state == RUN_RULE_FAILED or run.outcome == OUTCOME_RULE_FAILED:
            task.recheck_status = RECHECK_RULE_FAILED
            task.failure_reason = "recheck_rule_failed"
            self._transition(
                task, TASK_FAILED, actor=Actor(actor_type=SYSTEM, actor_id=None)
            )
            return
        task.recheck_status = RECHECK_EXEC_FAILED
        task.failure_reason = run.failure_reason or "recheck_exec_failed"
        self._transition(
            task, TASK_FAILED, actor=Actor(actor_type=SYSTEM, actor_id=None)
        )

    def _require_rule_failed_run(
        self, project_id: str, validation_run_id: str
    ) -> ValidationRun:
        run = self._require_run(project_id, validation_run_id)
        if run.state != RUN_RULE_FAILED and run.outcome != OUTCOME_RULE_FAILED:
            raise RepairServiceError(
                409,
                {
                    "error": "repair_requires_rule_failed",
                    "message": (
                        "A Repair Task can be opened ONLY from a "
                        "RuleFailed Validation Report / Violation. "
                        "Passed, ExecFailed-only, Cancelled, or a run "
                        "with no Violation cannot open a task."
                    ),
                    "state": run.state,
                    "outcome": run.outcome,
                },
            )
        return run

    def _require_rule_failed_report(
        self, project_id: str, run: ValidationRun
    ) -> ValidationReport:
        try:
            report = self._validation.get_report(project_id, run.id)
        except ValidationServiceError as exc:
            raise RepairServiceError(exc.status_code, exc.detail) from exc
        if report.outcome != OUTCOME_RULE_FAILED or not report.violations:
            raise RepairServiceError(
                409,
                {
                    "error": "repair_requires_violation",
                    "message": (
                        "A Repair Task needs a RuleFailed report with at "
                        "least one Violation. ExecFailed-only and Passed "
                        "reports cannot open a task."
                    ),
                    "outcome": report.outcome,
                    "violation_count": len(report.violations),
                },
            )
        return report

    def _require_run(self, project_id: str, run_id: str) -> ValidationRun:
        try:
            return self._validation.get_run(project_id, run_id)
        except ValidationServiceError as exc:
            raise RepairServiceError(exc.status_code, exc.detail) from exc

    def _source_run(self, task: RepairTask) -> ValidationRun:
        return self._require_run(task.project_id, task.validation_run_id)

    def _require_snapshot_id(self, task: RepairTask) -> str:
        run = self._source_run(task)
        if run.snapshot_id:
            return run.snapshot_id
        plan = self._plans.current_plan(task.project_id, task.scene_id)
        if plan is not None and plan.snapshot_id:
            return plan.snapshot_id
        raise RepairServiceError(
            409,
            {
                "error": "snapshot_required",
                "message": (
                    "ReviseScenePlan needs the source run snapshot or "
                    "the current Scene Plan snapshot. No Context Pack "
                    "assembler."
                ),
            },
        )

    def _require_extractable_draft(self, project_id: str, scene_id: str) -> SceneDraft:
        for draft in self._drafts.list_drafts(project_id, scene_id):
            if draft.status in EXTRACTABLE_DRAFT_STATUSES:
                return draft
        raise RepairServiceError(
            409,
            {
                "error": "scene_draft_required",
                "message": (
                    "Reextract needs an immutable Scene Draft revision. "
                    "Missing drafts cannot start extract. No chapter-level "
                    "generate."
                ),
            },
        )

    def _record_job(self, task: RepairTask, kind: str, job_id: str) -> None:
        task.invoked_jobs.append({"kind": kind, "id": job_id})
        self._repo.save_task(task)

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise RepairServiceError(404, {"error": "project_not_found"})

    def _require_human(self, actor: Actor, *, action: str) -> Actor:
        try:
            return require_human_editor(actor, action=action, resource="Repair Task")
        except ActorError as exc:
            raise RepairServiceError(
                403,
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                    "actor_type": actor.actor_type or None,
                },
            ) from exc

    def _require_work_actor(self, actor: Actor, action: str, *, verb: str) -> Actor:
        if action == ACTION_HUMAN_REJECT:
            return self._require_human(actor, action=verb)
        actor_type = actor.actor_type or GENERATION_AGENT
        if actor_type not in ALLOWED_WORK_ACTORS:
            raise RepairServiceError(
                403,
                {
                    "error": "actor_not_allowed",
                    "message": (
                        "Start / complete may be the human 主编, a "
                        "generation Agent, or the system. Review agents "
                        "cannot treat repair as Approval. No auto-approve."
                    ),
                    "actor_type": actor_type,
                },
            )
        return Actor(actor_type=actor_type, actor_id=actor.actor_id)

    def _transition(self, task: RepairTask, new_state: str, *, actor: Actor) -> None:
        before = task.to_audit_dict()
        previous = task.state
        now = _utc_now_z()
        task.transitions.append({"from": previous, "to": new_state, "at": now})
        task.state = new_state
        task.updated_at = now
        self._repo.save_task(task)
        self._write_audit(
            actor=actor,
            action="repair_task.transition",
            resource_type="repair_task",
            resource_id=task.id,
            before_json=before,
            after_json=task.to_audit_dict(),
        )

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
            actor_type=actor.actor_type or SYSTEM,
            actor_id=actor.actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            correlation_id=get_request_id(),
        )


def _require_action(action: str) -> str:
    cleaned = action.strip()
    if cleaned not in RECOMMENDED_ACTIONS:
        raise RepairServiceError(
            422,
            {
                "error": "invalid_recommended_action",
                "message": (
                    "recommended_action allowed values ONLY: "
                    "ReviseScenePlan / Regenerate / Reextract / HumanReject."
                ),
                "action": action,
            },
        )
    return cleaned


def _select_violation(
    report: ValidationReport, violation_id: str | None
) -> tuple[int, Violation]:
    if not report.violations:
        raise RepairServiceError(
            409,
            {
                "error": "repair_requires_violation",
                "message": "No Violation is available to open a Repair Task.",
            },
        )
    if violation_id is None or not violation_id.strip():
        return 0, report.violations[0]
    cleaned = violation_id.strip()
    refs = [_violation_ref(report.id, index) for index in range(len(report.violations))]
    if cleaned in refs:
        index = refs.index(cleaned)
        return index, report.violations[index]
    if cleaned.isdigit():
        index = int(cleaned)
        if 0 <= index < len(report.violations):
            return index, report.violations[index]
    raise RepairServiceError(
        404,
        {
            "error": "violation_not_found",
            "message": "The requested violation_id is not on this RuleFailed report.",
            "violation_id": cleaned,
        },
    )


def _violation_ref(report_id: str, index: int) -> str:
    return f"{report_id}:{index}"


def _error_reason(exc: RepairServiceError) -> str:
    detail = exc.detail
    if isinstance(detail, dict) and isinstance(detail.get("error"), str):
        return detail["error"]
    return str(detail)


def _nested_reason(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict) and isinstance(detail.get("error"), str):
        return detail["error"]
    return type(exc).__name__


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
