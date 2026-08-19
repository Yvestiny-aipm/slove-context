"""Human shuttle service (nodes UI.2 / UI.3).

Copy a deterministic prompt out; paste prose, candidates, or summaries
back. Does not call LLM Gateway / Fake Provider. Does not write Canon.
Does not approve. Does not auto-submit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.candidate_change.models import (
    CANDIDATE_EXTRACTED,
    JOB_QUEUED,
    JOB_REUSABLE_STATES,
    CandidateChange,
    ExtractJob,
)
from slove_context.candidate_change.repository import CandidateChangeRepository
from slove_context.candidate_change.service import (
    CandidateChangeService,
    assemble_candidate,
)
from slove_context.candidate_change.validate import (
    CandidateChangeSchemaError,
    validate_candidate_change,
)
from slove_context.canon.models import SNAPSHOT_FROZEN, CanonFact, CanonSnapshot
from slove_context.canon.repository import CanonRepository
from slove_context.logging import get_request_id
from slove_context.review_queue.models import SUBJECT_CANDIDATE_CHANGE
from slove_context.review_queue.service import (
    ReviewQueueService,
    ReviewQueueServiceError,
)
from slove_context.scene.models import (
    DEPENDENCY_SATISFYING_STATUSES,
    Chapter,
    Scene,
)
from slove_context.scene.service import SceneService, SceneServiceError
from slove_context.scene_draft.metrics import (
    character_count,
    content_hash,
    word_count_estimate,
)
from slove_context.scene_draft.models import (
    DRAFT_EXTRACTED,
    DRAFT_GENERATED,
    DRAFT_SUPERSEDED,
    SceneDraft,
    SceneDraftJob,
)
from slove_context.scene_draft.models import (
    JOB_REUSABLE_STATES as DRAFT_JOB_REUSABLE_STATES,
)
from slove_context.scene_draft.models import (
    JOB_SUCCEEDED as DRAFT_JOB_SUCCEEDED,
)
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.scene_plan.repository import ScenePlanRepository
from slove_context.shuttle.models import (
    EXTERNAL_SUBSCRIBED_MODEL,
    MIN_DRAFT_BODY_CHARS,
    MIN_SCENE_SUMMARY_BODY_CHARS,
    PURPOSE_CHAPTER_SUMMARY,
    PURPOSE_EXTRACT,
    PURPOSE_SCENE_DRAFT,
    PURPOSE_SCENE_SUMMARY,
    SHUTTLE_CHAPTER_SUMMARY_PROMPT_VERSION,
    SHUTTLE_DRAFT_PROMPT_VERSION,
    SHUTTLE_EXTRACT_PROMPT_VERSION,
    SHUTTLE_SCENE_SUMMARY_PROMPT_VERSION,
)
from slove_context.shuttle.prompt import (
    build_chapter_summary_prompt,
    build_draft_prompt,
    build_extract_prompt,
    build_scene_summary_prompt,
)
from slove_context.story.actors import (
    HUMAN_EDITOR,
    SYSTEM,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.models import StorySpecVersion
from slove_context.story.repository import StoryRepository
from slove_context.summary.models import (
    JOB_QUEUED as SUMMARY_JOB_QUEUED,
)
from slove_context.summary.models import (
    JOB_REUSABLE_STATES as SUMMARY_JOB_REUSABLE_STATES,
)
from slove_context.summary.models import (
    JOB_SUCCEEDED as SUMMARY_JOB_SUCCEEDED,
)
from slove_context.summary.models import (
    KIND_CHAPTER,
    KIND_SCENE,
    SUMMARY_GENERATED,
    SUMMARY_SUPERSEDED,
    ChapterSummary,
    SceneSummary,
    SummaryJob,
)
from slove_context.summary.repository import SummaryRepository
from slove_context.summary.service import SUMMARIZABLE_DRAFT_STATUSES


class ShuttleServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class ShuttleService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        canon_repository: CanonRepository,
        scene_service: SceneService,
        plan_repository: ScenePlanRepository,
        draft_repository: SceneDraftRepository,
        extract_repository: CandidateChangeRepository,
        extract_service: CandidateChangeService,
        audit_writer: AuditWriter,
        summary_repository: SummaryRepository,
        review_queue_service: ReviewQueueService | None = None,
        enqueue_review_items: bool = False,
    ) -> None:
        self._story = story_repository
        self._canon = canon_repository
        self._scenes = scene_service
        self._plans = plan_repository
        self._drafts = draft_repository
        self._extract_repo = extract_repository
        self._extracts = extract_service
        self._summaries = summary_repository
        self._audit = audit_writer
        self._review_queue = review_queue_service
        # 4.1 standalone extract does not enqueue. Keep the same default.
        self._enqueue_review_items = enqueue_review_items

    def draft_prompt(
        self, project_id: str, scene_id: str, *, actor: Actor
    ) -> dict[str, Any]:
        editor = self._require_human(
            actor, action="copy", resource="shuttle draft prompt"
        )
        self._require_project(project_id)
        scene = self._require_approved_scene(project_id, scene_id)
        snapshot = self._preferred_snapshot(project_id)
        excerpts = self._snapshot_excerpts(project_id, snapshot)
        spec = self._current_spec_version(project_id)
        prompt = build_draft_prompt(
            scene=scene,
            spec=spec,
            snapshot_id=snapshot.id if snapshot is not None else None,
            excerpts=excerpts,
        )
        self._write_audit(
            actor=editor,
            action="shuttle.draft_prompt",
            resource_type="shuttle_prompt",
            resource_id=scene.id,
            before_json=None,
            after_json={
                "purpose": PURPOSE_SCENE_DRAFT,
                "scene_id": scene.id,
                "snapshot_id": snapshot.id if snapshot is not None else None,
                "prompt_chars": len(prompt),
                "is_canon": False,
            },
        )
        return {
            "prompt": prompt,
            "purpose": PURPOSE_SCENE_DRAFT,
            "scene_id": scene.id,
            "is_canon": False,
        }

    def import_draft(
        self,
        *,
        project_id: str,
        scene_id: str,
        body: str,
        snapshot_id: str,
        actor: Actor,
        plan_id: str | None = None,
        context_pack_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        editor = self._require_human(actor, action="paste", resource="shuttle draft")
        self._require_project(project_id)
        scene = self._require_scene(project_id, scene_id)
        snapshot = self._require_snapshot(project_id, snapshot_id)
        prose = body if isinstance(body, str) else ""
        if len(prose.strip()) < MIN_DRAFT_BODY_CHARS:
            raise ShuttleServiceError(
                400,
                {
                    "error": "draft_body_too_short",
                    "message": (
                        f"Pasted prose must be at least {MIN_DRAFT_BODY_CHARS} "
                        "non-whitespace-stripped characters. Paste-back is not "
                        "approval and does not write Canon."
                    ),
                    "min_chars": MIN_DRAFT_BODY_CHARS,
                },
            )

        key = _clean_optional(idempotency_key)
        if key is not None:
            existing = self._drafts.find_job_by_idempotency_key(
                project_id, scene.id, key
            )
            if existing is not None and existing.state in DRAFT_JOB_REUSABLE_STATES:
                draft = (
                    self._drafts.get_draft(existing.draft_id)
                    if existing.draft_id
                    else None
                )
                return {
                    "job": existing.to_public_dict(),
                    "draft": draft.to_public_dict() if draft is not None else None,
                    "is_canon": False,
                    "auto_approved": False,
                    "writes_canon": False,
                }

        resolved_plan = _clean_optional(plan_id) or self._current_plan_id(
            project_id, scene.id
        )
        resolved_pack = _clean_optional(context_pack_id) or ""
        now = _utc_now_z()
        job = SceneDraftJob(
            id=str(uuid4()),
            project_id=project_id,
            scene_id=scene.id,
            scene_card_id=scene.scene_card_id,
            plan_id=resolved_plan or "",
            snapshot_id=snapshot.id,
            context_pack_id=resolved_pack,
            prompt_version=SHUTTLE_DRAFT_PROMPT_VERSION,
            state=JOB_QUEUED,
            created_at=now,
            updated_at=now,
            created_by=editor.actor_id or scene.created_by,
            actor_type=HUMAN_EDITOR,
            idempotency_key=key,
        )
        self._drafts.add_job(job)
        self._write_audit(
            actor=editor,
            action="shuttle.draft_import.create",
            resource_type="scene_draft_job",
            resource_id=job.id,
            before_json=None,
            after_json=job.to_audit_dict(),
        )
        draft = self._persist_imported_draft(
            job,
            scene=scene,
            body=prose,
            actor=editor,
        )
        return {
            "job": job.to_public_dict(),
            "draft": draft.to_public_dict(),
            "is_canon": False,
            "auto_approved": False,
            "writes_canon": False,
        }

    def extract_prompt(
        self,
        project_id: str,
        scene_id: str,
        revision_id: str,
        *,
        actor: Actor,
    ) -> dict[str, Any]:
        editor = self._require_human(
            actor, action="copy", resource="shuttle extract prompt"
        )
        self._require_project(project_id)
        scene = self._require_scene(project_id, scene_id)
        draft = self._require_draft(project_id, scene.id, revision_id)
        prompt = build_extract_prompt(scene=scene, draft=draft)
        self._write_audit(
            actor=editor,
            action="shuttle.extract_prompt",
            resource_type="shuttle_prompt",
            resource_id=draft.id,
            before_json=None,
            after_json={
                "purpose": PURPOSE_EXTRACT,
                "draft_id": draft.id,
                "scene_id": scene.id,
                "prompt_chars": len(prompt),
                "is_canon": False,
            },
        )
        return {
            "prompt": prompt,
            "purpose": PURPOSE_EXTRACT,
            "draft_id": draft.id,
            "is_canon": False,
        }

    def import_extract(
        self,
        *,
        project_id: str,
        scene_id: str,
        revision_id: str,
        candidates: list[Any],
        actor: Actor,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        editor = self._require_human(actor, action="paste", resource="shuttle extract")
        self._require_project(project_id)
        scene = self._require_scene(project_id, scene_id)
        draft = self._require_draft(project_id, scene.id, revision_id)
        if not isinstance(candidates, list):
            raise ShuttleServiceError(
                400,
                {
                    "error": "candidates_must_be_array",
                    "message": "Body.candidates must be a JSON array.",
                },
            )

        key = _clean_optional(idempotency_key)
        if key is not None:
            existing = self._extract_repo.find_job_by_idempotency_key(
                project_id, scene.id, draft.id, key
            )
            if existing is not None and existing.state in JOB_REUSABLE_STATES:
                items = [
                    item
                    for item in self._extracts.list_candidates(project_id, scene.id)
                    if item.job_id == existing.id
                ]
                return {
                    "job": existing.to_public_dict(),
                    "items": [item.to_public_dict() for item in items],
                    "is_canon": False,
                    "auto_approved": False,
                    "writes_canon": False,
                }

        assembled = self._assemble_and_validate(
            candidates,
            scene=scene,
            draft=draft,
            created_by=editor.actor_id or "主编",
        )
        now = _utc_now_z()
        job = ExtractJob(
            id=str(uuid4()),
            project_id=project_id,
            scene_id=scene.id,
            draft_id=draft.id,
            draft_revision=draft.revision,
            prompt_version=SHUTTLE_EXTRACT_PROMPT_VERSION,
            state=JOB_QUEUED,
            created_at=now,
            updated_at=now,
            created_by=editor.actor_id or draft.created_by,
            actor_type=HUMAN_EDITOR,
            idempotency_key=key,
        )
        self._extract_repo.add_job(job)
        self._write_audit(
            actor=editor,
            action="shuttle.extract_import.create",
            resource_type="extract_job",
            resource_id=job.id,
            before_json=None,
            after_json=job.to_audit_dict(),
        )
        persisted = self._extracts.persist_extracted_payloads(
            job, draft=draft, payloads=assembled
        )
        if self._enqueue_review_items:
            self._enqueue_candidates(project_id, persisted, actor=editor)
        return {
            "job": job.to_public_dict(),
            "items": [item.to_public_dict() for item in persisted],
            "is_canon": False,
            "auto_approved": False,
            "writes_canon": False,
        }

    def scene_summary_prompt(
        self,
        project_id: str,
        scene_id: str,
        *,
        draft_revision_id: str,
        actor: Actor,
    ) -> dict[str, Any]:
        editor = self._require_human(
            actor, action="copy", resource="shuttle scene summary prompt"
        )
        self._require_project(project_id)
        scene = self._require_scene(project_id, scene_id)
        draft = self._require_summarizable_draft(
            project_id, scene.id, draft_revision_id
        )
        prompt = build_scene_summary_prompt(scene=scene, draft=draft)
        self._write_audit(
            actor=editor,
            action="shuttle.scene_summary_prompt",
            resource_type="shuttle_prompt",
            resource_id=draft.id,
            before_json=None,
            after_json={
                "purpose": PURPOSE_SCENE_SUMMARY,
                "scene_id": scene.id,
                "draft_revision_id": draft.id,
                "draft_content_hash": draft.content_hash,
                "prompt_chars": len(prompt),
                "is_canon": False,
            },
        )
        return {
            "prompt": prompt,
            "purpose": PURPOSE_SCENE_SUMMARY,
            "scene_id": scene.id,
            "draft_revision_id": draft.id,
            "is_canon": False,
        }

    def import_scene_summary(
        self,
        *,
        project_id: str,
        scene_id: str,
        draft_revision_id: str,
        body: str,
        actor: Actor,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        editor = self._require_human(
            actor, action="paste", resource="shuttle scene summary"
        )
        self._require_project(project_id)
        scene = self._require_scene(project_id, scene_id)
        draft = self._require_summarizable_draft(
            project_id, scene.id, draft_revision_id
        )
        prose = body if isinstance(body, str) else ""
        if len(prose.strip()) < MIN_SCENE_SUMMARY_BODY_CHARS:
            raise ShuttleServiceError(
                422,
                {
                    "error": "scene_summary_body_too_short",
                    "message": (
                        f"Pasted scene summary must be at least "
                        f"{MIN_SCENE_SUMMARY_BODY_CHARS} characters after "
                        "stripping whitespace. Paste-back is not approval "
                        "and does not write Canon."
                    ),
                    "min_chars": MIN_SCENE_SUMMARY_BODY_CHARS,
                },
            )

        key = _clean_optional(idempotency_key)
        if key is not None:
            existing = self._summaries.find_job_by_idempotency_key(
                project_id, KIND_SCENE, scene.id, key
            )
            if existing is not None and existing.state in SUMMARY_JOB_REUSABLE_STATES:
                summary = (
                    self._summaries.get_scene_summary(existing.summary_id)
                    if existing.summary_id
                    else None
                )
                return _summary_import_payload(existing, summary)

        now = _utc_now_z()
        job = SummaryJob(
            id=str(uuid4()),
            project_id=project_id,
            kind=KIND_SCENE,
            scene_id=scene.id,
            draft_revision_id=draft.id,
            source_draft_content_hash=draft.content_hash,
            prompt_version=SHUTTLE_SCENE_SUMMARY_PROMPT_VERSION,
            state=SUMMARY_JOB_QUEUED,
            created_at=now,
            updated_at=now,
            created_by=editor.actor_id or scene.created_by,
            actor_type=HUMAN_EDITOR,
            idempotency_key=key,
        )
        self._summaries.add_job(job)
        self._write_audit(
            actor=editor,
            action="shuttle.scene_summary_import.create",
            resource_type="summary_job",
            resource_id=job.id,
            before_json=None,
            after_json=job.to_audit_dict(),
        )
        summary = self._persist_imported_scene_summary(
            job, scene=scene, draft=draft, body=prose, actor=editor
        )
        return _summary_import_payload(job, summary)

    def chapter_summary_prompt(
        self,
        project_id: str,
        chapter_id: str,
        *,
        actor: Actor,
    ) -> dict[str, Any]:
        editor = self._require_human(
            actor, action="copy", resource="shuttle chapter summary prompt"
        )
        self._require_project(project_id)
        chapter = self._require_chapter(project_id, chapter_id)
        sources = self._require_chapter_scene_summaries(project_id, chapter)
        prompt = build_chapter_summary_prompt(
            chapter_id=chapter.id, scene_summaries=sources
        )
        self._write_audit(
            actor=editor,
            action="shuttle.chapter_summary_prompt",
            resource_type="shuttle_prompt",
            resource_id=chapter.id,
            before_json=None,
            after_json={
                "purpose": PURPOSE_CHAPTER_SUMMARY,
                "chapter_id": chapter.id,
                "source_scene_summary_revision_ids": [item.id for item in sources],
                "prompt_chars": len(prompt),
                "is_canon": False,
            },
        )
        return {
            "prompt": prompt,
            "purpose": PURPOSE_CHAPTER_SUMMARY,
            "chapter_id": chapter.id,
            "source_scene_summary_revision_ids": [item.id for item in sources],
            "is_canon": False,
        }

    def import_chapter_summary(
        self,
        *,
        project_id: str,
        chapter_id: str,
        body: str,
        source_scene_summary_revision_ids: list[str],
        actor: Actor,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        editor = self._require_human(
            actor, action="paste", resource="shuttle chapter summary"
        )
        self._require_project(project_id)
        chapter = self._require_chapter(project_id, chapter_id)
        sources = self._require_cited_chapter_scene_summaries(
            project_id,
            chapter,
            source_scene_summary_revision_ids,
        )
        prose = body if isinstance(body, str) else ""
        if not prose.strip():
            raise ShuttleServiceError(
                422,
                {
                    "error": "chapter_summary_body_empty",
                    "message": (
                        "Pasted chapter summary must not be empty. "
                        "Paste-back is not approval and does not write Canon."
                    ),
                },
            )

        key = _clean_optional(idempotency_key)
        if key is not None:
            existing = self._summaries.find_job_by_idempotency_key(
                project_id, KIND_CHAPTER, chapter.id, key
            )
            if existing is not None and existing.state in SUMMARY_JOB_REUSABLE_STATES:
                summary = (
                    self._summaries.get_chapter_summary(existing.summary_id)
                    if existing.summary_id
                    else None
                )
                return _summary_import_payload(existing, summary)

        source_ids = [item.id for item in sources]
        now = _utc_now_z()
        job = SummaryJob(
            id=str(uuid4()),
            project_id=project_id,
            kind=KIND_CHAPTER,
            chapter_id=chapter.id,
            source_scene_summary_revision_ids=source_ids,
            prompt_version=SHUTTLE_CHAPTER_SUMMARY_PROMPT_VERSION,
            state=SUMMARY_JOB_QUEUED,
            created_at=now,
            updated_at=now,
            created_by=editor.actor_id or chapter.created_by,
            actor_type=HUMAN_EDITOR,
            idempotency_key=key,
        )
        self._summaries.add_job(job)
        self._write_audit(
            actor=editor,
            action="shuttle.chapter_summary_import.create",
            resource_type="summary_job",
            resource_id=job.id,
            before_json=None,
            after_json=job.to_audit_dict(),
        )
        summary = self._persist_imported_chapter_summary(
            job, sources=sources, body=prose, actor=editor
        )
        return _summary_import_payload(job, summary)

    def _assemble_and_validate(
        self,
        raw_items: list[Any],
        *,
        scene: Scene,
        draft: SceneDraft,
        created_by: str,
    ) -> list[dict[str, Any]]:
        assembled: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_items):
            if not isinstance(raw, dict):
                raise ShuttleServiceError(
                    400,
                    {
                        "error": "candidate_not_object",
                        "message": "Each candidate must be an object.",
                        "index": index,
                    },
                )
            quote = raw.get("evidence_quote")
            if not isinstance(quote, str) or quote not in draft.body:
                raise ShuttleServiceError(
                    400,
                    {
                        "error": "evidence_quote_not_in_draft",
                        "message": (
                            "Every evidence_quote must be a substring of that "
                            "revision's body. Nothing was persisted."
                        ),
                        "index": index,
                    },
                )
            payload = assemble_candidate(
                raw,
                project_id=scene.project_id,
                scene_id=scene.id,
                created_by=created_by,
            )
            try:
                validate_candidate_change(payload)
            except CandidateChangeSchemaError as exc:
                raise ShuttleServiceError(
                    422,
                    {
                        "error": "candidate_schema_failed",
                        "message": (
                            "Pasted candidates failed "
                            "contracts/candidate-change.schema.json. "
                            "Nothing was persisted. Candidates are not Canon."
                        ),
                        "errors": exc.errors,
                    },
                ) from exc
            if payload.get("status") != CANDIDATE_EXTRACTED:
                raise ShuttleServiceError(
                    400,
                    {
                        "error": "candidate_status_not_extracted",
                        "message": "Shuttle extract may only persist Extracted candidates.",
                    },
                )
            assembled.append(payload)
        return assembled

    def _persist_imported_draft(
        self,
        job: SceneDraftJob,
        *,
        scene: Scene,
        body: str,
        actor: Actor,
    ) -> SceneDraft:
        now = _utc_now_z()
        previous = self._previous_live_draft(job.project_id, job.scene_id)
        revision = self._drafts.next_revision(job.project_id, job.scene_id)
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
            generation_model=EXTERNAL_SUBSCRIBED_MODEL,
            prompt_version=SHUTTLE_DRAFT_PROMPT_VERSION,
            generated_at=now,
            scene_card_id=job.scene_card_id,
            plan_id=job.plan_id,
            snapshot_id=job.snapshot_id,
            context_pack_id=job.context_pack_id,
            created_at=now,
            created_by=actor.actor_id or scene.created_by,
        )
        self._drafts.add_draft(draft)
        if previous is not None:
            before = previous.to_audit_dict()
            previous.status = DRAFT_SUPERSEDED
            self._drafts.save_draft(previous)
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
        before_job = job.to_audit_dict()
        job.transitions.append(
            {"from": job.state, "to": DRAFT_JOB_SUCCEEDED, "at": now}
        )
        job.state = DRAFT_JOB_SUCCEEDED
        job.updated_at = now
        self._drafts.save_job(job)
        self._write_audit(
            actor=Actor(actor_type=SYSTEM, actor_id=None),
            action="scene_draft_job.transition",
            resource_type="scene_draft_job",
            resource_id=job.id,
            before_json=before_job,
            after_json=job.to_audit_dict(),
        )
        self._write_audit(
            actor=actor,
            action="shuttle.draft_import",
            resource_type="scene_draft",
            resource_id=draft.id,
            before_json=None,
            after_json=draft.to_audit_dict(),
        )
        return draft

    def _previous_live_draft(self, project_id: str, scene_id: str) -> SceneDraft | None:
        for draft in self._drafts.list_drafts(project_id, scene_id):
            if draft.status in {DRAFT_GENERATED, DRAFT_EXTRACTED}:
                return draft
        return None

    def _enqueue_candidates(
        self,
        project_id: str,
        candidates: list[CandidateChange],
        *,
        actor: Actor,
    ) -> None:
        if self._review_queue is None:
            return
        for candidate in candidates:
            try:
                self._review_queue.enqueue(
                    project_id=project_id,
                    actor=actor,
                    body={
                        "subject_type": SUBJECT_CANDIDATE_CHANGE,
                        "subject_id": candidate.id,
                    },
                )
            except ReviewQueueServiceError:
                continue

    def _require_human(self, actor: Actor, *, action: str, resource: str) -> Actor:
        try:
            return require_human_editor(actor, action=action, resource=resource)
        except ActorError as exc:
            raise ShuttleServiceError(
                403,
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                },
            ) from exc

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise ShuttleServiceError(404, {"error": "project_not_found"})

    def _require_scene(self, project_id: str, scene_id: str) -> Scene:
        try:
            return self._scenes.get_scene(project_id, scene_id)
        except SceneServiceError as exc:
            raise ShuttleServiceError(exc.status_code, exc.detail) from exc

    def _require_approved_scene(self, project_id: str, scene_id: str) -> Scene:
        scene = self._require_scene(project_id, scene_id)
        if scene.status not in DEPENDENCY_SATISFYING_STATUSES:
            raise ShuttleServiceError(
                409,
                {
                    "error": "scene_card_not_approved",
                    "message": (
                        "Draft prompt requires an approved Scene Card. "
                        "The shuttle does not create a draft."
                    ),
                    "scene_id": scene.id,
                    "status": scene.status,
                },
            )
        return scene

    def _require_draft(
        self, project_id: str, scene_id: str, revision_id: str
    ) -> SceneDraft:
        cleaned = _clean_optional(revision_id)
        if cleaned is None:
            raise ShuttleServiceError(404, {"error": "scene_draft_not_found"})
        draft = self._drafts.get_draft(cleaned)
        if (
            draft is None
            or draft.project_id != project_id
            or draft.scene_id != scene_id
        ):
            raise ShuttleServiceError(404, {"error": "scene_draft_not_found"})
        return draft

    def _require_snapshot(self, project_id: str, snapshot_id: str) -> CanonSnapshot:
        cleaned = _clean_optional(snapshot_id)
        if cleaned is None:
            raise ShuttleServiceError(
                422,
                {
                    "error": "snapshot_id_required",
                    "message": "snapshot_id is required to attach the imported draft.",
                },
            )
        snapshot = self._canon.get_snapshot(cleaned)
        if snapshot is None or snapshot.project_id != project_id:
            raise ShuttleServiceError(404, {"error": "canon_snapshot_not_found"})
        return snapshot

    def _preferred_snapshot(self, project_id: str) -> CanonSnapshot | None:
        snapshots = self._canon.list_snapshots(project_id)
        frozen = [item for item in snapshots if item.status == SNAPSHOT_FROZEN]
        if frozen:
            return frozen[-1]
        return snapshots[-1] if snapshots else None

    def _snapshot_excerpts(
        self, project_id: str, snapshot: CanonSnapshot | None
    ) -> list[dict[str, str]]:
        if snapshot is None:
            return []
        facts = [
            fact
            for fact in self._canon.list_facts(project_id)
            if fact.id in set(snapshot.fact_ids)
        ]
        excerpts: list[dict[str, str]] = []
        for fact in sorted(facts, key=lambda item: (item.id, item.predicate)):
            excerpts.append(_excerpt_for_fact(self._canon, fact))
        return excerpts

    def _current_spec_version(self, project_id: str) -> StorySpecVersion | None:
        spec = self._story.get_spec_for_project(project_id)
        if spec is None:
            return None
        try:
            return spec.current_version()
        except KeyError:
            return None

    def _current_plan_id(self, project_id: str, scene_id: str) -> str:
        plan = self._plans.current_plan(project_id, scene_id)
        return str(plan.id) if plan is not None else ""

    def _persist_imported_scene_summary(
        self,
        job: SummaryJob,
        *,
        scene: Scene,
        draft: SceneDraft,
        body: str,
        actor: Actor,
    ) -> SceneSummary:
        now = _utc_now_z()
        previous = self._summaries.current_scene_summary(job.project_id, scene.id)
        revision = self._summaries.next_scene_revision(job.project_id, scene.id)
        summary = SceneSummary(
            id=str(uuid4()),
            project_id=job.project_id,
            scene_id=scene.id,
            job_id=job.id,
            revision=revision,
            status=SUMMARY_GENERATED,
            body=body,
            content_hash=content_hash(body),
            source_draft_revision_id=draft.id,
            source_draft_revision=draft.revision,
            source_draft_content_hash=draft.content_hash,
            prompt_version=SHUTTLE_SCENE_SUMMARY_PROMPT_VERSION,
            generated_at=now,
            generation_model=EXTERNAL_SUBSCRIBED_MODEL,
            created_at=now,
            created_by=actor.actor_id or scene.created_by,
        )
        self._summaries.add_scene_summary(summary)
        if previous is not None:
            before = previous.to_audit_dict()
            previous.status = SUMMARY_SUPERSEDED
            self._summaries.save_scene_summary(previous)
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
        before_job = job.to_audit_dict()
        job.transitions.append(
            {"from": job.state, "to": SUMMARY_JOB_SUCCEEDED, "at": now}
        )
        job.state = SUMMARY_JOB_SUCCEEDED
        job.updated_at = now
        self._summaries.save_job(job)
        self._write_audit(
            actor=Actor(actor_type=SYSTEM, actor_id=None),
            action="summary_job.transition",
            resource_type="summary_job",
            resource_id=job.id,
            before_json=before_job,
            after_json=job.to_audit_dict(),
        )
        self._write_audit(
            actor=actor,
            action="shuttle.scene_summary_import",
            resource_type="scene_summary",
            resource_id=summary.id,
            before_json=None,
            after_json=summary.to_audit_dict(),
        )
        return summary

    def _persist_imported_chapter_summary(
        self,
        job: SummaryJob,
        *,
        sources: list[SceneSummary],
        body: str,
        actor: Actor,
    ) -> ChapterSummary:
        now = _utc_now_z()
        chapter_id = job.chapter_id or ""
        previous = self._summaries.current_chapter_summary(job.project_id, chapter_id)
        revision = self._summaries.next_chapter_revision(job.project_id, chapter_id)
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
            prompt_version=SHUTTLE_CHAPTER_SUMMARY_PROMPT_VERSION,
            generated_at=now,
            generation_model=EXTERNAL_SUBSCRIBED_MODEL,
            created_at=now,
            created_by=actor.actor_id or job.created_by,
        )
        self._summaries.add_chapter_summary(summary)
        if previous is not None:
            before = previous.to_audit_dict()
            previous.status = SUMMARY_SUPERSEDED
            self._summaries.save_chapter_summary(previous)
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
        before_job = job.to_audit_dict()
        job.transitions.append(
            {"from": job.state, "to": SUMMARY_JOB_SUCCEEDED, "at": now}
        )
        job.state = SUMMARY_JOB_SUCCEEDED
        job.updated_at = now
        self._summaries.save_job(job)
        self._write_audit(
            actor=Actor(actor_type=SYSTEM, actor_id=None),
            action="summary_job.transition",
            resource_type="summary_job",
            resource_id=job.id,
            before_json=before_job,
            after_json=job.to_audit_dict(),
        )
        self._write_audit(
            actor=actor,
            action="shuttle.chapter_summary_import",
            resource_type="chapter_summary",
            resource_id=summary.id,
            before_json=None,
            after_json=summary.to_audit_dict(),
        )
        return summary

    def _require_summarizable_draft(
        self, project_id: str, scene_id: str, draft_revision_id: str
    ) -> SceneDraft:
        cleaned = _clean_optional(draft_revision_id)
        if cleaned is None:
            raise ShuttleServiceError(
                422,
                {
                    "error": "draft_revision_id_required",
                    "message": (
                        "A Scene Summary shuttle must reference an existing "
                        "Scene Draft revision. Missing drafts are rejected."
                    ),
                },
            )
        draft = self._drafts.get_draft(cleaned)
        if (
            draft is None
            or draft.project_id != project_id
            or draft.scene_id != scene_id
        ):
            raise ShuttleServiceError(
                404,
                {
                    "error": "scene_draft_not_found",
                    "message": (
                        "Scene Summary requires an existing Scene Draft "
                        "revision. Missing drafts are rejected. "
                        "The shuttle does not create a summary."
                    ),
                    "draft_revision_id": cleaned,
                },
            )
        if draft.status not in SUMMARIZABLE_DRAFT_STATUSES:
            raise ShuttleServiceError(
                409,
                {
                    "error": "draft_not_summarizable",
                    "message": (
                        "Scene Summary requires an existing generated Scene "
                        "Draft revision. Failed or cancelled drafts are rejected."
                    ),
                    "draft_revision_id": draft.id,
                    "status": draft.status,
                },
            )
        return draft

    def _require_chapter(self, project_id: str, chapter_id: str) -> Chapter:
        try:
            return self._scenes.get_chapter(project_id, chapter_id)
        except SceneServiceError as exc:
            raise ShuttleServiceError(exc.status_code, exc.detail) from exc

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
            raise ShuttleServiceError(
                409,
                {
                    "error": "chapter_has_no_scenes",
                    "message": (
                        "Chapter Summary rolls up Scene Summaries. A chapter "
                        "with no scenes cannot be summarized. Do not invent."
                    ),
                    "chapter_id": chapter.id,
                },
            )
        sources: list[SceneSummary] = []
        missing: list[str] = []
        for scene in scenes:
            current = self._summaries.current_scene_summary(project_id, scene.id)
            if current is None:
                missing.append(scene.id)
            else:
                sources.append(current)
        if missing:
            raise ShuttleServiceError(
                409,
                {
                    "error": "scene_summaries_missing",
                    "message": (
                        "Chapter Summary is rolled up from existing Scene "
                        "Summaries. Required scene summaries are missing. "
                        "Do not invent."
                    ),
                    "chapter_id": chapter.id,
                    "missing_scene_ids": missing,
                },
            )
        return sources

    def _require_cited_chapter_scene_summaries(
        self,
        project_id: str,
        chapter: Chapter,
        source_ids: list[str],
    ) -> list[SceneSummary]:
        sources = self._require_chapter_scene_summaries(project_id, chapter)
        required = {item.id for item in sources}
        provided = [_clean_optional(item) for item in source_ids]
        cleaned = [item for item in provided if item is not None]
        if set(cleaned) != required:
            raise ShuttleServiceError(
                409,
                {
                    "error": "source_scene_summary_revision_ids_incomplete",
                    "message": (
                        "Chapter Summary must cite the current Scene Summary "
                        "revision of every scene in the chapter. "
                        "Incomplete citations are rejected. Do not invent."
                    ),
                    "chapter_id": chapter.id,
                    "required_revision_ids": sorted(required),
                },
            )
        return sources

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


def _excerpt_for_fact(canon: CanonRepository, fact: CanonFact) -> dict[str, str]:
    entity = canon.get_entity(fact.entity_id)
    name = entity.name.strip() if entity is not None else ""
    value = fact.predicate.strip()
    if isinstance(fact.value_json, str) and fact.value_json.strip():
        value = f"{fact.predicate.strip()} {fact.value_json.strip()}".strip()
    statement = " ".join(part for part in (name, value) if part) or "已批准 Canon 事实"
    return {
        "statement": statement,
        "source_evidence": "主编已批准并提交",
        "effective_story_time": fact.effective_story_time.strip() or "未标注故事时间",
    }


def _summary_import_payload(
    job: SummaryJob, summary: SceneSummary | ChapterSummary | None
) -> dict[str, Any]:
    return {
        "job": job.to_public_dict(),
        "summary": summary.to_public_dict() if summary is not None else None,
        "is_canon": False,
        "auto_approved": False,
        "writes_canon": False,
        "is_scene_draft": False,
        "is_candidate_change": False,
    }


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
