"""Batch scheduler (node 8.4).

Plans and enqueues scene DAGs through 8.3 / 8.1 / 8.2.
Does not bypass PermissionGuard. Does not write Canon. Does not
auto-approve. dry-run never calls the model or enqueues write jobs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.agents.permissions import PermissionDenied, PermissionGuard
from slove_context.audit import AuditWriter
from slove_context.dags.models import DAG_BLOCKED, DAG_FAILED, DAG_WAITING_HUMAN
from slove_context.dags.service import DagServiceError
from slove_context.jobs.models import JOB_TYPES
from slove_context.logging import get_request_id
from slove_context.scene.models import Scene
from slove_context.scene.service import SceneService, SceneServiceError
from slove_context.scheduler.deps import SchedulerServices
from slove_context.scheduler.models import (
    ALERT_ACKNOWLEDGED,
    ALERT_BUDGET_EXCEEDED,
    ALERT_CONSECUTIVE_FAILURES,
    ALERT_OPEN,
    DECISION_ENQUEUED,
    DECISION_HELD,
    DEFAULT_CONCURRENCY,
    DEFAULT_DAILY_TOKEN_BUDGET,
    DEFAULT_ESTIMATED_COST_PER_SCENE,
    DEFAULT_ESTIMATED_TOKENS_PER_DAG,
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_PER_SCENE_COST_CAP,
    KIND_CANON_WRITE,
    KIND_PLANNING,
    KIND_PROSE_WRITE,
    KIND_READ_CHECK,
    REASON_CONCURRENCY,
    REASON_DRY_RUN,
    STATUS_CANCELLED,
    STATUS_PAUSED,
    STATUS_PLANNED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    WORKER_JOBS_PER_DAG,
    BudgetCounter,
    ScheduleAlert,
    ScheduleConfig,
    ScheduleDecision,
    ScheduleRun,
    default_config,
)
from slove_context.scheduler.parallelism import (
    ActiveSlot,
    decide,
)
from slove_context.scheduler.repository import ScheduleRepository
from slove_context.story.actors import (
    GENERATION_AGENT,
    HUMAN_EDITOR,
    REVIEW_AGENT,
    SYSTEM,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.repository import StoryRepository

ALLOWED_START_ACTORS = frozenset({HUMAN_EDITOR, GENERATION_AGENT, SYSTEM})
ALLOWED_TICK_ACTORS = frozenset({HUMAN_EDITOR, GENERATION_AGENT, SYSTEM})


class ScheduleServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class ScheduleService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        scene_service: SceneService,
        schedule_repository: ScheduleRepository,
        audit_writer: AuditWriter,
        services: SchedulerServices,
        estimated_tokens_per_dag: int = DEFAULT_ESTIMATED_TOKENS_PER_DAG,
        estimated_cost_per_scene: float = DEFAULT_ESTIMATED_COST_PER_SCENE,
    ) -> None:
        self._story = story_repository
        self._scenes = scene_service
        self._repo = schedule_repository
        self._audit = audit_writer
        self._svc = services
        self._guard = PermissionGuard()
        self._tokens_per_dag = estimated_tokens_per_dag
        self._cost_per_scene = estimated_cost_per_scene

    def configure(
        self,
        project_id: str,
        *,
        actor: Actor,
        concurrency: int | None = None,
        daily_token_budget: int | None = None,
        per_scene_cost_cap: float | None = None,
        failure_threshold: int | None = None,
    ) -> ScheduleConfig:
        self._require_project(project_id)
        trigger = _require_configure_actor(actor)
        existing = self._repo.get_config(project_id)
        now = _utc_now_z()
        before = existing.to_audit_dict() if existing is not None else None
        config = ScheduleConfig(
            project_id=project_id,
            concurrency=_require_positive_int(
                concurrency
                if concurrency is not None
                else (existing.concurrency if existing else DEFAULT_CONCURRENCY),
                "concurrency",
            ),
            daily_token_budget=_require_nonneg_int(
                daily_token_budget
                if daily_token_budget is not None
                else (
                    existing.daily_token_budget
                    if existing
                    else DEFAULT_DAILY_TOKEN_BUDGET
                ),
                "daily_token_budget",
            ),
            per_scene_cost_cap=_require_nonneg_float(
                per_scene_cost_cap
                if per_scene_cost_cap is not None
                else (
                    existing.per_scene_cost_cap
                    if existing
                    else DEFAULT_PER_SCENE_COST_CAP
                ),
                "per_scene_cost_cap",
            ),
            failure_threshold=_require_positive_int(
                failure_threshold
                if failure_threshold is not None
                else (
                    existing.failure_threshold
                    if existing
                    else DEFAULT_FAILURE_THRESHOLD
                ),
                "failure_threshold",
            ),
            updated_at=now,
            updated_by=trigger.actor_id or "scheduler",
            actor_type=trigger.actor_type,
        )
        self._repo.save_config(config)
        self._write_audit(
            actor=trigger,
            action="schedule.config",
            resource_type="schedule_config",
            resource_id=project_id,
            before_json=before,
            after_json=config.to_audit_dict(),
        )
        return config

    def get_config(self, project_id: str) -> ScheduleConfig:
        self._require_project(project_id)
        existing = self._repo.get_config(project_id)
        if existing is not None:
            return existing
        now = _utc_now_z()
        config = default_config(
            project_id, updated_at=now, updated_by="scheduler-default"
        )
        self._repo.save_config(config)
        return config

    def dry_run(
        self,
        project_id: str,
        *,
        actor: Actor,
        snapshot_id: str,
        chapter_id: str | None = None,
    ) -> dict[str, Any]:
        """Execution plan + estimated counts. No model. No write jobs. No Canon."""
        trigger = _require_start_actor(actor)
        self._assert_not_canon_writer(trigger)
        self._require_project(project_id)
        cleaned_snapshot = _require_snapshot(snapshot_id)
        config = self.get_config(project_id)
        scenes = self._candidate_scenes(project_id, chapter_id)
        scenes_by_id = {item.id: item for item in self._scenes.list_scenes(project_id)}
        now = _utc_now_z()
        run = ScheduleRun(
            id=str(uuid4()),
            project_id=project_id,
            snapshot_id=cleaned_snapshot,
            status=STATUS_PLANNED,
            created_at=now,
            updated_at=now,
            created_by=trigger.actor_id or "scheduler",
            actor_type=trigger.actor_type,
            chapter_id=_clean_optional(chapter_id),
            dry_run=True,
            correlation_id=get_request_id() or str(uuid4()),
        )
        decisions = self._plan_scenes(
            run,
            scenes=scenes,
            scenes_by_id=scenes_by_id,
            config=config,
            enqueue=False,
            actor=trigger,
        )
        generatable = [item for item in scenes if self._scenes.is_generatable(item)]
        run.estimated_dag_count = len(generatable)
        run.estimated_task_count = len(generatable) * WORKER_JOBS_PER_DAG
        run.enqueued_count = 0
        self._repo.add_run(run)
        for decision in decisions:
            if decision.action == DECISION_ENQUEUED:
                decision.action = DECISION_HELD
                decision.reason_code = REASON_DRY_RUN
                decision.message = (
                    "dry-run: execution plan only. No model, no write job, "
                    "no Canon write."
                )
            self._repo.add_decision(decision)
        run.held_count = sum(1 for item in decisions if item.action == DECISION_HELD)
        run.updated_at = now
        self._repo.save_run(run)
        self._write_audit(
            actor=trigger,
            action="schedule.dry_run",
            resource_type="schedule_run",
            resource_id=run.id,
            before_json=None,
            after_json=run.to_audit_dict(),
        )
        return {
            "run": run.to_public_dict(),
            "plan": [item.to_public_dict() for item in decisions],
            "estimated_task_count": run.estimated_task_count,
            "estimated_dag_count": run.estimated_dag_count,
            "called_model": False,
            "enqueued_write_jobs": False,
            "writes_canon": False,
            "auto_approved": False,
        }

    def start(
        self,
        project_id: str,
        *,
        actor: Actor,
        snapshot_id: str,
        chapter_id: str | None = None,
    ) -> ScheduleRun:
        trigger = _require_start_actor(actor)
        self._assert_not_canon_writer(trigger)
        self._require_project(project_id)
        cleaned_snapshot = _require_snapshot(snapshot_id)
        config = self.get_config(project_id)
        now = _utc_now_z()
        run = ScheduleRun(
            id=str(uuid4()),
            project_id=project_id,
            snapshot_id=cleaned_snapshot,
            status=STATUS_RUNNING,
            created_at=now,
            updated_at=now,
            created_by=trigger.actor_id or "scheduler",
            actor_type=trigger.actor_type,
            chapter_id=_clean_optional(chapter_id),
            dry_run=False,
            correlation_id=get_request_id() or str(uuid4()),
        )
        self._repo.add_run(run)
        self._write_audit(
            actor=trigger,
            action="schedule.start",
            resource_type="schedule_run",
            resource_id=run.id,
            before_json=None,
            after_json=run.to_audit_dict(),
        )
        self._advance_run(run, actor=trigger, config=config)
        return run

    def pause(self, project_id: str, run_id: str, *, actor: Actor) -> ScheduleRun:
        editor = self._require_human(actor, action="pause")
        run = self.get_run(project_id, run_id)
        return self._pause_run(
            run,
            actor=editor,
            reason="human_pause",
            alert_kind=None,
        )

    def resume(self, project_id: str, run_id: str, *, actor: Actor) -> ScheduleRun:
        editor = self._require_human(actor, action="resume")
        self._assert_not_canon_writer(editor)
        run = self.get_run(project_id, run_id)
        if run.status == STATUS_CANCELLED:
            raise ScheduleServiceError(
                409,
                {
                    "error": "run_cancelled",
                    "message": "A cancelled run is kept and is not resumed.",
                    "kept": True,
                },
            )
        if run.status != STATUS_PAUSED:
            raise ScheduleServiceError(
                409,
                {
                    "error": "run_not_paused",
                    "message": "Only a paused run can be human-resumed. Resume is not automatic.",
                    "status": run.status,
                    "kept": True,
                },
            )
        before = run.to_audit_dict()
        run.status = STATUS_RUNNING
        run.paused_reason = None
        run.updated_at = _utc_now_z()
        self._repo.save_run(run)
        for alert in self._repo.list_alerts(project_id):
            if alert.run_id == run.id and alert.status == ALERT_OPEN:
                alert.status = ALERT_ACKNOWLEDGED
        self._write_audit(
            actor=editor,
            action="schedule.resume",
            resource_type="schedule_run",
            resource_id=run.id,
            before_json=before,
            after_json=run.to_audit_dict(),
        )
        return run

    def cancel(self, project_id: str, run_id: str, *, actor: Actor) -> ScheduleRun:
        editor = self._require_human(actor, action="cancel")
        run = self.get_run(project_id, run_id)
        if run.status == STATUS_CANCELLED:
            return run
        before = run.to_audit_dict()
        run.status = STATUS_CANCELLED
        run.updated_at = _utc_now_z()
        self._repo.save_run(run)
        self._write_audit(
            actor=editor,
            action="schedule.cancel",
            resource_type="schedule_run",
            resource_id=run.id,
            before_json=before,
            after_json=run.to_audit_dict(),
        )
        return run

    def get_run(self, project_id: str, run_id: str) -> ScheduleRun:
        self._require_project(project_id)
        run = self._repo.get_run(run_id)
        if run is None or run.project_id != project_id:
            raise ScheduleServiceError(404, {"error": "schedule_run_not_found"})
        return run

    def list_runs(self, project_id: str) -> list[ScheduleRun]:
        self._require_project(project_id)
        return self._repo.list_runs(project_id)

    def list_alerts(self, project_id: str) -> list[ScheduleAlert]:
        self._require_project(project_id)
        return self._repo.list_alerts(project_id)

    def list_decisions(
        self, project_id: str, *, run_id: str | None = None
    ) -> list[ScheduleDecision]:
        self._require_project(project_id)
        return self._repo.list_decisions(project_id, run_id=run_id)

    def tick(self, *, actor: Actor) -> dict[str, Any]:
        """Process every running project. Independent projects proceed together."""
        trigger = _require_tick_actor(actor)
        self._assert_not_canon_writer(trigger)
        processed: list[str] = []
        runs_out: list[dict[str, Any]] = []
        for run in self._repo.list_running_runs():
            config = self.get_config(run.project_id)
            self._advance_run(run, actor=trigger, config=config)
            processed.append(run.project_id)
            runs_out.append(run.to_public_dict())
        self._write_audit(
            actor=trigger,
            action="schedule.tick",
            resource_type="schedule_tick",
            resource_id=trigger.actor_id or "scheduler",
            before_json=None,
            after_json={
                "processed_project_ids": processed,
                "run_count": len(runs_out),
                "writes_canon": False,
                "auto_approved": False,
            },
        )
        return {
            "processed_project_ids": processed,
            "runs": runs_out,
            "writes_canon": False,
            "auto_approved": False,
        }

    def inspect_scene(
        self,
        project_id: str,
        *,
        scene_id: str,
        snapshot_id: str | None,
        task_kind: str,
    ) -> dict[str, Any]:
        self._require_project(project_id)
        config = self.get_config(project_id)
        try:
            scene = self._scenes.get_scene(project_id, scene_id)
        except SceneServiceError as exc:
            raise ScheduleServiceError(exc.status_code, exc.detail) from exc
        scenes_by_id = {item.id: item for item in self._scenes.list_scenes(project_id)}
        kind = inspect_task_kind(task_kind)
        verdict = decide(
            scene,
            task_kind=kind,
            snapshot_id=_clean_optional(snapshot_id),
            unsatisfied_dependencies=self._scenes.unsatisfied_dependencies(scene),
            active=[],
            scenes_by_id=scenes_by_id,
            estimated_cost=self._cost_per_scene,
            per_scene_cost_cap=config.per_scene_cost_cap,
        )
        return {
            "scene_id": scene.id,
            "project_id": project_id,
            "action": verdict.action,
            "reason_code": verdict.reason_code,
            "message": verdict.message,
            "task_kind": verdict.task_kind,
            "generatable": self._scenes.is_generatable(scene),
            "writes_canon": False,
            "auto_approved": False,
        }

    def reject_canon_write(self, project_id: str, *, actor: Actor, action: str) -> None:
        """Scheduler never approves or submits Canon. Always 403."""
        self._require_project(project_id)
        try:
            if action == "approve":
                self._guard.assert_actor_may_approve_canon(actor)
            else:
                self._guard.assert_actor_may_submit_canon(actor)
        except PermissionDenied:
            pass
        raise ScheduleServiceError(
            403,
            {
                "error": "scheduler_cannot_write_canon",
                "message": (
                    "The batch scheduler cannot approve or submit Canon. "
                    "Canon write remains 4.2 human submit / 8.3 canon_commit "
                    "after a human 主编 approve. No Agent / Worker / "
                    "scheduler / system actor may submit Canon."
                ),
                "action": action,
                "actor_type": actor.actor_type or None,
                "writes_canon": False,
                "auto_approved": False,
            },
        )

    def _advance_run(
        self, run: ScheduleRun, *, actor: Actor, config: ScheduleConfig
    ) -> None:
        if run.status in {STATUS_CANCELLED, STATUS_PAUSED, STATUS_SUCCEEDED}:
            return
        if run.dry_run:
            return
        budget = self._budget_for(run.project_id)
        if budget.tokens_used >= config.daily_token_budget:
            self._pause_run(
                run,
                actor=Actor(actor_type=SYSTEM, actor_id="batch-scheduler"),
                reason=ALERT_BUDGET_EXCEEDED,
                alert_kind=ALERT_BUDGET_EXCEEDED,
                tokens_used=budget.tokens_used,
            )
            return
        if run.consecutive_failures >= config.failure_threshold:
            self._pause_run(
                run,
                actor=Actor(actor_type=SYSTEM, actor_id="batch-scheduler"),
                reason=ALERT_CONSECUTIVE_FAILURES,
                alert_kind=ALERT_CONSECUTIVE_FAILURES,
                consecutive_failures=run.consecutive_failures,
            )
            return

        scenes = self._candidate_scenes(run.project_id, run.chapter_id)
        scenes_by_id = {
            item.id: item for item in self._scenes.list_scenes(run.project_id)
        }
        in_flight = self._in_flight_slots(run)
        decisions = self._plan_scenes(
            run,
            scenes=scenes,
            scenes_by_id=scenes_by_id,
            config=config,
            enqueue=True,
            actor=actor,
            in_flight=in_flight,
        )
        for decision in decisions:
            if decision.action != DECISION_ENQUEUED:
                self._repo.add_decision(decision)
                continue
            scene = scenes_by_id[decision.scene_id]
            dag_id = self._enqueue_scene_dag(run, scene, actor=actor, config=config)
            decision.dag_id = dag_id
            self._repo.add_decision(decision)
            if run.status == STATUS_PAUSED:
                return

        if not scenes:
            run.status = STATUS_SUCCEEDED
        run.updated_at = _utc_now_z()
        self._repo.save_run(run)

    def _plan_scenes(
        self,
        run: ScheduleRun,
        *,
        scenes: list[Scene],
        scenes_by_id: dict[str, Scene],
        config: ScheduleConfig,
        enqueue: bool,
        actor: Actor,
        in_flight: list[ActiveSlot] | None = None,
    ) -> list[ScheduleDecision]:
        del actor
        now = _utc_now_z()
        active = list(in_flight or [])
        decisions: list[ScheduleDecision] = []
        already = set(run.dag_ids)
        decided_scenes = {
            item.scene_id
            for item in self._repo.list_decisions(run.project_id, run_id=run.id)
            if item.action == DECISION_ENQUEUED and item.dag_id
        }
        completed = self._completed_scene_ids(run)
        held = 0
        for scene in scenes:
            if scene.id in decided_scenes or scene.id in already:
                continue
            unsatisfied = self._scenes.unsatisfied_dependencies(scene)
            verdict = decide(
                scene,
                task_kind=KIND_PROSE_WRITE,
                snapshot_id=run.snapshot_id,
                unsatisfied_dependencies=unsatisfied,
                active=active,
                scenes_by_id=scenes_by_id,
                estimated_cost=self._cost_per_scene,
                per_scene_cost_cap=config.per_scene_cost_cap,
                completed_scene_ids=completed,
            )
            action = verdict.action
            if action == DECISION_ENQUEUED and enqueue:
                if len(
                    [slot for slot in active if slot.project_id == run.project_id]
                ) >= (config.concurrency):
                    action = DECISION_HELD
                    reason = REASON_CONCURRENCY
                    message = "Per-project concurrency limit; scene stays held."
                else:
                    reason = verdict.reason_code
                    message = verdict.message
                    active.append(
                        ActiveSlot(
                            project_id=run.project_id,
                            scene_id=scene.id,
                            snapshot_id=run.snapshot_id,
                            task_kind=KIND_PROSE_WRITE,
                        )
                    )
            elif action == DECISION_ENQUEUED and not enqueue:
                reason = verdict.reason_code
                message = verdict.message
            else:
                reason = verdict.reason_code
                message = verdict.message
            if action == DECISION_HELD:
                held += 1
            decision = ScheduleDecision(
                id=str(uuid4()),
                run_id=run.id,
                project_id=run.project_id,
                scene_id=scene.id,
                action=action,
                reason_code=reason,
                task_kind=verdict.task_kind,
                snapshot_id=run.snapshot_id,
                dag_id=None,
                message=message,
                created_at=now,
                parallel_with=[
                    slot.scene_id
                    for slot in active
                    if slot.scene_id != scene.id and slot.project_id == run.project_id
                ],
            )
            decisions.append(decision)
        run.held_count = held
        run.estimated_dag_count = sum(
            1 for item in decisions if item.action == DECISION_ENQUEUED
        )
        run.estimated_task_count = run.estimated_dag_count * WORKER_JOBS_PER_DAG
        return decisions

    def _enqueue_scene_dag(
        self,
        run: ScheduleRun,
        scene: Scene,
        *,
        actor: Actor,
        config: ScheduleConfig,
    ) -> str | None:
        self._assert_worker_dispatch_allowed()
        orchestrator = Actor(actor_type=SYSTEM, actor_id="batch-scheduler")
        try:
            dag = self._svc.dags.create_dag(
                project_id=run.project_id,
                scene_id=scene.id,
                snapshot_id=run.snapshot_id,
                actor=orchestrator,
            )
            advanced = self._svc.dags.advance(
                run.project_id, dag.id, actor=orchestrator
            )
        except DagServiceError as exc:
            run.consecutive_failures += 1
            run.updated_at = _utc_now_z()
            self._repo.save_run(run)
            if run.consecutive_failures >= config.failure_threshold:
                self._pause_run(
                    run,
                    actor=Actor(actor_type=SYSTEM, actor_id="batch-scheduler"),
                    reason=ALERT_CONSECUTIVE_FAILURES,
                    alert_kind=ALERT_CONSECUTIVE_FAILURES,
                    consecutive_failures=run.consecutive_failures,
                )
            else:
                detail = (
                    exc.detail if isinstance(exc.detail, dict) else {"error": str(exc)}
                )
                self._write_audit(
                    actor=actor,
                    action="schedule.enqueue_failed",
                    resource_type="schedule_run",
                    resource_id=run.id,
                    before_json=None,
                    after_json={
                        "scene_id": scene.id,
                        "error": str(detail.get("error") or "dag_failed"),
                        "kept": True,
                        "writes_canon": False,
                    },
                )
            return None

        run.dag_ids.append(advanced.id)
        run.enqueued_count += 1
        tokens = self._tokens_per_dag
        cost = self._cost_per_scene
        run.tokens_used += tokens
        run.cost_used += cost
        budget = self._add_budget(run.project_id, tokens=tokens, cost=cost)
        if advanced.status in {DAG_FAILED, DAG_BLOCKED}:
            run.consecutive_failures += 1
        elif advanced.status == DAG_WAITING_HUMAN:
            run.consecutive_failures = 0
        if budget.tokens_used >= config.daily_token_budget:
            self._pause_run(
                run,
                actor=Actor(actor_type=SYSTEM, actor_id="batch-scheduler"),
                reason=ALERT_BUDGET_EXCEEDED,
                alert_kind=ALERT_BUDGET_EXCEEDED,
                tokens_used=budget.tokens_used,
            )
            return advanced.id
        if run.consecutive_failures >= config.failure_threshold:
            self._pause_run(
                run,
                actor=Actor(actor_type=SYSTEM, actor_id="batch-scheduler"),
                reason=ALERT_CONSECUTIVE_FAILURES,
                alert_kind=ALERT_CONSECUTIVE_FAILURES,
                consecutive_failures=run.consecutive_failures,
            )
            return advanced.id
        run.updated_at = _utc_now_z()
        self._repo.save_run(run)
        return advanced.id

    def _pause_run(
        self,
        run: ScheduleRun,
        *,
        actor: Actor,
        reason: str,
        alert_kind: str | None,
        tokens_used: int = 0,
        consecutive_failures: int = 0,
    ) -> ScheduleRun:
        if run.status == STATUS_CANCELLED:
            return run
        before = run.to_audit_dict()
        run.status = STATUS_PAUSED
        run.paused_reason = reason
        run.updated_at = _utc_now_z()
        self._repo.save_run(run)
        if alert_kind is not None:
            alert = ScheduleAlert(
                id=str(uuid4()),
                project_id=run.project_id,
                run_id=run.id,
                kind=alert_kind,
                status=ALERT_OPEN,
                message=_alert_message(alert_kind),
                created_at=_utc_now_z(),
                created_by=actor.actor_id or "batch-scheduler",
                actor_type=actor.actor_type or SYSTEM,
                tokens_used=tokens_used or run.tokens_used,
                consecutive_failures=consecutive_failures or run.consecutive_failures,
            )
            self._repo.add_alert(alert)
            self._write_audit(
                actor=actor,
                action="schedule.alert",
                resource_type="schedule_alert",
                resource_id=alert.id,
                before_json=None,
                after_json=alert.to_audit_dict(),
            )
        self._write_audit(
            actor=actor,
            action="schedule.pause",
            resource_type="schedule_run",
            resource_id=run.id,
            before_json=before,
            after_json=run.to_audit_dict(),
        )
        return run

    def _completed_scene_ids(self, run: ScheduleRun) -> set[str]:
        done: set[str] = set()
        for dag_id in run.dag_ids:
            try:
                dag = self._svc.dags.get_dag(run.project_id, dag_id)
            except DagServiceError:
                continue
            if dag.status in {DAG_WAITING_HUMAN, "succeeded"}:
                done.add(dag.scene_id)
        return done

    def _in_flight_slots(self, run: ScheduleRun) -> list[ActiveSlot]:
        slots: list[ActiveSlot] = []
        for dag_id in run.dag_ids:
            try:
                dag = self._svc.dags.get_dag(run.project_id, dag_id)
            except DagServiceError:
                continue
            slots.append(
                ActiveSlot(
                    project_id=run.project_id,
                    scene_id=dag.scene_id,
                    snapshot_id=dag.snapshot_id,
                    task_kind=KIND_PROSE_WRITE,
                    dag_id=dag.id,
                )
            )
        return slots

    def _candidate_scenes(self, project_id: str, chapter_id: str | None) -> list[Scene]:
        try:
            scenes = self._scenes.list_scenes(project_id)
        except SceneServiceError as exc:
            raise ScheduleServiceError(exc.status_code, exc.detail) from exc
        cleaned = _clean_optional(chapter_id)
        if cleaned is not None:
            scenes = [item for item in scenes if item.chapter_id == cleaned]
        return scenes

    def _budget_for(self, project_id: str) -> BudgetCounter:
        day = _utc_day()
        existing = self._repo.get_budget(project_id, day)
        if existing is not None:
            return existing
        counter = BudgetCounter(
            project_id=project_id,
            day=day,
            tokens_used=0,
            cost_used=0.0,
            updated_at=_utc_now_z(),
        )
        self._repo.save_budget(counter)
        return counter

    def _add_budget(
        self, project_id: str, *, tokens: int, cost: float
    ) -> BudgetCounter:
        counter = self._budget_for(project_id)
        counter.tokens_used += tokens
        counter.cost_used += cost
        counter.updated_at = _utc_now_z()
        self._repo.save_budget(counter)
        return counter

    def _assert_worker_dispatch_allowed(self) -> None:
        for job_type in JOB_TYPES:
            try:
                self._guard.assert_job_dispatch_allowed(job_type)
            except PermissionDenied as exc:
                raise ScheduleServiceError(exc.status_code, exc.detail) from exc

    def _assert_not_canon_writer(self, actor: Actor) -> None:
        if actor.actor_type == HUMAN_EDITOR:
            return
        try:
            self._guard.assert_actor_may_submit_canon(actor)
        except PermissionDenied:
            return
        raise ScheduleServiceError(
            403,
            {
                "error": "scheduler_cannot_write_canon",
                "message": "Non-human actors cannot submit Canon via the scheduler.",
                "actor_type": actor.actor_type,
            },
        )

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise ScheduleServiceError(404, {"error": "project_not_found"})

    def _require_human(self, actor: Actor, *, action: str) -> Actor:
        try:
            return require_human_editor(actor, action=action, resource="schedule")
        except ActorError as exc:
            raise ScheduleServiceError(
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
            actor_type=actor.actor_type or SYSTEM,
            actor_id=actor.actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            correlation_id=get_request_id(),
        )


def inspect_task_kind(raw: str | None) -> str:
    cleaned = (raw or KIND_PROSE_WRITE).strip().lower()
    aliases = {
        "planning": KIND_PLANNING,
        "plan": KIND_PLANNING,
        "read": KIND_READ_CHECK,
        "read_check": KIND_READ_CHECK,
        "validate": KIND_READ_CHECK,
        "prose": KIND_PROSE_WRITE,
        "prose_write": KIND_PROSE_WRITE,
        "draft": KIND_PROSE_WRITE,
        "canon": KIND_CANON_WRITE,
        "canon_write": KIND_CANON_WRITE,
        "canon_commit": KIND_CANON_WRITE,
    }
    return aliases.get(cleaned, KIND_PROSE_WRITE)


def _require_start_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or GENERATION_AGENT
    if actor_type == REVIEW_AGENT or actor_type not in ALLOWED_START_ACTORS:
        raise ScheduleServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "A batch schedule may be started by the human 主编, "
                    "a generation agent, or the system. This is not Canon approval."
                ),
                "actor_type": actor_type,
            },
        )
    return Actor(actor_type=actor_type, actor_id=actor.actor_id)


def _require_tick_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or SYSTEM
    if actor_type not in ALLOWED_TICK_ACTORS:
        raise ScheduleServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": "tick processes running projects. It does not approve Canon.",
                "actor_type": actor_type,
            },
        )
    return Actor(actor_type=actor_type, actor_id=actor.actor_id)


def _require_configure_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or HUMAN_EDITOR
    if actor_type == REVIEW_AGENT:
        raise ScheduleServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": "Review agents cannot change schedule limits.",
                "actor_type": actor_type,
            },
        )
    if actor_type not in {HUMAN_EDITOR, SYSTEM, GENERATION_AGENT}:
        raise ScheduleServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": "Only the human 主编, system, or a generation agent may configure limits.",
                "actor_type": actor_type,
            },
        )
    return Actor(actor_type=actor_type, actor_id=actor.actor_id)


def _require_snapshot(snapshot_id: str) -> str:
    cleaned = (snapshot_id or "").strip()
    if not cleaned:
        raise ScheduleServiceError(
            422,
            {
                "error": "snapshot_id_required",
                "message": "A frozen Canon Snapshot id is required.",
            },
        )
    return cleaned


def _require_positive_int(value: int, field: str) -> int:
    if value < 1:
        raise ScheduleServiceError(
            422,
            {
                "error": f"invalid_{field}",
                "message": f"{field} must be at least 1.",
            },
        )
    return value


def _require_nonneg_int(value: int, field: str) -> int:
    if value < 0:
        raise ScheduleServiceError(
            422,
            {
                "error": f"invalid_{field}",
                "message": f"{field} must be >= 0.",
            },
        )
    return value


def _require_nonneg_float(value: float, field: str) -> float:
    if value < 0:
        raise ScheduleServiceError(
            422,
            {
                "error": f"invalid_{field}",
                "message": f"{field} must be >= 0.",
            },
        )
    return float(value)


def _alert_message(kind: str) -> str:
    if kind == ALERT_BUDGET_EXCEEDED:
        return (
            "Daily token budget exceeded. The project is paused. "
            "A human 主编 must resume. No auto-approve. No Canon write."
        )
    return (
        "Consecutive failures hit the threshold. The project is paused. "
        "A human 主编 must resume. No auto-approve. No Canon write."
    )


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"


def _utc_day() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")
