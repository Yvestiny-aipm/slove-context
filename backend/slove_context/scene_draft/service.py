"""Scene Draft generation jobs (node 3.4).

Trigger requires:
- an approved, generatable Scene Card
- a valid Scene Plan (schema-valid, belongs to the scene)
- a Canon Snapshot id
- a pre-frozen Context Pack reference (3.4 static fixture or a
  frozen pack from the 6.1 assembler)

Output is immutable Scene Draft prose (status Generated at most).
Retry or rewrite creates a new revision. Old rows are not overwritten.

Uses LlmGateway.generate_text. Default jobs stay Fake (3.4). Node UI.4
may pass a DeepSeek-backed gateway for one-scene prose. Does not write
Canon. Does not auto-approve or publish. Does not extract facts (4.1).
Provider generate_* do not persist drafts.

Idempotency rules (also in models.py and README):
1. Duplicate submit: the same idempotency_key on the same scene returns
   the existing job if that job is still queued, running, or succeeded.
2. Retry after success: omit the key or send a new key. That creates a
   new job and a new draft revision. The previous revision stays intact
   and is marked Superseded.
3. Cancel: human editor only. Terminal. The job row is kept. The same
   key is not reused after cancel (a later trigger creates a new job).
4. Generate failure: the failed job is kept (not deleted). A later
   trigger — same key or new key — creates a new job / revision attempt.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.canon.models import CanonSnapshot
from slove_context.canon.repository import CanonRepository
from slove_context.context_pack.models import PACK_FROZEN
from slove_context.context_pack.repository import ContextPackRepository
from slove_context.llm.errors import LlmError
from slove_context.llm.gateway import LlmGateway
from slove_context.llm.types import GenerateRequest, GenerateResponse
from slove_context.logging import get_request_id
from slove_context.scene.models import Scene
from slove_context.scene.service import SceneService, SceneServiceError
from slove_context.scene_draft.context_pack import get_static_context_pack
from slove_context.scene_draft.metrics import (
    character_count,
    content_hash,
    word_count_estimate,
)
from slove_context.scene_draft.models import (
    DEFAULT_TASK_TYPE,
    DRAFT_GENERATED,
    DRAFT_SUPERSEDED,
    JOB_CANCELLABLE_STATES,
    JOB_CANCELLED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_REUSABLE_STATES,
    JOB_RUNNING,
    JOB_SUCCEEDED,
    PROMPT_VERSION,
    SceneDraft,
    SceneDraftJob,
)
from slove_context.scene_draft.prompt import (
    build_system_prompt,
    build_user_prompt,
    prompt_version,
)
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.scene_plan.models import ScenePlan
from slove_context.scene_plan.repository import ScenePlanRepository
from slove_context.scene_plan.validate import ScenePlanSchemaError, validate_scene_plan
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

ALLOWED_TRIGGER_ACTORS = frozenset({HUMAN_EDITOR, GENERATION_AGENT, SYSTEM})


class SceneDraftServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class SceneDraftService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        canon_repository: CanonRepository,
        scene_service: SceneService,
        plan_repository: ScenePlanRepository,
        draft_repository: SceneDraftRepository,
        audit_writer: AuditWriter,
        llm_gateway: LlmGateway,
        task_type: str = DEFAULT_TASK_TYPE,
        auto_run: bool = True,
        context_pack_repository: ContextPackRepository | None = None,
        generation_model: str = "fake-model",
    ) -> None:
        self._story = story_repository
        self._canon = canon_repository
        self._scenes = scene_service
        self._plans = plan_repository
        self._repo = draft_repository
        self._audit = audit_writer
        self._gateway = llm_gateway
        self._task_type = task_type
        self._auto_run = auto_run
        self._context_packs = context_pack_repository
        self._generation_model = generation_model or "fake-model"

    def trigger_job(
        self,
        *,
        project_id: str,
        scene_id: str,
        snapshot_id: str,
        plan_id: str,
        context_pack_id: str,
        actor: Actor,
        idempotency_key: str | None = None,
    ) -> SceneDraftJob:
        self._require_project(project_id)
        trigger = _require_trigger_actor(actor)
        scene = self._require_generatable_scene(project_id, scene_id)
        snapshot = self._require_snapshot(project_id, snapshot_id)
        plan = self._require_valid_plan(project_id, scene.id, plan_id)
        pack = self._require_context_pack(context_pack_id)

        key = _clean_optional(idempotency_key)
        if key is not None:
            existing = self._repo.find_job_by_idempotency_key(project_id, scene.id, key)
            if existing is not None and existing.state in JOB_REUSABLE_STATES:
                return existing

        now = _utc_now_z()
        job = SceneDraftJob(
            id=str(uuid4()),
            project_id=project_id,
            scene_id=scene.id,
            scene_card_id=scene.scene_card_id,
            plan_id=plan.id,
            snapshot_id=snapshot.id,
            context_pack_id=str(pack["id"]),
            prompt_version=prompt_version(),
            state=JOB_QUEUED,
            created_at=now,
            updated_at=now,
            created_by=trigger.actor_id or scene.created_by,
            actor_type=trigger.actor_type,
            idempotency_key=key,
        )
        self._repo.add_job(job)
        self._write_audit(
            actor=trigger,
            action="scene_draft_job.create",
            resource_type="scene_draft_job",
            resource_id=job.id,
            before_json=None,
            after_json=job.to_audit_dict(),
        )
        if self._auto_run:
            self._run_job(job, scene=scene, plan=plan, context_pack=pack)
        return job

    def get_job(self, project_id: str, job_id: str) -> SceneDraftJob:
        self._require_project(project_id)
        job = self._repo.get_job(job_id)
        if job is None or job.project_id != project_id:
            raise SceneDraftServiceError(404, {"error": "scene_draft_job_not_found"})
        return job

    def cancel_job(
        self, project_id: str, job_id: str, *, actor: Actor
    ) -> SceneDraftJob:
        self._require_project(project_id)
        try:
            editor = require_human_editor(
                actor, action="cancel", resource="Scene Draft job"
            )
        except ActorError as exc:
            raise SceneDraftServiceError(
                403,
                {
                    "error": "actor_not_allowed",
                    "message": str(exc),
                },
            ) from exc
        job = self.get_job(project_id, job_id)
        if job.state not in JOB_CANCELLABLE_STATES:
            raise SceneDraftServiceError(
                409,
                {
                    "error": "job_not_cancellable",
                    "message": (
                        "Cancel is terminal and only applies to queued or running "
                        "jobs. Succeeded / failed / cancelled jobs are kept and "
                        "are not deleted."
                    ),
                    "state": job.state,
                },
            )
        self._transition(job, JOB_CANCELLED, actor_type=editor.actor_type)
        return job

    def list_drafts(self, project_id: str, scene_id: str) -> list[SceneDraft]:
        self._require_project(project_id)
        scene = self._require_scene(project_id, scene_id)
        return self._repo.list_drafts(project_id, scene.id)

    def get_draft(self, project_id: str, scene_id: str, revision_id: str) -> SceneDraft:
        self._require_project(project_id)
        scene = self._require_scene(project_id, scene_id)
        draft = self._repo.get_draft(revision_id)
        if (
            draft is None
            or draft.project_id != project_id
            or draft.scene_id != scene.id
        ):
            raise SceneDraftServiceError(404, {"error": "scene_draft_not_found"})
        return draft

    def _run_job(
        self,
        job: SceneDraftJob,
        *,
        scene: Scene,
        plan: ScenePlan,
        context_pack: dict[str, Any],
    ) -> None:
        self._transition(job, JOB_RUNNING, actor_type=SYSTEM)
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(
            scene=scene,
            plan=plan,
            snapshot_id=job.snapshot_id,
            context_pack_id=job.context_pack_id,
            context_pack=context_pack,
        )
        response = self._generate(
            job,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        body, reason = _prose_from_response(response)
        if body is None:
            self._fail(job, reason=reason or "generate_failed")
            return
        self._succeed(
            job, body=body, model=_model_from_response(response, self._generation_model)
        )

    def _generate(
        self,
        job: SceneDraftJob,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> GenerateResponse | None:
        request = GenerateRequest(
            model=self._generation_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.4,
            max_tokens=1024,
            correlation_id=get_request_id() or job.id,
            task_type=self._task_type,
            prompt_version=PROMPT_VERSION,
        )
        try:
            response = self._gateway.generate_text(request)
        except LlmError as exc:
            job.request_refs.append(
                {
                    "request_id": get_request_id() or job.id,
                    "raw_response_reference": None,
                    "error_code": type(exc).__name__,
                }
            )
            self._persist_job(job)
            return None
        job.request_refs.append(
            {
                "request_id": response.request_id,
                "raw_response_reference": response.raw_response_reference,
                "error_code": (
                    response.error.code if response.error is not None else None
                ),
                "usage": response.usage.to_dict(),
                "model": response.model,
            }
        )
        self._persist_job(job)
        return response

    def _succeed(self, job: SceneDraftJob, *, body: str, model: str) -> None:
        def persist() -> None:
            now = _utc_now_z()
            previous = self._repo.current_generated_draft(job.project_id, job.scene_id)
            revision = self._repo.next_revision(job.project_id, job.scene_id)
            draft = SceneDraft(
                id=str(uuid4()),
                project_id=job.project_id,
                scene_id=job.scene_id,
                job_id=job.id,
                revision=revision,
                status=DRAFT_GENERATED,
                body=body,
                content_hash=content_hash(body),
                character_count=character_count(body),
                word_count_estimate=word_count_estimate(body),
                generation_model=model,
                prompt_version=job.prompt_version,
                generated_at=now,
                scene_card_id=job.scene_card_id,
                plan_id=job.plan_id,
                snapshot_id=job.snapshot_id,
                context_pack_id=job.context_pack_id,
                created_at=now,
                created_by=job.created_by,
            )
            self._repo.add_draft(draft)
            if previous is not None:
                before = previous.to_audit_dict()
                previous.status = DRAFT_SUPERSEDED
                self._repo.save_draft(previous)
                self._write_audit(
                    actor=Actor(actor_type=SYSTEM, actor_id=None),
                    action="scene_draft.supersede",
                    resource_type="scene_draft",
                    resource_id=previous.id,
                    before_json=before,
                    after_json=previous.to_audit_dict(),
                )
            job.draft_id = draft.id
            job.draft_revision = draft.revision
            job.failure_reason = None
            job.evidence = None
            self._transition(job, JOB_SUCCEEDED, actor_type=SYSTEM)
            self._write_audit(
                actor=Actor(actor_type=SYSTEM, actor_id=None),
                action="scene_draft.create",
                resource_type="scene_draft",
                resource_id=draft.id,
                before_json=None,
                after_json=draft.to_audit_dict(),
            )

        self._gateway.invoke_once("persist_generation_state", persist)

    def _fail(self, job: SceneDraftJob, *, reason: str) -> None:
        def persist() -> None:
            job.failure_reason = reason
            job.evidence = {
                "request_refs": [dict(item) for item in job.request_refs],
                "raw_response_references": [
                    item.get("raw_response_reference")
                    for item in job.request_refs
                    if item.get("raw_response_reference")
                ],
                "failure_reason": reason,
            }
            self._transition(job, JOB_FAILED, actor_type=SYSTEM)

        self._gateway.invoke_once("persist_generation_state", persist)

    def _transition(
        self, job: SceneDraftJob, new_state: str, *, actor_type: str
    ) -> None:
        before = job.to_audit_dict()
        self._set_state(job, new_state)
        self._write_audit(
            actor=Actor(actor_type=actor_type, actor_id=None),
            action="scene_draft_job.transition",
            resource_type="scene_draft_job",
            resource_id=job.id,
            before_json=before,
            after_json=job.to_audit_dict(),
        )

    def _set_state(self, job: SceneDraftJob, new_state: str) -> None:
        previous = job.state
        now = _utc_now_z()
        job.transitions.append({"from": previous, "to": new_state, "at": now})
        job.state = new_state
        job.updated_at = now
        self._persist_job(job)

    def _persist_job(self, job: SceneDraftJob) -> None:
        self._repo.save_job(job)

    def _require_generatable_scene(self, project_id: str, scene_id: str) -> Scene:
        scene = self._require_scene(project_id, scene_id)
        if not self._scenes.is_generatable(scene):
            unsatisfied = self._scenes.unsatisfied_dependencies(scene)
            raise SceneDraftServiceError(
                409,
                {
                    "error": "scene_not_generatable",
                    "message": (
                        "Scene Draft generation requires an approved (or published) "
                        "Scene Card whose dependencies are complete. Rejecting this "
                        "job. Scene Draft is not Canon and is not auto-approved."
                    ),
                    "scene_id": scene.id,
                    "status": scene.status,
                    "unsatisfied_dependencies": unsatisfied,
                    "generatable": False,
                },
            )
        return scene

    def _require_scene(self, project_id: str, scene_id: str) -> Scene:
        try:
            return self._scenes.get_scene(project_id, scene_id)
        except SceneServiceError as exc:
            raise SceneDraftServiceError(exc.status_code, exc.detail) from exc

    def _require_valid_plan(
        self, project_id: str, scene_id: str, plan_id: str
    ) -> ScenePlan:
        cleaned = _clean_required(plan_id)
        if cleaned is None:
            raise SceneDraftServiceError(
                422,
                {
                    "error": "plan_id_required",
                    "message": "A valid Scene Plan id is required.",
                },
            )
        plan = self._plans.get_plan(cleaned)
        if plan is None or plan.project_id != project_id:
            raise SceneDraftServiceError(404, {"error": "scene_plan_not_found"})
        if plan.scene_id != scene_id:
            raise SceneDraftServiceError(
                409,
                {
                    "error": "scene_plan_scene_mismatch",
                    "message": "The Scene Plan does not belong to this scene.",
                    "plan_id": plan.id,
                    "scene_id": scene_id,
                },
            )
        try:
            validate_scene_plan(plan.payload)
        except ScenePlanSchemaError as exc:
            raise SceneDraftServiceError(
                409,
                {
                    "error": "scene_plan_invalid",
                    "message": "The Scene Plan failed schema validation.",
                    "errors": exc.errors,
                },
            ) from exc
        return plan

    def _require_snapshot(self, project_id: str, snapshot_id: str) -> CanonSnapshot:
        cleaned = _clean_required(snapshot_id)
        if cleaned is None:
            raise SceneDraftServiceError(
                422,
                {
                    "error": "snapshot_id_required",
                    "message": "A specified Canon Snapshot is required.",
                },
            )
        snapshot = self._canon.get_snapshot(cleaned)
        if snapshot is None or snapshot.project_id != project_id:
            raise SceneDraftServiceError(404, {"error": "canon_snapshot_not_found"})
        return snapshot

    def _require_context_pack(self, context_pack_id: str) -> dict[str, Any]:
        cleaned = _clean_required(context_pack_id)
        if cleaned is None:
            raise SceneDraftServiceError(
                422,
                {
                    "error": "context_pack_id_required",
                    "message": (
                        "A pre-frozen Context Pack reference is required. "
                        "Use the static fixture id or a frozen pack "
                        "from the node 6.1 assembler."
                    ),
                },
            )
        pack = get_static_context_pack(cleaned)
        if pack is not None:
            return pack
        if self._context_packs is not None:
            assembled = self._context_packs.get(cleaned)
            if assembled is not None and assembled.status == PACK_FROZEN:
                return dict(assembled.payload)
        raise SceneDraftServiceError(
            404,
            {
                "error": "context_pack_not_found",
                "message": (
                    "Unknown Context Pack id. Jobs must reference the "
                    "pre-frozen static fixture or a frozen assembler "
                    "pack. Unfrozen / failed / cancelled packs are "
                    "not accepted."
                ),
            },
        )

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise SceneDraftServiceError(404, {"error": "project_not_found"})

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


def _prose_from_response(
    response: GenerateResponse | None,
) -> tuple[str | None, str | None]:
    if response is None:
        return None, "provider_call_failed"
    if response.error is not None:
        return None, response.error.code
    text = response.parsed_output
    if not isinstance(text, str) or not text.strip():
        return None, "empty_prose"
    return text, None


def _model_from_response(
    response: GenerateResponse | None, fallback: str = "fake-model"
) -> str:
    if response is None or not response.model:
        return fallback
    return response.model


def _require_trigger_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or GENERATION_AGENT
    if actor_type == REVIEW_AGENT:
        raise SceneDraftServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Review agents cannot trigger Scene Draft generation. "
                    "Use human_editor, generation_agent, or system."
                ),
                "actor_type": actor_type,
            },
        )
    if actor_type not in ALLOWED_TRIGGER_ACTORS:
        raise SceneDraftServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Scene Draft jobs may be triggered by the human 主编, "
                    "a generation agent, or the system. This is generate_*, "
                    "not Canon approval."
                ),
                "actor_type": actor_type,
            },
        )
    return Actor(actor_type=actor_type, actor_id=actor.actor_id)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_required(value: str | None) -> str | None:
    return _clean_optional(value)


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
