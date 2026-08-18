"""Candidate Change extraction jobs (node 4.1).

Trigger requires one generated immutable Scene Draft (status Generated
or already Extracted), its Scene, and project. Structured output is
assembled and validated against contracts/candidate-change.schema.json.
Invalid items are never persisted as valid candidates. At most one
format-repair request.

Uses Fake Provider via LlmGateway.generate_structured only. Does not
write Canon. Does not auto-approve. Does not run Validate (4.2).
Does not overwrite draft prose. Success may move draft Generated →
Extracted (status only).

Idempotency rules (also in models.py):
1. Duplicate submit: the same idempotency_key on the same draft returns
   the existing job if that job is still queued, running, or succeeded.
2. Cancel: human editor only. Terminal. The job row is kept.
3. Extract failure: the failed job is kept (not deleted). A later
   trigger — same key or new key — creates a new job / extract batch.
4. Retry after success with a new key (or omit): new append-only batch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.candidate_change.models import (
    ATTEMPT_GENERATE,
    ATTEMPT_REPAIR,
    CANDIDATE_EXTRACTED,
    DEFAULT_REPAIR_TASK_TYPE,
    DEFAULT_SCHEMA_VERSION,
    DEFAULT_TASK_TYPE,
    JOB_CANCELLABLE_STATES,
    JOB_CANCELLED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_REPAIR,
    JOB_REUSABLE_STATES,
    JOB_RUNNING,
    JOB_SUCCEEDED,
    PROMPT_VERSION,
    CandidateChange,
    ExtractJob,
)
from slove_context.candidate_change.prompt import (
    build_repair_user_prompt,
    build_system_prompt,
    build_user_prompt,
    prompt_version,
)
from slove_context.candidate_change.repository import CandidateChangeRepository
from slove_context.candidate_change.validate import (
    CandidateChangeSchemaError,
    validate_candidate_change,
)
from slove_context.llm.errors import LlmError
from slove_context.llm.gateway import LlmGateway
from slove_context.llm.types import GenerateRequest, GenerateResponse
from slove_context.logging import get_request_id
from slove_context.scene.models import Scene
from slove_context.scene.service import SceneService, SceneServiceError
from slove_context.scene_draft.metrics import content_hash
from slove_context.scene_draft.models import (
    DRAFT_EXTRACTED,
    DRAFT_GENERATED,
    EXTRACTABLE_DRAFT_STATUSES,
    SceneDraft,
)
from slove_context.scene_draft.repository import SceneDraftRepository
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
MAX_FORMAT_REPAIRS = 1


class CandidateChangeServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class CandidateChangeService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        scene_service: SceneService,
        draft_repository: SceneDraftRepository,
        extract_repository: CandidateChangeRepository,
        audit_writer: AuditWriter,
        llm_gateway: LlmGateway,
        task_type: str = DEFAULT_TASK_TYPE,
        repair_task_type: str = DEFAULT_REPAIR_TASK_TYPE,
        auto_run: bool = True,
    ) -> None:
        self._story = story_repository
        self._scenes = scene_service
        self._drafts = draft_repository
        self._repo = extract_repository
        self._audit = audit_writer
        self._gateway = llm_gateway
        self._task_type = task_type
        self._repair_task_type = repair_task_type
        self._auto_run = auto_run

    def trigger_job(
        self,
        *,
        project_id: str,
        scene_id: str,
        revision_id: str,
        actor: Actor,
        idempotency_key: str | None = None,
    ) -> ExtractJob:
        self._require_project(project_id)
        trigger = _require_trigger_actor(actor)
        scene = self._require_scene(project_id, scene_id)
        draft = self._require_extractable_draft(project_id, scene.id, revision_id)

        key = _clean_optional(idempotency_key)
        if key is not None:
            existing = self._repo.find_job_by_idempotency_key(
                project_id, scene.id, draft.id, key
            )
            if existing is not None and existing.state in JOB_REUSABLE_STATES:
                return existing

        now = _utc_now_z()
        job = ExtractJob(
            id=str(uuid4()),
            project_id=project_id,
            scene_id=scene.id,
            draft_id=draft.id,
            draft_revision=draft.revision,
            prompt_version=prompt_version(),
            state=JOB_QUEUED,
            created_at=now,
            updated_at=now,
            created_by=trigger.actor_id or draft.created_by,
            actor_type=trigger.actor_type,
            idempotency_key=key,
        )
        self._repo.add_job(job)
        self._write_audit(
            actor=trigger,
            action="extract_job.create",
            resource_type="extract_job",
            resource_id=job.id,
            before_json=None,
            after_json=job.to_audit_dict(),
        )
        if self._auto_run:
            self._run_job(job, scene=scene, draft=draft)
        return job

    def get_job(self, project_id: str, job_id: str) -> ExtractJob:
        self._require_project(project_id)
        job = self._repo.get_job(job_id)
        if job is None or job.project_id != project_id:
            raise CandidateChangeServiceError(404, {"error": "extract_job_not_found"})
        return job

    def cancel_job(self, project_id: str, job_id: str, *, actor: Actor) -> ExtractJob:
        self._require_project(project_id)
        try:
            editor = require_human_editor(
                actor, action="cancel", resource="Candidate Change extract job"
            )
        except ActorError as exc:
            raise CandidateChangeServiceError(
                403,
                {
                    "error": "actor_not_allowed",
                    "message": str(exc),
                },
            ) from exc
        job = self.get_job(project_id, job_id)
        if job.state not in JOB_CANCELLABLE_STATES:
            raise CandidateChangeServiceError(
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

    def list_candidates(self, project_id: str, scene_id: str) -> list[CandidateChange]:
        self._require_project(project_id)
        scene = self._require_scene(project_id, scene_id)
        return self._repo.list_candidates(project_id, scene.id)

    def _run_job(self, job: ExtractJob, *, scene: Scene, draft: SceneDraft) -> None:
        self._transition(job, JOB_RUNNING, actor_type=SYSTEM)
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(scene=scene, draft=draft)
        first = self._generate(
            job,
            attempt=ATTEMPT_GENERATE,
            task_type=self._task_type,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        assembled, errors = self._validate_response(first, scene=scene, draft=draft)
        if assembled is not None:
            self._succeed(job, draft=draft, payloads=assembled)
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
        assembled, errors = self._validate_response(repair, scene=scene, draft=draft)
        if assembled is not None:
            self._succeed(job, draft=draft, payloads=assembled)
            return
        self._fail(job, reason="schema_validation_failed", errors=errors)

    def _generate(
        self,
        job: ExtractJob,
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
        self,
        response: GenerateResponse | None,
        *,
        scene: Scene,
        draft: SceneDraft,
    ) -> tuple[list[dict[str, Any]] | None, list[dict[str, str]]]:
        if response is None:
            return None, [{"path": "", "message": "provider_call_failed"}]
        if response.error is not None:
            return None, [
                {
                    "path": "",
                    "message": response.error.code,
                }
            ]
        raw_items, extract_error = _raw_candidate_items(response.parsed_output)
        if extract_error is not None:
            return None, [{"path": "", "message": extract_error}]
        assembled: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for index, raw in enumerate(raw_items):
            if not isinstance(raw, dict):
                errors.append(
                    {
                        "path": f"candidates.{index}",
                        "message": "candidate must be an object",
                    }
                )
                continue
            payload = _assemble_candidate(
                raw,
                project_id=scene.project_id,
                scene_id=scene.id,
                created_by=draft.created_by,
            )
            try:
                validate_candidate_change(payload)
            except CandidateChangeSchemaError as exc:
                for item in exc.errors:
                    path = item["path"]
                    prefix = f"candidates.{index}"
                    item["path"] = f"{prefix}.{path}" if path else prefix
                    errors.append(item)
                continue
            assembled.append(payload)
        if errors:
            return None, errors
        return assembled, []

    def _succeed(
        self,
        job: ExtractJob,
        *,
        draft: SceneDraft,
        payloads: list[dict[str, Any]],
    ) -> None:
        def persist() -> None:
            batch = self._repo.next_extract_batch(
                job.project_id, job.scene_id, job.draft_id
            )
            candidate_ids: list[str] = []
            for payload in payloads:
                candidate = CandidateChange(
                    id=str(payload["id"]),
                    project_id=job.project_id,
                    scene_id=job.scene_id,
                    draft_id=job.draft_id,
                    job_id=job.id,
                    extract_batch=batch,
                    schema_version=str(payload["schema_version"]),
                    subject=str(payload["subject"]),
                    predicate=str(payload["predicate"]),
                    object=str(payload["object"]),
                    value=str(payload["value"]),
                    effective_story_time=str(payload["effective_story_time"]),
                    source_scene_id=str(payload["source_scene_id"]),
                    evidence_quote=str(payload["evidence_quote"]),
                    confidence=float(payload["confidence"]),
                    status=CANDIDATE_EXTRACTED,
                    created_at=str(payload["created_at"]),
                    created_by=str(payload["created_by"]),
                    payload=payload,
                )
                self._repo.add_candidate(candidate)
                candidate_ids.append(candidate.id)
                self._write_audit(
                    actor=Actor(actor_type=SYSTEM, actor_id=None),
                    action="candidate_change.create",
                    resource_type="candidate_change",
                    resource_id=candidate.id,
                    before_json=None,
                    after_json=candidate.to_audit_dict(),
                )
            job.extract_batch = batch
            job.candidate_ids = candidate_ids
            job.validation_result = {"ok": True, "errors": [], "attempt": job.state}
            job.failure_reason = None
            job.evidence = None
            self._mark_draft_extracted(draft)
            self._transition(job, JOB_SUCCEEDED, actor_type=SYSTEM)

        self._gateway.invoke_once("persist_generation_state", persist)

    def _mark_draft_extracted(self, draft: SceneDraft) -> None:
        if draft.status != DRAFT_GENERATED:
            return
        before = draft.to_audit_dict()
        body_before = draft.body
        hash_before = draft.content_hash
        draft.status = DRAFT_EXTRACTED
        if draft.body != body_before or draft.content_hash != hash_before:
            raise CandidateChangeServiceError(
                409,
                {
                    "error": "draft_body_immutable",
                    "message": "Extraction must not overwrite Scene Draft prose.",
                },
            )
        self._drafts.save_draft(draft)
        self._write_audit(
            actor=Actor(actor_type=SYSTEM, actor_id=None),
            action="scene_draft.extract",
            resource_type="scene_draft",
            resource_id=draft.id,
            before_json=before,
            after_json=draft.to_audit_dict(),
        )

    def _fail(
        self, job: ExtractJob, *, reason: str, errors: list[dict[str, str]]
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

    def _transition(self, job: ExtractJob, new_state: str, *, actor_type: str) -> None:
        before = job.to_audit_dict()
        self._set_state(job, new_state)
        self._write_audit(
            actor=Actor(actor_type=actor_type, actor_id=None),
            action="extract_job.transition",
            resource_type="extract_job",
            resource_id=job.id,
            before_json=before,
            after_json=job.to_audit_dict(),
        )

    def _set_state(self, job: ExtractJob, new_state: str) -> None:
        previous = job.state
        now = _utc_now_z()
        job.transitions.append({"from": previous, "to": new_state, "at": now})
        job.state = new_state
        job.updated_at = now
        self._persist_job(job)

    def _persist_job(self, job: ExtractJob) -> None:
        self._repo.save_job(job)

    def _require_extractable_draft(
        self, project_id: str, scene_id: str, revision_id: str
    ) -> SceneDraft:
        cleaned = _clean_optional(revision_id)
        if cleaned is None:
            raise CandidateChangeServiceError(
                422,
                {
                    "error": "draft_id_required",
                    "message": "A generated immutable Scene Draft id is required.",
                },
            )
        draft = self._drafts.get_draft(cleaned)
        if (
            draft is None
            or draft.project_id != project_id
            or draft.scene_id != scene_id
        ):
            raise CandidateChangeServiceError(404, {"error": "scene_draft_not_found"})
        if content_hash(draft.body) != draft.content_hash:
            raise CandidateChangeServiceError(
                409,
                {
                    "error": "draft_not_immutable",
                    "message": (
                        "Scene Draft body does not match its content hash. "
                        "Extraction requires an immutable generated draft and "
                        "never overwrites prose."
                    ),
                    "draft_id": draft.id,
                    "status": draft.status,
                },
            )
        if draft.status not in EXTRACTABLE_DRAFT_STATUSES:
            raise CandidateChangeServiceError(
                409,
                {
                    "error": "draft_not_extractable",
                    "message": (
                        "Extraction requires a generated immutable Scene Draft "
                        "(status Generated, or a later extractable status). "
                        "Missing, failed, cancelled, superseded, or overwritten "
                        "drafts are rejected. Extraction does not write Canon."
                    ),
                    "draft_id": draft.id,
                    "status": draft.status,
                },
            )
        return draft

    def _require_scene(self, project_id: str, scene_id: str) -> Scene:
        try:
            return self._scenes.get_scene(project_id, scene_id)
        except SceneServiceError as exc:
            raise CandidateChangeServiceError(exc.status_code, exc.detail) from exc

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise CandidateChangeServiceError(404, {"error": "project_not_found"})

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


def _raw_candidate_items(parsed: Any) -> tuple[list[Any], str | None]:
    if isinstance(parsed, list):
        return parsed, None
    if isinstance(parsed, dict):
        if "candidates" in parsed:
            items = parsed.get("candidates")
            if not isinstance(items, list):
                return [], "candidates_must_be_array"
            return items, None
        return [parsed], None
    return [], "structured_parse_failed"


def _assemble_candidate(
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
        "subject": raw.get("subject"),
        "predicate": raw.get("predicate"),
        "object": raw.get("object"),
        "value": raw.get("value"),
        "effective_story_time": raw.get("effective_story_time"),
        "source_scene_id": scene_id,
        "evidence_quote": raw.get("evidence_quote"),
        "confidence": raw.get("confidence"),
        "status": CANDIDATE_EXTRACTED,
    }


def _require_trigger_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or GENERATION_AGENT
    if actor_type == REVIEW_AGENT:
        raise CandidateChangeServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Review agents cannot trigger Candidate Change extraction. "
                    "Use human_editor, generation_agent, or system."
                ),
                "actor_type": actor_type,
            },
        )
    if actor_type not in ALLOWED_TRIGGER_ACTORS:
        raise CandidateChangeServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Extract jobs may be triggered by the human 主编, "
                    "a generation agent, or the system. This is extract, "
                    "not Canon approval and not Validate."
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


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
