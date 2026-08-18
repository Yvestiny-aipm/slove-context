"""Single-scene DAG orchestrator (node 8.3).

Controls state, inputs, permissions, and the human-approval gate.
Automatic nodes dispatch through the 8.1 Worker and 8.2 PermissionGuard.
canon_commit calls existing 4.2 submit only after a human 主编 approve.
A blocker stops later automatic submit. No 8.4 batch. No real model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.agents.permissions import PermissionDenied, PermissionGuard
from slove_context.audit import AuditWriter
from slove_context.candidate_change.models import (
    CANDIDATE_APPROVED,
    CANDIDATE_AWAITING_VERDICT,
    CANDIDATE_EXTRACTED,
)
from slove_context.candidate_change.service import CandidateChangeServiceError
from slove_context.context_pack.models import PACK_ASSEMBLED, PACK_FROZEN
from slove_context.dags.deps import DagServices
from slove_context.dags.graph import (
    KIND_WORKER,
    NODE_CANDIDATE_EXTRACTION,
    NODE_CANON_COMMIT,
    NODE_CONTEXT_PACK,
    NODE_DOWNSTREAM_UNBLOCK,
    NODE_DRAFT_VALIDATION,
    NODE_HUMAN_REVIEW,
    NODE_IDS,
    NODE_PLAN_VALIDATION,
    NODE_SCENE_DRAFT,
    NODE_SCENE_PLAN,
    NODE_SUMMARY,
    ancestors_of,
    descendants_of,
    normalize_node_id,
    spec_for,
)
from slove_context.dags.models import (
    DAG_BLOCKED,
    DAG_CANCELLED,
    DAG_CREATED,
    DAG_FAILED,
    DAG_RUNNING,
    DAG_SUCCEEDED,
    DAG_WAITING_HUMAN,
    DECISION_APPROVE,
    DECISION_REJECT,
    HUMAN_DECISIONS,
    STATUS_BLOCKED,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_READY,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    STATUS_WAITING_HUMAN,
    DagNode,
    SceneDag,
)
from slove_context.dags.repository import DagRepository
from slove_context.jobs.models import (
    STATUS_DEAD_LETTER,
)
from slove_context.jobs.models import (
    STATUS_FAILED as JOB_FAILED,
)
from slove_context.jobs.models import (
    STATUS_SUCCEEDED as JOB_SUCCEEDED,
)
from slove_context.jobs.service import JobServiceError
from slove_context.logging import get_request_id
from slove_context.review_queue.models import (
    SUBJECT_CANDIDATE_CHANGE,
    SUBJECT_VALIDATION_REPORT,
)
from slove_context.review_queue.service import ReviewQueueServiceError
from slove_context.scene.service import SceneServiceError
from slove_context.scene_plan.service import ScenePlanServiceError
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
from slove_context.validation.models import RUN_RULE_FAILED

ALLOWED_CREATE_ACTORS = frozenset({HUMAN_EDITOR, GENERATION_AGENT, SYSTEM})
ALLOWED_ADVANCE_ACTORS = frozenset({HUMAN_EDITOR, GENERATION_AGENT, SYSTEM})
WORKER_TERMINAL = frozenset({JOB_SUCCEEDED, JOB_FAILED, STATUS_DEAD_LETTER})


class DagServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class DagService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        dag_repository: DagRepository,
        audit_writer: AuditWriter,
        services: DagServices,
    ) -> None:
        self._story = story_repository
        self._repo = dag_repository
        self._audit = audit_writer
        self._svc = services
        self._guard = PermissionGuard()

    def create_dag(
        self,
        *,
        project_id: str,
        scene_id: str,
        snapshot_id: str,
        actor: Actor,
        rebuild_context_pack: bool = False,
        start_from: str | None = None,
    ) -> SceneDag:
        self._require_project(project_id)
        trigger = _require_create_actor(actor)
        try:
            scene = self._svc.scenes.get_scene(project_id, scene_id)
        except SceneServiceError as exc:
            raise DagServiceError(exc.status_code, exc.detail) from exc
        if not snapshot_id or not snapshot_id.strip():
            raise DagServiceError(
                422,
                {
                    "error": "snapshot_id_required",
                    "message": "A frozen Canon Snapshot id is required.",
                },
            )
        start = None
        if start_from is not None:
            start = normalize_node_id(start_from)
            if start is None:
                raise DagServiceError(
                    422,
                    {
                        "error": "invalid_start_from",
                        "message": "start_from must be a fixed DAG node id.",
                        "allowed": list(NODE_IDS),
                    },
                )
        now = _utc_now_z()
        dag = SceneDag(
            id=str(uuid4()),
            project_id=project_id,
            scene_id=scene.id,
            snapshot_id=snapshot_id.strip(),
            status=DAG_CREATED,
            created_at=now,
            updated_at=now,
            created_by=trigger.actor_id or "orchestrator",
            actor_type=trigger.actor_type,
            correlation_id=get_request_id() or str(uuid4()),
            rebuild_context_pack=bool(rebuild_context_pack),
            start_from=start,
        )
        for node_id in NODE_IDS:
            dag.nodes[node_id] = DagNode(
                id=str(uuid4()),
                dag_id=dag.id,
                node_id=node_id,
                status=STATUS_PENDING,
                created_at=now,
                updated_at=now,
            )
        if start is not None:
            self._reuse_ancestors(dag, start, rebuild_context_pack=rebuild_context_pack)
        self._repo.add_dag(dag)
        self._write_audit(
            actor=trigger,
            action="scene_dag.create",
            resource_type="scene_dag",
            resource_id=dag.id,
            before_json=None,
            after_json=dag.to_audit_dict(),
        )
        return dag

    def get_dag(self, project_id: str, dag_id: str) -> SceneDag:
        self._require_project(project_id)
        dag = self._repo.get_dag(dag_id)
        if dag is None or dag.project_id != project_id:
            raise DagServiceError(404, {"error": "dag_not_found"})
        return dag

    def graph(self, project_id: str, dag_id: str) -> dict[str, Any]:
        return self.get_dag(project_id, dag_id).graph_dict()

    def advance(self, project_id: str, dag_id: str, *, actor: Actor) -> SceneDag:
        trigger = _require_advance_actor(actor)
        dag = self.get_dag(project_id, dag_id)
        if dag.status == DAG_CANCELLED:
            raise DagServiceError(
                409,
                {
                    "error": "dag_cancelled",
                    "message": "A cancelled DAG is kept and is not advanced.",
                    "kept": True,
                },
            )
        if dag.blocked and dag.status == DAG_BLOCKED:
            return dag
        before = dag.to_audit_dict()
        progressed = True
        steps = 0
        while progressed and steps < 24:
            steps += 1
            progressed = False
            if dag.blocked:
                break
            ready = self._ready_nodes(dag)
            if not ready:
                break
            for node in ready:
                if dag.blocked:
                    break
                if node.node_id == NODE_HUMAN_REVIEW:
                    self._enter_human_review(dag, node)
                    progressed = True
                    continue
                if node.node_id == NODE_CANON_COMMIT:
                    if dag.human_decision != DECISION_APPROVE:
                        continue
                    self._run_canon_commit(dag, node)
                    progressed = True
                    continue
                self._run_automatic(dag, node, actor=trigger)
                progressed = True
        self._refresh_dag_status(dag)
        dag.updated_at = _utc_now_z()
        self._repo.save_dag(dag)
        self._write_audit(
            actor=trigger,
            action="scene_dag.advance",
            resource_type="scene_dag",
            resource_id=dag.id,
            before_json=before,
            after_json=dag.to_audit_dict(),
        )
        return dag

    def human_review(
        self,
        project_id: str,
        dag_id: str,
        *,
        actor: Actor,
        decision: str,
        reason_code: str,
    ) -> SceneDag:
        try:
            editor = require_human_editor(
                actor, action="human_review", resource="scene_dag"
            )
            self._guard.assert_actor_may_approve_canon(editor)
        except ActorError as exc:
            raise DagServiceError(
                403,
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                    "actor_type": actor.actor_type or None,
                },
            ) from exc
        except PermissionDenied as exc:
            raise DagServiceError(exc.status_code, exc.detail) from exc
        dag = self.get_dag(project_id, dag_id)
        if dag.blocked:
            raise DagServiceError(
                409,
                {
                    "error": "dag_blocked",
                    "message": (
                        "A blocker already stopped later automatic submit, "
                        "including canon_commit."
                    ),
                    "blocker_node_id": dag.blocker_node_id,
                    "blocker_reason": dag.blocker_reason,
                },
            )
        node = dag.node(NODE_HUMAN_REVIEW)
        if node.status not in {STATUS_WAITING_HUMAN, STATUS_READY, STATUS_PENDING}:
            raise DagServiceError(
                409,
                {
                    "error": "human_review_not_open",
                    "message": "human_review is not waiting for a 主编 decision.",
                    "status": node.status,
                },
            )
        if node.status != STATUS_WAITING_HUMAN:
            raise DagServiceError(
                409,
                {
                    "error": "human_review_not_ready",
                    "message": (
                        "Advance the DAG until extract and draft_validation "
                        "finish. Without a human 主编, canon_commit must not run."
                    ),
                    "status": node.status,
                },
            )
        cleaned = (decision or "").strip().lower()
        if cleaned not in HUMAN_DECISIONS:
            raise DagServiceError(
                422,
                {
                    "error": "invalid_human_decision",
                    "message": "decision must be approve or reject.",
                    "allowed": sorted(HUMAN_DECISIONS),
                },
            )
        reason = (reason_code or "").strip()
        if not reason:
            raise DagServiceError(
                422,
                {
                    "error": "reason_code_required",
                    "message": "Each human_review step needs a reason_code.",
                },
            )
        before = dag.to_audit_dict()
        self._mark_running(node)
        candidate_ids = list(dag.frozen_outputs.get("candidate_ids") or [])
        try:
            for candidate_id in candidate_ids:
                if cleaned == DECISION_APPROVE:
                    self._svc.approval.approve(
                        project_id=dag.project_id,
                        candidate_id=str(candidate_id),
                        actor=editor,
                        body={
                            "decision": "Approve",
                            "created_by": editor.actor_id or "主编",
                            "reason": reason,
                        },
                    )
                else:
                    self._svc.approval.reject(
                        project_id=dag.project_id,
                        candidate_id=str(candidate_id),
                        actor=editor,
                        body={
                            "decision": "Reject",
                            "created_by": editor.actor_id or "主编",
                            "reason": reason,
                        },
                    )
        except CandidateChangeServiceError as exc:
            self._fail_node(
                dag, node, error_code="human_review_failed", detail=exc.detail
            )
            raise DagServiceError(exc.status_code, exc.detail) from exc
        dag.human_decision = cleaned
        dag.human_reason_code = reason
        dag.human_actor_type = editor.actor_type
        dag.human_actor_id = editor.actor_id
        node.outputs = {
            "human_decision": cleaned,
            "reason_code": reason,
            "candidate_ids": candidate_ids,
        }
        dag.frozen_outputs["human_decision"] = cleaned
        self._finish_node(node, STATUS_SUCCEEDED)
        if cleaned == DECISION_REJECT:
            self._set_blocker(
                dag,
                node.node_id,
                "human_reject",
                "Human 主编 rejected. canon_commit must not run.",
            )
            self._block_later(dag, NODE_CANON_COMMIT)
        self._refresh_dag_status(dag)
        dag.updated_at = _utc_now_z()
        self._repo.save_dag(dag)
        self._write_audit(
            actor=editor,
            action="scene_dag.human_review",
            resource_type="scene_dag",
            resource_id=dag.id,
            before_json=before,
            after_json=dag.to_audit_dict(),
        )
        return dag

    def rerun(
        self,
        project_id: str,
        dag_id: str,
        *,
        actor: Actor,
        from_node: str,
        rebuild_context_pack: bool = False,
    ) -> SceneDag:
        editor = self._require_human(actor, action="rerun")
        dag = self.get_dag(project_id, dag_id)
        if dag.status == DAG_CANCELLED:
            raise DagServiceError(
                409,
                {
                    "error": "dag_cancelled",
                    "message": "A cancelled DAG is kept and is not rerun.",
                    "kept": True,
                },
            )
        start = normalize_node_id(from_node)
        if start is None:
            raise DagServiceError(
                422,
                {
                    "error": "invalid_from_node",
                    "message": "from_node must be a fixed DAG node id.",
                    "allowed": list(NODE_IDS),
                },
            )
        before = dag.to_audit_dict()
        reset_ids = set(descendants_of(start))
        if rebuild_context_pack:
            reset_ids.update(descendants_of(NODE_CONTEXT_PACK))
        now = _utc_now_z()
        for node_id in reset_ids:
            node = dag.node(node_id)
            node.status = STATUS_PENDING
            node.job_id = None
            node.started_at = None
            node.finished_at = None
            node.duration_ms = None
            node.error_code = None
            node.error_detail = None
            node.outputs = {}
            node.reused_upstream = False
            node.updated_at = now
        for key in list(dag.frozen_outputs.keys()):
            if _output_owned_by(key, reset_ids):
                dag.frozen_outputs.pop(key, None)
        if NODE_HUMAN_REVIEW in reset_ids:
            dag.human_decision = None
            dag.human_reason_code = None
            dag.human_actor_type = None
            dag.human_actor_id = None
        if dag.blocker_node_id in reset_ids or dag.blocker_node_id is None:
            dag.blocked = False
            dag.blocker_node_id = None
            dag.blocker_reason = None
        dag.rebuild_context_pack = bool(rebuild_context_pack)
        dag.start_from = start
        dag.status = DAG_RUNNING
        dag.updated_at = now
        self._repo.save_dag(dag)
        self._write_audit(
            actor=editor,
            action="scene_dag.rerun",
            resource_type="scene_dag",
            resource_id=dag.id,
            before_json=before,
            after_json=dag.to_audit_dict(),
        )
        return dag

    def cancel(self, project_id: str, dag_id: str, *, actor: Actor) -> SceneDag:
        editor = self._require_human(actor, action="cancel")
        dag = self.get_dag(project_id, dag_id)
        if dag.status == DAG_CANCELLED:
            return dag
        before = dag.to_audit_dict()
        now = _utc_now_z()
        for node in dag.ordered_nodes():
            if node.status in {
                STATUS_PENDING,
                STATUS_READY,
                STATUS_RUNNING,
                STATUS_WAITING_HUMAN,
            }:
                node.status = STATUS_CANCELLED
                node.finished_at = now
                node.updated_at = now
                node.error_code = "cancelled"
        dag.status = DAG_CANCELLED
        dag.updated_at = now
        self._repo.save_dag(dag)
        self._write_audit(
            actor=editor,
            action="scene_dag.cancel",
            resource_type="scene_dag",
            resource_id=dag.id,
            before_json=before,
            after_json=dag.to_audit_dict(),
        )
        return dag

    def _ready_nodes(self, dag: SceneDag) -> list[DagNode]:
        ready: list[DagNode] = []
        for node in dag.ordered_nodes():
            if node.status not in {STATUS_PENDING, STATUS_READY}:
                continue
            if not self._deps_satisfied(dag, node.node_id):
                continue
            if node.node_id == NODE_DRAFT_VALIDATION and not self._extract_ready(dag):
                continue
            if node.node_id == NODE_CANON_COMMIT and (
                dag.human_decision != DECISION_APPROVE or dag.blocked
            ):
                continue
            if node.node_id == NODE_HUMAN_REVIEW and dag.blocked:
                continue
            node.status = STATUS_READY
            ready.append(node)
        return ready

    def _deps_satisfied(self, dag: SceneDag, node_id: str) -> bool:
        for dep in spec_for(node_id).dependencies:
            if dag.node(dep).status != STATUS_SUCCEEDED:
                return False
        return True

    def _extract_ready(self, dag: SceneDag) -> bool:
        extract = dag.node(NODE_CANDIDATE_EXTRACTION)
        if extract.status == STATUS_SUCCEEDED:
            return bool(dag.frozen_outputs.get("candidate_ids"))
        return False

    def _run_automatic(self, dag: SceneDag, node: DagNode, *, actor: Actor) -> None:
        spec = node.spec
        self._mark_running(node)
        try:
            if spec.kind == KIND_WORKER:
                self._run_worker_node(dag, node, actor=actor)
            elif node.node_id == NODE_PLAN_VALIDATION:
                self._run_plan_validation(dag, node)
            elif node.node_id == NODE_DOWNSTREAM_UNBLOCK:
                self._run_downstream_unblock(dag, node)
            else:
                raise DagServiceError(
                    500, {"error": "unknown_node_kind", "node_id": node.node_id}
                )
        except DagServiceError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc)}
            self._fail_node(
                dag,
                node,
                error_code=str(detail.get("error") or "node_failed"),
                detail=detail,
            )

    def _run_worker_node(self, dag: SceneDag, node: DagNode, *, actor: Actor) -> None:
        spec = node.spec
        assert spec.job_type is not None
        payload = self._payload_for(dag, node.node_id)
        try:
            job = self._svc.jobs.enqueue(
                project_id=dag.project_id,
                job_type=spec.job_type,
                actor=Actor(actor_type=SYSTEM, actor_id="dag-orchestrator"),
                payload=payload,
                scene_id=dag.scene_id,
                max_attempts=1,
                correlation_id=dag.correlation_id,
            )
        except JobServiceError as exc:
            raise DagServiceError(exc.status_code, exc.detail) from exc
        node.job_id = job.id
        finished = self._pump_job(dag.project_id, job.id)
        result = finished.result_reference or {}
        inner = str(result.get("inner_state") or "")
        if finished.status != JOB_SUCCEEDED:
            self._fail_node(
                dag,
                node,
                error_code=finished.error_code or "worker_job_failed",
                detail={
                    "error": finished.error_code or "worker_job_failed",
                    "message": finished.error_detail,
                    "job_id": finished.id,
                },
            )
            return
        if node.node_id == NODE_DRAFT_VALIDATION and inner == RUN_RULE_FAILED:
            self._record_validation_outputs(dag, node, result)
            self._set_blocker(
                dag,
                node.node_id,
                "validation_rule_failed",
                "draft_validation RuleFailed is a blocker. canon_commit must not run.",
            )
            self._block_later(dag, NODE_HUMAN_REVIEW)
            self._finish_node(node, STATUS_BLOCKED)
            return
        if inner in {"failed", "Failed", "ExecFailed"}:
            self._fail_node(
                dag,
                node,
                error_code="inner_job_failed",
                detail={"error": "inner_job_failed", "inner_state": inner},
            )
            return
        self._collect_worker_outputs(dag, node, result)
        if node.node_id == NODE_CONTEXT_PACK:
            self._freeze_pack(dag, actor=actor)
        self._finish_node(node, STATUS_SUCCEEDED)

    def _payload_for(self, dag: SceneDag, node_id: str) -> dict[str, Any]:
        frozen = dag.frozen_outputs
        if node_id == NODE_CONTEXT_PACK:
            return {
                "scene_id": dag.scene_id,
                "snapshot_id": dag.snapshot_id,
                "purpose": "Generate",
            }
        if node_id == NODE_SCENE_PLAN:
            return {"scene_id": dag.scene_id, "snapshot_id": dag.snapshot_id}
        if node_id == NODE_SCENE_DRAFT:
            return {
                "scene_id": dag.scene_id,
                "snapshot_id": dag.snapshot_id,
                "plan_id": frozen["plan_id"],
                "context_pack_id": frozen["context_pack_id"],
            }
        if node_id == NODE_CANDIDATE_EXTRACTION:
            return {
                "scene_id": dag.scene_id,
                "revision_id": frozen["draft_revision_id"],
            }
        if node_id == NODE_DRAFT_VALIDATION:
            return {
                "scene_id": dag.scene_id,
                "candidate_ids": list(frozen.get("candidate_ids") or []),
            }
        if node_id == NODE_SUMMARY:
            return {
                "scene_id": dag.scene_id,
                "draft_revision_id": frozen["draft_revision_id"],
                "content_hash": frozen.get("content_hash"),
            }
        raise DagServiceError(500, {"error": "no_payload", "node_id": node_id})

    def _collect_worker_outputs(
        self, dag: SceneDag, node: DagNode, result: dict[str, Any]
    ) -> None:
        if node.node_id == NODE_CONTEXT_PACK:
            pack_id = str(result.get("resource_id") or "")
            node.outputs = {"context_pack_id": pack_id}
            dag.frozen_outputs["context_pack_id"] = pack_id
            return
        if node.node_id == NODE_SCENE_PLAN:
            plan_id = str(result.get("plan_id") or "")
            node.outputs = {"plan_id": plan_id}
            dag.frozen_outputs["plan_id"] = plan_id
            return
        if node.node_id == NODE_SCENE_DRAFT:
            draft_id = str(result.get("draft_id") or "")
            draft = self._svc.existing.draft.get_draft(
                dag.project_id, dag.scene_id, draft_id
            )
            node.outputs = {
                "draft_revision_id": draft.id,
                "content_hash": draft.content_hash,
            }
            dag.frozen_outputs["draft_revision_id"] = draft.id
            dag.frozen_outputs["content_hash"] = draft.content_hash
            return
        if node.node_id == NODE_CANDIDATE_EXTRACTION:
            candidate_ids = [str(item) for item in (result.get("candidate_ids") or [])]
            if not candidate_ids:
                listed = self._svc.existing.extract.list_candidates(
                    dag.project_id, dag.scene_id
                )
                candidate_ids = [
                    item.id
                    for item in listed
                    if item.status == CANDIDATE_EXTRACTED
                    or item.status == CANDIDATE_AWAITING_VERDICT
                    or item.status == CANDIDATE_APPROVED
                ]
            node.outputs = {"candidate_ids": candidate_ids}
            dag.frozen_outputs["candidate_ids"] = candidate_ids
            return
        if node.node_id == NODE_DRAFT_VALIDATION:
            self._record_validation_outputs(dag, node, result)
            return
        if node.node_id == NODE_SUMMARY:
            summary_id = str(result.get("summary_id") or "")
            node.outputs = {"summary_id": summary_id}
            dag.frozen_outputs["summary_id"] = summary_id

    def _record_validation_outputs(
        self, dag: SceneDag, node: DagNode, result: dict[str, Any]
    ) -> None:
        run_id = str(result.get("resource_id") or "")
        report_id = str(result.get("report_id") or "")
        node.outputs = {
            "validation_run_id": run_id,
            "validation_report_id": report_id,
            "inner_state": result.get("inner_state"),
        }
        dag.frozen_outputs["validation_run_id"] = run_id
        dag.frozen_outputs["validation_report_id"] = report_id

    def _freeze_pack(self, dag: SceneDag, *, actor: Actor) -> None:
        pack_id = str(dag.frozen_outputs.get("context_pack_id") or "")
        if not pack_id:
            return
        pack = self._svc.context_pack.get_pack(dag.project_id, pack_id)
        if pack.status == PACK_FROZEN:
            return
        if pack.status != PACK_ASSEMBLED:
            raise DagServiceError(
                409,
                {
                    "error": "context_pack_not_assembled",
                    "status": pack.status,
                },
            )
        frozen = self._svc.context_pack.freeze(
            dag.project_id,
            pack.id,
            actor=Actor(actor_type=SYSTEM, actor_id="dag-orchestrator"),
        )
        dag.frozen_outputs["context_pack_id"] = frozen.id
        dag.node(NODE_CONTEXT_PACK).outputs["context_pack_id"] = frozen.id

    def _run_plan_validation(self, dag: SceneDag, node: DagNode) -> None:
        try:
            plan = self._svc.existing.plan.get_current_plan(
                dag.project_id, dag.scene_id
            )
        except ScenePlanServiceError as exc:
            raise DagServiceError(exc.status_code, exc.detail) from exc
        if plan.id != dag.frozen_outputs.get("plan_id") and dag.frozen_outputs.get(
            "plan_id"
        ):
            plan_id = str(dag.frozen_outputs["plan_id"])
        else:
            plan_id = plan.id
            dag.frozen_outputs["plan_id"] = plan.id
        node.outputs = {"plan_id": plan_id, "plan_valid": True}
        dag.frozen_outputs["plan_valid"] = True
        self._finish_node(node, STATUS_SUCCEEDED)

    def _enter_human_review(self, dag: SceneDag, node: DagNode) -> None:
        self._mark_running(node)
        item_ids: list[str] = []
        actor = Actor(actor_type=SYSTEM, actor_id="dag-orchestrator")
        try:
            for candidate_id in dag.frozen_outputs.get("candidate_ids") or []:
                item = self._svc.review_queue.enqueue(
                    project_id=dag.project_id,
                    actor=actor,
                    body={
                        "subject_type": SUBJECT_CANDIDATE_CHANGE,
                        "subject_id": str(candidate_id),
                    },
                )
                item_ids.append(item.id)
            report_id = dag.frozen_outputs.get("validation_report_id")
            if report_id:
                item = self._svc.review_queue.enqueue(
                    project_id=dag.project_id,
                    actor=actor,
                    body={
                        "subject_type": SUBJECT_VALIDATION_REPORT,
                        "subject_id": str(report_id),
                    },
                )
                item_ids.append(item.id)
        except ReviewQueueServiceError as exc:
            raise DagServiceError(exc.status_code, exc.detail) from exc
        node.outputs = {"review_queue_item_ids": item_ids}
        dag.frozen_outputs["review_queue_item_ids"] = item_ids
        node.status = STATUS_WAITING_HUMAN
        node.updated_at = _utc_now_z()
        dag.status = DAG_WAITING_HUMAN

    def _run_canon_commit(self, dag: SceneDag, node: DagNode) -> None:
        if dag.blocked:
            self._finish_node(node, STATUS_BLOCKED)
            return
        if dag.human_decision != DECISION_APPROVE:
            raise DagServiceError(
                409,
                {
                    "error": "human_approval_required",
                    "message": (
                        "canon_commit happens only after human approval. "
                        "Without a human 主编, canon_commit must not run."
                    ),
                    "human_decision": dag.human_decision,
                },
            )
        editor = Actor(
            actor_type=dag.human_actor_type or HUMAN_EDITOR,
            actor_id=dag.human_actor_id or "主编",
        )
        try:
            self._guard.assert_actor_may_submit_canon(editor)
        except PermissionDenied as exc:
            raise DagServiceError(exc.status_code, exc.detail) from exc
        self._mark_running(node)
        fact_ids: list[str] = []
        try:
            for candidate_id in dag.frozen_outputs.get("candidate_ids") or []:
                result = self._svc.approval.submit(
                    project_id=dag.project_id,
                    candidate_id=str(candidate_id),
                    actor=editor,
                    body={
                        "entity_type": "物品",
                        "created_by": editor.actor_id or "主编",
                    },
                )
                fact = result.get("canon_fact")
                if fact is not None:
                    fact_ids.append(str(getattr(fact, "id", fact)))
        except CandidateChangeServiceError as exc:
            raise DagServiceError(exc.status_code, exc.detail) from exc
        node.outputs = {"submitted_canon_fact_ids": fact_ids}
        dag.frozen_outputs["submitted_canon_fact_ids"] = fact_ids
        self._finish_node(node, STATUS_SUCCEEDED)

    def _run_downstream_unblock(self, dag: SceneDag, node: DagNode) -> None:
        scenes = self._svc.scenes.list_scenes(dag.project_id)
        unblocked = [
            item.id
            for item in scenes
            if dag.scene_id in item.depends_on and self._svc.scenes.is_generatable(item)
        ]
        generatable = [
            item.id for item in self._svc.scenes.list_generatable(dag.project_id)
        ]
        node.outputs = {
            "unblocked_scene_ids": unblocked,
            "generatable_scene_ids": generatable,
        }
        dag.frozen_outputs["unblocked_scene_ids"] = unblocked
        self._finish_node(node, STATUS_SUCCEEDED)

    def _reuse_ancestors(
        self, dag: SceneDag, start: str, *, rebuild_context_pack: bool
    ) -> None:
        for node_id in ancestors_of(start):
            if node_id == NODE_CONTEXT_PACK and rebuild_context_pack:
                continue
            node = dag.node(node_id)
            reused = self._try_reuse(dag, node_id)
            if reused:
                node.status = STATUS_SUCCEEDED
                node.reused_upstream = True
                node.outputs = reused
                node.updated_at = dag.created_at
            else:
                raise DagServiceError(
                    409,
                    {
                        "error": "upstream_outputs_missing",
                        "message": (
                            "Rerun / start_from reuses already-frozen upstream "
                            "outputs by default. Missing "
                            f"{node_id}."
                        ),
                        "node_id": node_id,
                    },
                )

    def _try_reuse(self, dag: SceneDag, node_id: str) -> dict[str, Any] | None:
        if node_id == NODE_CONTEXT_PACK:
            packs = [
                pack
                for pack in self._svc.context_pack.list_packs(
                    dag.project_id, dag.scene_id
                )
                if pack.status == PACK_FROZEN
            ]
            if not packs:
                return None
            pack = packs[-1]
            dag.frozen_outputs["context_pack_id"] = pack.id
            return {"context_pack_id": pack.id}
        if node_id == NODE_SCENE_PLAN:
            try:
                plan = self._svc.existing.plan.get_current_plan(
                    dag.project_id, dag.scene_id
                )
            except ScenePlanServiceError:
                return None
            dag.frozen_outputs["plan_id"] = plan.id
            return {"plan_id": plan.id}
        if node_id == NODE_PLAN_VALIDATION:
            if dag.frozen_outputs.get("plan_id"):
                dag.frozen_outputs["plan_valid"] = True
                return {"plan_id": dag.frozen_outputs["plan_id"], "plan_valid": True}
            return None
        if node_id == NODE_SCENE_DRAFT:
            drafts = self._svc.existing.draft.list_drafts(dag.project_id, dag.scene_id)
            draft = drafts[0] if drafts else None
            if draft is None:
                return None
            dag.frozen_outputs["draft_revision_id"] = draft.id
            dag.frozen_outputs["content_hash"] = draft.content_hash
            return {
                "draft_revision_id": draft.id,
                "content_hash": draft.content_hash,
            }
        return None

    def _pump_job(self, project_id: str, job_id: str) -> Any:
        worker = self._svc.worker
        for _ in range(16):
            try:
                job = self._svc.jobs.get_job(project_id, job_id)
            except JobServiceError as exc:
                raise DagServiceError(exc.status_code, exc.detail) from exc
            if job.status in WORKER_TERMINAL:
                return job
            progressed = worker.run_once()
            if progressed is None:
                job = self._svc.jobs.get_job(project_id, job_id)
                if job.status in WORKER_TERMINAL:
                    return job
                raise DagServiceError(
                    409,
                    {
                        "error": "worker_idle",
                        "message": "Worker did not claim the DAG job.",
                        "job_id": job_id,
                    },
                )
        return self._svc.jobs.get_job(project_id, job_id)

    def _mark_running(self, node: DagNode) -> None:
        now = _utc_now_z()
        node.status = STATUS_RUNNING
        node.started_at = now
        node.updated_at = now

    def _finish_node(self, node: DagNode, status: str) -> None:
        now = _utc_now_z()
        node.status = status
        node.finished_at = now
        node.updated_at = now
        node.duration_ms = _duration_ms(node.started_at, node.finished_at)

    def _fail_node(
        self,
        dag: SceneDag,
        node: DagNode,
        *,
        error_code: str,
        detail: Any,
    ) -> None:
        node.error_code = error_code
        node.error_detail = _short_detail(detail)
        self._finish_node(node, STATUS_FAILED)
        self._set_blocker(
            dag, node.node_id, error_code, node.error_detail or error_code
        )
        self._block_later(dag, _first_successor(node.node_id))

    def _set_blocker(
        self, dag: SceneDag, node_id: str, reason: str, message: str
    ) -> None:
        dag.blocked = True
        dag.blocker_node_id = node_id
        dag.blocker_reason = message
        dag.status = DAG_BLOCKED

    def _block_later(self, dag: SceneDag, from_node: str | None) -> None:
        if from_node is None:
            return
        for node_id in descendants_of(from_node):
            node = dag.node(node_id)
            if node.status in {STATUS_PENDING, STATUS_READY}:
                node.status = STATUS_BLOCKED
                node.error_code = "blocked_by_upstream"
                node.updated_at = _utc_now_z()

    def _refresh_dag_status(self, dag: SceneDag) -> None:
        if dag.status == DAG_CANCELLED:
            return
        if dag.blocked:
            dag.status = DAG_BLOCKED
            return
        if all(item.status == STATUS_SUCCEEDED for item in dag.ordered_nodes()):
            dag.status = DAG_SUCCEEDED
            return
        if dag.node(NODE_HUMAN_REVIEW).status == STATUS_WAITING_HUMAN:
            dag.status = DAG_WAITING_HUMAN
            return
        if any(item.status == STATUS_FAILED for item in dag.ordered_nodes()):
            dag.status = DAG_FAILED
            return
        if any(
            item.status in {STATUS_RUNNING, STATUS_READY, STATUS_SUCCEEDED}
            for item in dag.ordered_nodes()
        ):
            dag.status = DAG_RUNNING

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise DagServiceError(404, {"error": "project_not_found"})

    def _require_human(self, actor: Actor, *, action: str) -> Actor:
        try:
            return require_human_editor(actor, action=action, resource="scene_dag")
        except ActorError as exc:
            raise DagServiceError(
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


def _require_create_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or GENERATION_AGENT
    if actor_type == REVIEW_AGENT or actor_type not in ALLOWED_CREATE_ACTORS:
        raise DagServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "A scene DAG may be created by the human 主编, a "
                    "generation agent, or the system. This is not Canon approval."
                ),
                "actor_type": actor_type,
            },
        )
    return Actor(actor_type=actor_type, actor_id=actor.actor_id)


def _require_advance_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or GENERATION_AGENT
    if actor_type not in ALLOWED_ADVANCE_ACTORS:
        raise DagServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "advance runs Worker nodes only. human_review and "
                    "canon_commit wait for a human 主编."
                ),
                "actor_type": actor_type,
            },
        )
    return Actor(actor_type=actor_type, actor_id=actor.actor_id)


def _output_owned_by(key: str, node_ids: set[str]) -> bool:
    owners = {
        "context_pack_id": NODE_CONTEXT_PACK,
        "plan_id": NODE_SCENE_PLAN,
        "plan_valid": NODE_PLAN_VALIDATION,
        "draft_revision_id": NODE_SCENE_DRAFT,
        "content_hash": NODE_SCENE_DRAFT,
        "candidate_ids": NODE_CANDIDATE_EXTRACTION,
        "validation_run_id": NODE_DRAFT_VALIDATION,
        "validation_report_id": NODE_DRAFT_VALIDATION,
        "review_queue_item_ids": NODE_HUMAN_REVIEW,
        "human_decision": NODE_HUMAN_REVIEW,
        "submitted_canon_fact_ids": NODE_CANON_COMMIT,
        "summary_id": NODE_SUMMARY,
        "unblocked_scene_ids": NODE_DOWNSTREAM_UNBLOCK,
    }
    owner = owners.get(key)
    return owner in node_ids if owner else False


def _first_successor(node_id: str) -> str | None:
    kids = [item for item in descendants_of(node_id) if item != node_id]
    return kids[0] if kids else None


def _short_detail(detail: Any) -> str:
    if isinstance(detail, dict):
        error = detail.get("error")
        message = detail.get("message")
        if isinstance(error, str) and isinstance(message, str):
            return f"{error}: {message}"[:500]
        if isinstance(error, str):
            return error[:500]
    return str(detail)[:500]


def _duration_ms(started: str | None, finished: str | None) -> int | None:
    if not started or not finished:
        return None
    start = datetime.fromisoformat(started)
    end = datetime.fromisoformat(finished)
    return max(int((end - start).total_seconds() * 1000), 0)


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
