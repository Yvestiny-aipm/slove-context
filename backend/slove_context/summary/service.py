"""Scene / Chapter summary jobs (node 4.3).

Scene Summary requires an existing immutable Scene Draft revision
(draft_revision_id + its content hash). Missing drafts are rejected.

Chapter Summary rolls up current Scene Summaries of scenes in that
chapter. It does not generate chapter prose. Missing required scene
summaries are rejected.

Summaries are immutable revisions. Retry creates a new row. Old rows
are never overwritten. Summaries are not Canon, not Scene Draft, and
not Candidate Changes. Jobs do not write Canon and do not auto-approve.

Uses Fake Provider via LlmGateway.generate_text only.

Idempotency rules (also in models.py and README):
1. Duplicate submit: the same idempotency_key on the same scene or
   chapter returns the existing job if that job is still queued,
   running, or succeeded.
2. Retry after success: omit the key or send a new key. That creates a
   new job and a new summary revision. The previous revision stays
   intact and is marked Superseded.
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
from slove_context.llm.errors import LlmError
from slove_context.llm.gateway import LlmGateway
from slove_context.llm.types import GenerateRequest, GenerateResponse
from slove_context.logging import get_request_id
from slove_context.scene.models import Chapter, Scene
from slove_context.scene.service import SceneService, SceneServiceError
from slove_context.scene_draft.metrics import content_hash
from slove_context.scene_draft.models import (
    DRAFT_EXTRACTED,
    DRAFT_GENERATED,
    DRAFT_SUPERSEDED,
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
from slove_context.summary.models import (
    CHAPTER_PROMPT_VERSION,
    DEFAULT_CHAPTER_TASK_TYPE,
    DEFAULT_SCENE_TASK_TYPE,
    JOB_CANCELLABLE_STATES,
    JOB_CANCELLED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_REUSABLE_STATES,
    JOB_RUNNING,
    JOB_SUCCEEDED,
    KIND_CHAPTER,
    KIND_SCENE,
    SCENE_PROMPT_VERSION,
    SUMMARY_GENERATED,
    SUMMARY_SUPERSEDED,
    ChapterSummary,
    SceneSummary,
    SummaryJob,
)
from slove_context.summary.prompt import (
    build_chapter_system_prompt,
    build_chapter_user_prompt,
    build_scene_system_prompt,
    build_scene_user_prompt,
    chapter_prompt_version,
    scene_prompt_version,
)
from slove_context.summary.repository import SummaryRepository

ALLOWED_TRIGGER_ACTORS = frozenset({HUMAN_EDITOR, GENERATION_AGENT, SYSTEM})
SUMMARIZABLE_DRAFT_STATUSES = frozenset(
    {DRAFT_GENERATED, DRAFT_EXTRACTED, DRAFT_SUPERSEDED}
)


class SummaryServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class SummaryService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        scene_service: SceneService,
        draft_repository: SceneDraftRepository,
        summary_repository: SummaryRepository,
        audit_writer: AuditWriter,
        llm_gateway: LlmGateway,
        scene_task_type: str = DEFAULT_SCENE_TASK_TYPE,
        chapter_task_type: str = DEFAULT_CHAPTER_TASK_TYPE,
        auto_run: bool = True,
    ) -> None:
        self._story = story_repository
        self._scenes = scene_service
        self._drafts = draft_repository
        self._repo = summary_repository
        self._audit = audit_writer
        self._gateway = llm_gateway
        self._scene_task_type = scene_task_type
        self._chapter_task_type = chapter_task_type
        self._auto_run = auto_run

    def trigger_scene_job(
        self,
        *,
        project_id: str,
        scene_id: str,
        draft_revision_id: str,
        actor: Actor,
        idempotency_key: str | None = None,
        content_hash_value: str | None = None,
    ) -> SummaryJob:
        self._require_project(project_id)
        trigger = _require_trigger_actor(actor)
        scene = self._require_scene(project_id, scene_id)
        draft = self._require_summarizable_draft(
            project_id,
            scene.id,
            draft_revision_id,
            expected_hash=content_hash_value,
        )

        key = _clean_optional(idempotency_key)
        if key is not None:
            existing = self._repo.find_job_by_idempotency_key(
                project_id, KIND_SCENE, scene.id, key
            )
            if existing is not None and existing.state in JOB_REUSABLE_STATES:
                return existing

        now = _utc_now_z()
        job = SummaryJob(
            id=str(uuid4()),
            project_id=project_id,
            kind=KIND_SCENE,
            scene_id=scene.id,
            draft_revision_id=draft.id,
            source_draft_content_hash=draft.content_hash,
            prompt_version=scene_prompt_version(),
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
            action="summary_job.create",
            resource_type="summary_job",
            resource_id=job.id,
            before_json=None,
            after_json=job.to_audit_dict(),
        )
        if self._auto_run:
            self._run_scene_job(job, scene=scene, draft=draft)
        return job

    def trigger_chapter_job(
        self,
        *,
        project_id: str,
        chapter_id: str,
        actor: Actor,
        idempotency_key: str | None = None,
    ) -> SummaryJob:
        self._require_project(project_id)
        trigger = _require_trigger_actor(actor)
        chapter = self._require_chapter(project_id, chapter_id)
        sources = self._require_chapter_scene_summaries(project_id, chapter)

        key = _clean_optional(idempotency_key)
        if key is not None:
            existing = self._repo.find_job_by_idempotency_key(
                project_id, KIND_CHAPTER, chapter.id, key
            )
            if existing is not None and existing.state in JOB_REUSABLE_STATES:
                return existing

        source_ids = [item.id for item in sources]
        now = _utc_now_z()
        job = SummaryJob(
            id=str(uuid4()),
            project_id=project_id,
            kind=KIND_CHAPTER,
            chapter_id=chapter.id,
            source_scene_summary_revision_ids=source_ids,
            prompt_version=chapter_prompt_version(),
            state=JOB_QUEUED,
            created_at=now,
            updated_at=now,
            created_by=trigger.actor_id or chapter.created_by,
            actor_type=trigger.actor_type,
            idempotency_key=key,
        )
        self._repo.add_job(job)
        self._write_audit(
            actor=trigger,
            action="summary_job.create",
            resource_type="summary_job",
            resource_id=job.id,
            before_json=None,
            after_json=job.to_audit_dict(),
        )
        if self._auto_run:
            self._run_chapter_job(job, sources=sources)
        return job

    def get_scene_job(self, project_id: str, job_id: str) -> SummaryJob:
        return self._get_job(project_id, job_id, kind=KIND_SCENE)

    def get_chapter_job(self, project_id: str, job_id: str) -> SummaryJob:
        return self._get_job(project_id, job_id, kind=KIND_CHAPTER)

    def cancel_scene_job(
        self, project_id: str, job_id: str, *, actor: Actor
    ) -> SummaryJob:
        return self._cancel_job(project_id, job_id, kind=KIND_SCENE, actor=actor)

    def cancel_chapter_job(
        self, project_id: str, job_id: str, *, actor: Actor
    ) -> SummaryJob:
        return self._cancel_job(project_id, job_id, kind=KIND_CHAPTER, actor=actor)

    def list_scene_summaries(self, project_id: str, scene_id: str) -> list[SceneSummary]:
        self._require_project(project_id)
        scene = self._require_scene(project_id, scene_id)
        return self._repo.list_scene_summaries(project_id, scene.id)

    def get_scene_summary(
        self, project_id: str, scene_id: str, revision_id: str
    ) -> SceneSummary:
        self._require_project(project_id)
        scene = self._require_scene(project_id, scene_id)
        summary = self._repo.get_scene_summary(revision_id)
        if (
            summary is None
            or summary.project_id != project_id
            or summary.scene_id != scene.id
        ):
            raise SummaryServiceError(404, {"error": "scene_summary_not_found"})
        return summary

    def list_chapter_summaries(
        self, project_id: str, chapter_id: str
    ) -> list[ChapterSummary]:
        self._require_project(project_id)
        chapter = self._require_chapter(project_id, chapter_id)
        return self._repo.list_chapter_summaries(project_id, chapter.id)

    def get_chapter_summary(
        self, project_id: str, chapter_id: str, revision_id: str
    ) -> ChapterSummary:
        self._require_project(project_id)
        chapter = self._require_chapter(project_id, chapter_id)
        summary = self._repo.get_chapter_summary(revision_id)
        if (
            summary is None
            or summary.project_id != project_id
            or summary.chapter_id != chapter.id
        ):
            raise SummaryServiceError(404, {"error": "chapter_summary_not_found"})
        return summary

    def _get_job(self, project_id: str, job_id: str, *, kind: str) -> SummaryJob:
        self._require_project(project_id)
        job = self._repo.get_job(job_id)
        if job is None or job.project_id != project_id or job.kind != kind:
            raise SummaryServiceError(404, {"error": "summary_job_not_found"})
        return job

    def _cancel_job(
        self, project_id: str, job_id: str, *, kind: str, actor: Actor
    ) -> SummaryJob:
        self._require_project(project_id)
        try:
            editor = require_human_editor(
                actor, action="cancel", resource="summary job"
            )
        except ActorError as exc:
            raise SummaryServiceError(
                403,
                {
                    "error": "actor_not_allowed",
                    "message": str(exc),
                },
            ) from exc
        job = self._get_job(project_id, job_id, kind=kind)
        if job.state not in JOB_CANCELLABLE_STATES:
            raise SummaryServiceError(
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

    def _run_scene_job(
        self, job: SummaryJob, *, scene: Scene, draft: SceneDraft
    ) -> None:
        self._transition(job, JOB_RUNNING, actor_type=SYSTEM)
        response = self._generate(
            job,
            system_prompt=build_scene_system_prompt(),
            user_prompt=build_scene_user_prompt(scene=scene, draft=draft),
            task_type=self._scene_task_type,
            prompt_version=SCENE_PROMPT_VERSION,
        )
        body, reason = _text_from_response(response)
        if body is None:
            self._fail(job, reason=reason or "generate_failed")
            return
        self._succeed_scene(
            job,
            body=body,
            model=_model_from_response(response),
            draft=draft,
        )

    def _run_chapter_job(
        self, job: SummaryJob, *, sources: list[SceneSummary]
    ) -> None:
        self._transition(job, JOB_RUNNING, actor_type=SYSTEM)
        chapter_id = job.chapter_id or ""
        response = self._generate(
            job,
            system_prompt=build_chapter_system_prompt(),
            user_prompt=build_chapter_user_prompt(
                chapter_id=chapter_id, scene_summaries=sources
            ),
            task_type=self._chapter_task_type,
            prompt_version=CHAPTER_PROMPT_VERSION,
        )
        body, reason = _text_from_response(response)
        if body is None:
            self._fail(job, reason=reason or "generate_failed")
            return
        self._succeed_chapter(
            job,
            body=body,
            model=_model_from_response(response),
            sources=sources,
        )

    def _generate(
        self,
        job: SummaryJob,
        *,
        system_prompt: str,
        user_prompt: str,
        task_type: str,
        prompt_version: str,
    ) -> GenerateResponse | None:
        request = GenerateRequest(
            model="fake-model",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=512,
            correlation_id=get_request_id() or job.id,
            task_type=task_type,
            prompt_version=prompt_version,
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

    def _succeed_scene(
        self,
        job: SummaryJob,
        *,
        body: str,
        model: str,
        draft: SceneDraft,
    ) -> None:
        def persist() -> None:
            now = _utc_now_z()
            previous = self._repo.current_scene_summary(job.project_id, draft.scene_id)
            revision = self._repo.next_scene_revision(job.project_id, draft.scene_id)
            summary = SceneSummary(
                id=str(uuid4()),
                project_id=job.project_id,
                scene_id=draft.scene_id,
                job_id=job.id,
                revision=revision,
                status=SUMMARY_GENERATED,
                body=body,
                content_hash=content_hash(body),
                source_draft_revision_id=draft.id,
                source_draft_revision=draft.revision,
                source_draft_content_hash=draft.content_hash,
                prompt_version=job.prompt_version,
                generated_at=now,
                generation_model=model,
                created_at=now,
                created_by=job.created_by,
            )
            self._repo.add_scene_summary(summary)
            if previous is not None:
                before = previous.to_audit_dict()
                previous.status = SUMMARY_SUPERSEDED
                self._repo.save_scene_summary(previous)
                self._write_audit(
                    actor=Actor(actor_type=SYSTEM, actor_id=None),
                    action="scene_summary.supersede",
                    resource_type="scene_summary",
                    resource_id=previous.id,
                    before_json=before,
                    after_json=previous.to_audit_dict(),
                )
            job.summary_id = summary.id
            job.summary_revision = summary.revision
            job.failure_reason = None
            job.evidence = None
            self._transition(job, JOB_SUCCEEDED, actor_type=SYSTEM)
            self._write_audit(
                actor=Actor(actor_type=SYSTEM, actor_id=None),
                action="scene_summary.create",
                resource_type="scene_summary",
                resource_id=summary.id,
                before_json=None,
                after_json=summary.to_audit_dict(),
            )

        self._gateway.invoke_once("persist_generation_state", persist)

    def _succeed_chapter(
        self,
        job: SummaryJob,
        *,
        body: str,
        model: str,
        sources: list[SceneSummary],
    ) -> None:
        def persist() -> None:
            now = _utc_now_z()
            chapter_id = job.chapter_id or ""
            previous = self._repo.current_chapter_summary(job.project_id, chapter_id)
            revision = self._repo.next_chapter_revision(job.project_id, chapter_id)
            source_ids = [item.id for item in sources]
            summary = ChapterSummary(
                id=str(uuid4()),
                project_id=job.project_id,
                chapter_id=chapter_id,
                job_id=job.id,
                revision=revision,
                status=SUMMARY_GENERATED,
                body=body,
                content_hash=content_hash(body),
                source_scene_summary_revision_ids=source_ids,
                prompt_version=job.prompt_version,
                generated_at=now,
                generation_model=model,
                created_at=now,
                created_by=job.created_by,
            )
            self._repo.add_chapter_summary(summary)
            if previous is not None:
                before = previous.to_audit_dict()
                previous.status = SUMMARY_SUPERSEDED
                self._repo.save_chapter_summary(previous)
                self._write_audit(
                    actor=Actor(actor_type=SYSTEM, actor_id=None),
                    action="chapter_summary.supersede",
                    resource_type="chapter_summary",
                    resource_id=previous.id,
                    before_json=before,
                    after_json=previous.to_audit_dict(),
                )
            job.summary_id = summary.id
            job.summary_revision = summary.revision
            job.source_scene_summary_revision_ids = source_ids
            job.failure_reason = None
            job.evidence = None
            self._transition(job, JOB_SUCCEEDED, actor_type=SYSTEM)
            self._write_audit(
                actor=Actor(actor_type=SYSTEM, actor_id=None),
                action="chapter_summary.create",
                resource_type="chapter_summary",
                resource_id=summary.id,
                before_json=None,
                after_json=summary.to_audit_dict(),
            )

        self._gateway.invoke_once("persist_generation_state", persist)

    def _fail(self, job: SummaryJob, *, reason: str) -> None:
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
        self, job: SummaryJob, new_state: str, *, actor_type: str
    ) -> None:
        before = job.to_audit_dict()
        self._set_state(job, new_state)
        self._write_audit(
            actor=Actor(actor_type=actor_type, actor_id=None),
            action="summary_job.transition",
            resource_type="summary_job",
            resource_id=job.id,
            before_json=before,
            after_json=job.to_audit_dict(),
        )

    def _set_state(self, job: SummaryJob, new_state: str) -> None:
        previous = job.state
        now = _utc_now_z()
        job.transitions.append({"from": previous, "to": new_state, "at": now})
        job.state = new_state
        job.updated_at = now
        self._persist_job(job)

    def _persist_job(self, job: SummaryJob) -> None:
        self._repo.save_job(job)

    def _require_summarizable_draft(
        self,
        project_id: str,
        scene_id: str,
        draft_revision_id: str,
        *,
        expected_hash: str | None,
    ) -> SceneDraft:
        cleaned = _clean_required(draft_revision_id)
        if cleaned is None:
            raise SummaryServiceError(
                422,
                {
                    "error": "draft_revision_id_required",
                    "message": (
                        "A Scene Summary must reference an existing Scene Draft "
                        "revision id and its content hash."
                    ),
                },
            )
        draft = self._drafts.get_draft(cleaned)
        if (
            draft is None
            or draft.project_id != project_id
            or draft.scene_id != scene_id
        ):
            raise SummaryServiceError(
                404,
                {
                    "error": "scene_draft_not_found",
                    "message": (
                        "Scene Summary requires an existing Scene Draft revision. "
                        "Missing drafts are rejected. Summary is not Canon."
                    ),
                    "draft_revision_id": cleaned,
                },
            )
        if content_hash(draft.body) != draft.content_hash:
            raise SummaryServiceError(
                409,
                {
                    "error": "draft_not_immutable",
                    "message": (
                        "Scene Draft body does not match its content hash. "
                        "Summaries require an immutable generated draft."
                    ),
                    "draft_revision_id": draft.id,
                },
            )
        expected = _clean_optional(expected_hash)
        if expected is not None and expected != draft.content_hash:
            raise SummaryServiceError(
                409,
                {
                    "error": "draft_content_hash_mismatch",
                    "message": (
                        "Provided content hash does not match the referenced "
                        "Scene Draft revision."
                    ),
                    "draft_revision_id": draft.id,
                },
            )
        if draft.status not in SUMMARIZABLE_DRAFT_STATUSES:
            raise SummaryServiceError(
                409,
                {
                    "error": "draft_not_summarizable",
                    "message": (
                        "Scene Summary requires an existing generated Scene Draft "
                        "revision (Generated, Extracted, or a kept superseded "
                        "revision). Failed or cancelled drafts are rejected."
                    ),
                    "draft_revision_id": draft.id,
                    "status": draft.status,
                },
            )
        return draft

    def _require_chapter_scene_summaries(
        self, project_id: str, chapter: Chapter
    ) -> list[SceneSummary]:
        scenes = [
            scene
            for scene in self._scenes.list_scenes(project_id)
            if scene.chapter_id == chapter.id
        ]
        scenes.sort(key=lambda item: item.story_order)
        if not scenes:
            raise SummaryServiceError(
                409,
                {
                    "error": "chapter_has_no_scenes",
                    "message": (
                        "Chapter Summary rolls up Scene Summaries. A chapter "
                        "with no scenes cannot be summarized. This is not a "
                        "chapter-level prose generate entrance."
                    ),
                    "chapter_id": chapter.id,
                },
            )
        sources: list[SceneSummary] = []
        missing: list[str] = []
        for scene in scenes:
            current = self._repo.current_scene_summary(project_id, scene.id)
            if current is None:
                missing.append(scene.id)
            else:
                sources.append(current)
        if missing:
            raise SummaryServiceError(
                409,
                {
                    "error": "scene_summaries_missing",
                    "message": (
                        "Chapter Summary is rolled up from existing Scene "
                        "Summaries. Required scene summaries are missing. "
                        "This job does not generate chapter prose."
                    ),
                    "chapter_id": chapter.id,
                    "missing_scene_ids": missing,
                },
            )
        return sources

    def _require_scene(self, project_id: str, scene_id: str) -> Scene:
        try:
            return self._scenes.get_scene(project_id, scene_id)
        except SceneServiceError as exc:
            raise SummaryServiceError(exc.status_code, exc.detail) from exc

    def _require_chapter(self, project_id: str, chapter_id: str) -> Chapter:
        try:
            return self._scenes.get_chapter(project_id, chapter_id)
        except SceneServiceError as exc:
            raise SummaryServiceError(exc.status_code, exc.detail) from exc

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise SummaryServiceError(404, {"error": "project_not_found"})

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


def _text_from_response(
    response: GenerateResponse | None,
) -> tuple[str | None, str | None]:
    if response is None:
        return None, "provider_call_failed"
    if response.error is not None:
        return None, response.error.code
    text = response.parsed_output
    if not isinstance(text, str) or not text.strip():
        return None, "empty_summary"
    return text, None


def _model_from_response(response: GenerateResponse | None) -> str:
    if response is None or not response.model:
        return "fake-model"
    return response.model


def _require_trigger_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or GENERATION_AGENT
    if actor_type == REVIEW_AGENT:
        raise SummaryServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Review agents cannot trigger summary jobs. "
                    "Use human_editor, generation_agent, or system."
                ),
                "actor_type": actor_type,
            },
        )
    if actor_type not in ALLOWED_TRIGGER_ACTORS:
        raise SummaryServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Summary jobs may be triggered by the human 主编, "
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
