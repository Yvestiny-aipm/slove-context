"""Scene Plan generation jobs (node 3.3).

Trigger requires an approved, generatable Scene Card and a specified
Canon Snapshot. Structured output is assembled and validated against
contracts/scene-plan.schema.json. Invalid output is never persisted as
a valid plan. At most one format-repair request.

Uses Fake Provider via LlmGateway only. Does not write Canon. Does not
generate Scene Draft. Human approval is not required to create a plan;
triggering is an explicit API (human editor, generation agent, or system).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.canon.models import CanonSnapshot
from slove_context.canon.repository import CanonRepository
from slove_context.llm.errors import LlmError
from slove_context.llm.gateway import LlmGateway
from slove_context.llm.types import GenerateRequest, GenerateResponse
from slove_context.logging import get_request_id
from slove_context.scene.models import Scene
from slove_context.scene.service import SceneService, SceneServiceError
from slove_context.scene_plan.models import (
    ATTEMPT_GENERATE,
    ATTEMPT_REPAIR,
    DEFAULT_REPAIR_TASK_TYPE,
    DEFAULT_SCHEMA_VERSION,
    DEFAULT_TASK_TYPE,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_REPAIR,
    JOB_RUNNING,
    JOB_SUCCEEDED,
    PLAN_DRAFTED,
    PROMPT_VERSION,
    ScenePlan,
    ScenePlanJob,
)
from slove_context.scene_plan.prompt import (
    build_repair_user_prompt,
    build_system_prompt,
    build_user_prompt,
    prompt_version,
)
from slove_context.scene_plan.repository import ScenePlanRepository
from slove_context.scene_plan.validate import ScenePlanSchemaError, validate_scene_plan
from slove_context.story.actors import (
    GENERATION_AGENT,
    HUMAN_EDITOR,
    REVIEW_AGENT,
    SYSTEM,
    Actor,
)
from slove_context.story.repository import StoryRepository

ALLOWED_TRIGGER_ACTORS = frozenset({HUMAN_EDITOR, GENERATION_AGENT, SYSTEM})
MAX_FORMAT_REPAIRS = 1


class ScenePlanServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class ScenePlanService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        canon_repository: CanonRepository,
        scene_service: SceneService,
        plan_repository: ScenePlanRepository,
        audit_writer: AuditWriter,
        llm_gateway: LlmGateway,
        task_type: str = DEFAULT_TASK_TYPE,
        repair_task_type: str = DEFAULT_REPAIR_TASK_TYPE,
    ) -> None:
        self._story = story_repository
        self._canon = canon_repository
        self._scenes = scene_service
        self._repo = plan_repository
        self._audit = audit_writer
        self._gateway = llm_gateway
        self._task_type = task_type
        self._repair_task_type = repair_task_type

    def trigger_job(
        self,
        *,
        project_id: str,
        scene_id: str,
        snapshot_id: str,
        actor: Actor,
    ) -> ScenePlanJob:
        self._require_project(project_id)
        trigger = _require_trigger_actor(actor)
        scene = self._require_generatable_scene(project_id, scene_id)
        snapshot = self._require_snapshot(project_id, snapshot_id)
        now = _utc_now_z()
        job = ScenePlanJob(
            id=str(uuid4()),
            project_id=project_id,
            scene_id=scene.id,
            scene_card_id=scene.scene_card_id,
            snapshot_id=snapshot.id,
            prompt_version=prompt_version(),
            state=JOB_QUEUED,
            created_at=now,
            updated_at=now,
            created_by=trigger.actor_id or scene.created_by,
            actor_type=trigger.actor_type,
        )
        self._repo.add_job(job)
        self._write_audit(
            actor=trigger,
            action="scene_plan_job.create",
            resource_type="scene_plan_job",
            resource_id=job.id,
            before_json=None,
            after_json=job.to_audit_dict(),
        )
        self._run_job(job, scene=scene, snapshot_fact_ids=list(snapshot.fact_ids))
        return job

    def get_job(self, project_id: str, job_id: str) -> ScenePlanJob:
        self._require_project(project_id)
        job = self._repo.get_job(job_id)
        if job is None or job.project_id != project_id:
            raise ScenePlanServiceError(404, {"error": "scene_plan_job_not_found"})
        return job

    def get_current_plan(self, project_id: str, scene_id: str) -> ScenePlan:
        self._require_project(project_id)
        scene = self._scenes.get_scene(project_id, scene_id)
        plan = self._repo.current_plan(project_id, scene.id)
        if plan is None:
            raise ScenePlanServiceError(404, {"error": "scene_plan_not_found"})
        return plan

    def _run_job(
        self,
        job: ScenePlanJob,
        *,
        scene: Scene,
        snapshot_fact_ids: list[str],
    ) -> None:
        self._transition(job, JOB_RUNNING, actor_type=SYSTEM)
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(
            scene=scene,
            snapshot_id=job.snapshot_id,
            snapshot_fact_ids=snapshot_fact_ids,
        )
        first = self._generate(
            job,
            attempt=ATTEMPT_GENERATE,
            task_type=self._task_type,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        assembled, errors = self._validate_response(first, scene=scene)
        if assembled is not None:
            self._succeed(job, plan_payload=assembled)
            return

        if job.repair_count >= MAX_FORMAT_REPAIRS:
            self._fail(job, reason="schema_validation_failed", errors=errors)
            return

        self._transition(job, JOB_REPAIR, actor_type=SYSTEM)
        job.repair_count += 1
        repair = self._generate(
            job,
            attempt=ATTEMPT_REPAIR,
            task_type=self._repair_task_type,
            system_prompt=system_prompt,
            user_prompt=build_repair_user_prompt(validation_errors=errors),
        )
        assembled, errors = self._validate_response(repair, scene=scene)
        if assembled is not None:
            self._succeed(job, plan_payload=assembled)
            return
        self._fail(job, reason="schema_validation_failed", errors=errors)

    def _generate(
        self,
        job: ScenePlanJob,
        *,
        attempt: str,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
    ) -> GenerateResponse | None:
        request = GenerateRequest(
            model="fake-model",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=512,
            correlation_id=get_request_id() or job.id,
            task_type=task_type,
            prompt_version=PROMPT_VERSION,
        )
        try:
            response = self._gateway.generate_structured(request)
        except LlmError as exc:
            job.request_refs.append(
                {
                    "attempt": attempt,
                    "request_id": get_request_id() or job.id,
                    "raw_response_reference": None,
                    "error_code": type(exc).__name__,
                }
            )
            self._persist_job(job)
            return None
        job.request_refs.append(
            {
                "attempt": attempt,
                "request_id": response.request_id,
                "raw_response_reference": response.raw_response_reference,
                "error_code": (
                    response.error.code if response.error is not None else None
                ),
            }
        )
        self._persist_job(job)
        return response

    def _validate_response(
        self, response: GenerateResponse | None, *, scene: Scene
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
        if response is None:
            errors = [
                {
                    "path": "",
                    "message": "provider_call_failed",
                }
            ]
            return None, errors
        if response.error is not None or not isinstance(response.parsed_output, dict):
            errors = [
                {
                    "path": "",
                    "message": (
                        response.error.code
                        if response.error is not None
                        else "structured_parse_failed"
                    ),
                }
            ]
            return None, errors
        assembled = _assemble_plan(
            response.parsed_output,
            project_id=scene.project_id,
            scene_id=scene.id,
            created_by=scene.created_by,
        )
        try:
            validate_scene_plan(assembled)
        except ScenePlanSchemaError as exc:
            return None, exc.errors
        return assembled, []

    def _succeed(self, job: ScenePlanJob, *, plan_payload: dict[str, Any]) -> None:
        def persist() -> None:
            plan = ScenePlan(
                id=str(plan_payload["id"]),
                project_id=job.project_id,
                scene_id=job.scene_id,
                scene_card_id=job.scene_card_id,
                snapshot_id=job.snapshot_id,
                job_id=job.id,
                prompt_version=job.prompt_version,
                status=str(plan_payload["status"]),
                payload=plan_payload,
                created_at=str(plan_payload["created_at"]),
                created_by=str(plan_payload["created_by"]),
            )
            self._repo.add_plan(plan)
            job.plan_id = plan.id
            job.validation_result = {"ok": True, "errors": [], "attempt": job.state}
            job.failure_reason = None
            job.evidence = None
            self._transition(job, JOB_SUCCEEDED, actor_type=SYSTEM)
            self._write_audit(
                actor=Actor(actor_type=SYSTEM, actor_id=None),
                action="scene_plan.create",
                resource_type="scene_plan",
                resource_id=plan.id,
                before_json=None,
                after_json=plan.to_audit_dict(),
            )

        self._gateway.invoke_once("persist_generation_state", persist)

    def _fail(
        self, job: ScenePlanJob, *, reason: str, errors: list[dict[str, str]]
    ) -> None:
        def persist() -> None:
            job.validation_result = {
                "ok": False,
                "errors": errors,
                "attempt": ATTEMPT_REPAIR if job.repair_count else ATTEMPT_GENERATE,
            }
            job.failure_reason = reason
            job.evidence = {
                "request_refs": [dict(item) for item in job.request_refs],
                "raw_response_references": [
                    item.get("raw_response_reference")
                    for item in job.request_refs
                    if item.get("raw_response_reference")
                ],
                "validation_errors": errors,
                "repair_attempted": job.repair_count > 0,
                "repair_count": job.repair_count,
            }
            self._transition(job, JOB_FAILED, actor_type=SYSTEM)

        self._gateway.invoke_once("persist_generation_state", persist)

    def _transition(
        self, job: ScenePlanJob, new_state: str, *, actor_type: str
    ) -> None:
        before = job.to_audit_dict()
        self._set_state(job, new_state)
        self._write_audit(
            actor=Actor(actor_type=actor_type, actor_id=None),
            action="scene_plan_job.transition",
            resource_type="scene_plan_job",
            resource_id=job.id,
            before_json=before,
            after_json=job.to_audit_dict(),
        )

    def _set_state(self, job: ScenePlanJob, new_state: str) -> None:
        previous = job.state
        now = _utc_now_z()
        job.transitions.append({"from": previous, "to": new_state, "at": now})
        job.state = new_state
        job.updated_at = now
        self._persist_job(job)

    def _persist_job(self, job: ScenePlanJob) -> None:
        self._repo.save_job(job)

    def _require_generatable_scene(self, project_id: str, scene_id: str) -> Scene:
        try:
            scene = self._scenes.get_scene(project_id, scene_id)
        except SceneServiceError as exc:
            raise ScenePlanServiceError(exc.status_code, exc.detail) from exc
        if not self._scenes.is_generatable(scene):
            unsatisfied = self._scenes.unsatisfied_dependencies(scene)
            raise ScenePlanServiceError(
                409,
                {
                    "error": "scene_not_generatable",
                    "message": (
                        "Scene Plan generation requires an approved (or published) "
                        "Scene Card whose dependencies are complete (node 3.1). "
                        "Rejecting this job. Scene Plan is not Canon and not "
                        "Scene Draft."
                    ),
                    "scene_id": scene.id,
                    "status": scene.status,
                    "unsatisfied_dependencies": unsatisfied,
                    "generatable": False,
                },
            )
        return scene

    def _require_snapshot(self, project_id: str, snapshot_id: str) -> CanonSnapshot:
        cleaned = snapshot_id.strip() if isinstance(snapshot_id, str) else ""
        if not cleaned:
            raise ScenePlanServiceError(
                422,
                {
                    "error": "snapshot_id_required",
                    "message": "A specified Canon Snapshot is required.",
                },
            )
        snapshot = self._canon.get_snapshot(cleaned)
        if snapshot is None or snapshot.project_id != project_id:
            raise ScenePlanServiceError(404, {"error": "canon_snapshot_not_found"})
        return snapshot

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise ScenePlanServiceError(404, {"error": "project_not_found"})

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


def _assemble_plan(
    raw: dict[str, Any],
    *,
    project_id: str,
    scene_id: str,
    created_by: str,
) -> dict[str, Any]:
    return {
        "schema_version": raw.get("schema_version") or DEFAULT_SCHEMA_VERSION,
        "id": str(uuid4()),
        "project_id": project_id,
        "created_at": _utc_now_z(),
        "created_by": created_by,
        "scene_id": scene_id,
        "status": PLAN_DRAFTED,
        "intent": raw.get("intent"),
        "beats": raw.get("beats"),
    }


def _require_trigger_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or GENERATION_AGENT
    if actor_type == REVIEW_AGENT:
        raise ScenePlanServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Review agents cannot trigger Scene Plan generation. "
                    "Use human_editor, generation_agent, or system."
                ),
                "actor_type": actor_type,
            },
        )
    if actor_type not in ALLOWED_TRIGGER_ACTORS:
        raise ScenePlanServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Scene Plan jobs may be triggered by the human 主编, "
                    "a generation agent, or the system. This is generate_*, "
                    "not Canon approval."
                ),
                "actor_type": actor_type,
            },
        )
    return Actor(actor_type=actor_type, actor_id=actor.actor_id)


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
