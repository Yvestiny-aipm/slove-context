"""Release check / manifest / export write path (node 9.3).

Gates are read-only over existing artifacts. The service never writes
Canon, never approves Candidate Changes, and never generates prose.
Failed checks are kept and are not formal releases.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.agents.permissions import PermissionDenied, PermissionGuard
from slove_context.audit import AuditWriter
from slove_context.candidate_change.repository import CandidateChangeRepository
from slove_context.canon.repository import CanonRepository
from slove_context.logging import get_request_id
from slove_context.release.export import (
    build_json_export,
    build_markdown,
    build_review_pack,
    hash_export_body,
)
from slove_context.release.gates import (
    GateContext,
    current_drafts_for_scenes,
    flatten_failures,
    gate_stats,
    run_all_gates,
)
from slove_context.release.models import (
    CHECK_CANCELLED,
    CHECK_FAILED,
    CHECK_PASSED,
    CHECK_RUNNING,
    DUE_STATUS_DUE,
    DUE_STATUS_HANDLED,
    DUE_STATUS_WAIVED,
    DUE_STATUSES,
    EXPORT_FORMATS,
    EXPORT_JSON,
    EXPORT_MARKDOWN,
    GATE_IDS,
    MANIFEST_SCHEMA,
    SAFETY_PLACEHOLDER,
    SAFETY_RECORDED,
    SAFETY_WAIVED,
    WAIVER_DUE_ITEM,
    WAIVER_KINDS,
    WAIVER_SAFETY,
    DueItem,
    HumanWaiver,
    ReleaseCheck,
    ReleaseExport,
    ReleaseManifest,
    SafetyCheck,
    stable_hash,
)
from slove_context.release.repository import ReleaseRepository
from slove_context.repair.repository import RepairRepository
from slove_context.review_queue.models import STATUS_APPROVED, SUBJECT_SCENE_DRAFT
from slove_context.review_queue.repository import ReviewQueueRepository
from slove_context.scene.models import Chapter, Scene
from slove_context.scene.repository import SceneRepository
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.story.actors import (
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.repository import StoryRepository
from slove_context.style_validation.repository import StyleValidationRepository
from slove_context.summary.models import SUMMARY_GENERATED
from slove_context.summary.repository import SummaryRepository
from slove_context.validation.repository import ValidationRepository


class ReleaseServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class ReleaseService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        canon_repository: CanonRepository,
        scene_repository: SceneRepository,
        scene_draft_repository: SceneDraftRepository,
        candidate_change_repository: CandidateChangeRepository,
        validation_repository: ValidationRepository,
        repair_repository: RepairRepository,
        summary_repository: SummaryRepository,
        style_validation_repository: StyleValidationRepository,
        review_queue_repository: ReviewQueueRepository,
        release_repository: ReleaseRepository,
        audit_writer: AuditWriter,
    ) -> None:
        self._story = story_repository
        self._canon = canon_repository
        self._scenes = scene_repository
        self._drafts = scene_draft_repository
        self._candidates = candidate_change_repository
        self._validations = validation_repository
        self._repairs = repair_repository
        self._summaries = summary_repository
        self._styles = style_validation_repository
        self._reviews = review_queue_repository
        self._repo = release_repository
        self._audit = audit_writer
        self._guard = PermissionGuard()

    def run_check(
        self,
        *,
        project_id: str,
        actor: Actor,
        snapshot_id: str,
        scene_ids: list[str] | None = None,
        chapter_ids: list[str] | None = None,
    ) -> ReleaseCheck:
        self._require_project(project_id)
        editor = self._human(actor, action="run", resource="Release Check")
        now = _utc_now_z()
        check = ReleaseCheck(
            id=str(uuid4()),
            project_id=project_id,
            snapshot_id=snapshot_id,
            status=CHECK_RUNNING,
            created_at=now,
            updated_at=now,
            created_by=_actor_id(editor),
            actor_type=editor.actor_type,
        )
        self._repo.add_check(check)
        self._write_audit(
            editor, "release_check.create", check.id, after=check.to_audit_dict()
        )

        snapshot = self._canon.get_snapshot(snapshot_id)
        scenes, chapters = self._resolve_targets(
            project_id, scene_ids=scene_ids, chapter_ids=chapter_ids
        )
        drafts = current_drafts_for_scenes(
            {
                scene.id: self._drafts.list_drafts(project_id, scene.id)
                for scene in scenes
            },
            [scene.id for scene in scenes],
        )
        candidates = [
            item
            for scene in scenes
            for item in self._candidates.list_candidates(project_id, scene.id)
        ]
        reports = [
            item
            for item in self._validations.list_reports(project_id)
            if item.scene_id in {scene.id for scene in scenes}
        ]
        runs = [
            item
            for item in self._validations.list_runs(project_id)
            if item.scene_id in {scene.id for scene in scenes}
        ]
        repairs = [
            item
            for item in self._repairs.list_tasks(project_id)
            if item.scene_id in {scene.id for scene in scenes}
        ]
        summaries = []
        for chapter in chapters:
            current = self._summaries.current_chapter_summary(project_id, chapter.id)
            if current is not None and current.status == SUMMARY_GENERATED:
                summaries.append(current)
        style_runs = [
            item
            for item in self._styles.list_for_project(project_id)
            if item.scene_id in {scene.id for scene in scenes}
        ]
        ctx = GateContext(
            project_id=project_id,
            snapshot=snapshot,
            scenes=scenes,
            chapters=chapters,
            drafts=drafts,
            candidates=candidates,
            reports=reports,
            runs=runs,
            repairs=repairs,
            review_items=self._reviews.list_items(project_id),
            chapter_summaries=summaries,
            style_runs=style_runs,
            due_items=self._repo.list_due_items(project_id),
            safety_checks=self._repo.list_safety_checks(project_id),
            audit_writer=self._audit,
        )
        results = run_all_gates(ctx)
        failures = flatten_failures(results)
        check.scene_ids = [item.id for item in scenes]
        check.chapter_ids = [item.id for item in chapters]
        check.draft_ids = [item.id for item in drafts]
        check.gate_results = results
        check.failures = failures
        check.updated_at = _utc_now_z()
        if len(results) < 8 or {item.gate_id for item in results} < set(GATE_IDS):
            check.status = CHECK_FAILED
            check.failure_reason = "missing_gate"
        elif failures:
            check.status = CHECK_FAILED
            check.failure_reason = "gate_failed"
        else:
            check.status = CHECK_PASSED
            manifest = self._build_manifest(check, editor, ctx)
            self._repo.add_manifest(manifest)
            check.manifest_id = manifest.id
            self._write_audit(
                editor,
                "release_manifest.create",
                manifest.id,
                after=manifest.to_audit_dict(),
            )
        self._repo.save_check(check)
        self._write_audit(
            editor,
            "release_check.finish",
            check.id,
            after=check.to_audit_dict(),
        )
        return check

    def get_check(self, project_id: str, check_id: str) -> ReleaseCheck:
        return self._require_check(project_id, check_id)

    def list_checks(self, project_id: str) -> list[ReleaseCheck]:
        self._require_project(project_id)
        return self._repo.list_checks(project_id)

    def cancel_check(
        self, project_id: str, check_id: str, actor: Actor
    ) -> ReleaseCheck:
        editor = self._human(actor, action="cancel", resource="Release Check")
        check = self._require_check(project_id, check_id)
        if check.status in {CHECK_PASSED, CHECK_FAILED, CHECK_CANCELLED}:
            raise ReleaseServiceError(
                409,
                {
                    "error": "release_check_terminal",
                    "message": "A finished or cancelled check is kept and is not deleted.",
                    "status": check.status,
                },
            )
        before = check.to_audit_dict()
        check.status = CHECK_CANCELLED
        check.updated_at = _utc_now_z()
        self._repo.save_check(check)
        self._write_audit(
            editor,
            "release_check.cancel",
            check.id,
            before=before,
            after=check.to_audit_dict(),
        )
        return check

    def get_manifest(self, project_id: str, check_id: str) -> ReleaseManifest:
        check = self._require_check(project_id, check_id)
        if not check.passed or check.manifest_id is None:
            raise ReleaseServiceError(
                409,
                {
                    "error": "release_manifest_unavailable",
                    "message": (
                        "A Release Manifest exists only for a passed check. "
                        "A failed check is not a formal release."
                    ),
                    "status": check.status,
                    "failures": [item.to_public_dict() for item in check.failures],
                    "is_formal_release": False,
                },
            )
        manifest = self._repo.get_manifest(check.manifest_id)
        if manifest is None:
            raise ReleaseServiceError(
                404,
                {"error": "release_manifest_not_found", "check_id": check_id},
            )
        return manifest

    def reject_mutate_manifest(self, project_id: str, check_id: str) -> None:
        manifest = self.get_manifest(project_id, check_id)
        raise ReleaseServiceError(
            409,
            {
                "error": "release_manifest_immutable",
                "message": "A finished Release Manifest cannot be patched.",
                "manifest_id": manifest.id,
                "content_hash": manifest.content_hash,
            },
        )

    def export(
        self,
        *,
        project_id: str,
        check_id: str,
        actor: Actor,
        fmt: str,
    ) -> ReleaseExport:
        editor = self._human(actor, action="export", resource="Release Export")
        check = self._require_check(project_id, check_id)
        if not check.passed or check.manifest_id is None:
            raise ReleaseServiceError(
                409,
                {
                    "error": "formal_export_blocked",
                    "message": (
                        "Formal release export is forbidden when any gate failed. "
                        "A failed check is not a formal release."
                    ),
                    "status": check.status,
                    "failures": [item.to_public_dict() for item in check.failures],
                    "is_formal_release": False,
                },
            )
        cleaned = (fmt or "").strip().lower().replace("-", "_")
        if cleaned not in EXPORT_FORMATS:
            raise ReleaseServiceError(
                422,
                {
                    "error": "unsupported_export_format",
                    "allowed": sorted(EXPORT_FORMATS),
                },
            )
        manifest = self.get_manifest(project_id, check_id)
        scenes = [
            scene
            for scene_id in check.scene_ids
            if (scene := self._scenes.get_scene(scene_id)) is not None
        ]
        chapters = [
            chapter
            for chapter_id in check.chapter_ids
            if (chapter := self._scenes.get_chapter(chapter_id)) is not None
        ]
        drafts = [
            draft
            for draft_id in check.draft_ids
            if (draft := self._drafts.get_draft(draft_id)) is not None
        ]
        summaries = [
            item
            for chapter in chapters
            if (item := self._summaries.current_chapter_summary(project_id, chapter.id))
            is not None
        ]
        markdown = None
        json_body = None
        review_pack = None
        if cleaned == EXPORT_MARKDOWN:
            markdown = build_markdown(
                check=check,
                manifest=manifest,
                scenes=scenes,
                chapters=chapters,
                drafts=drafts,
            )
            content_hash = hash_export_body(markdown)
        elif cleaned == EXPORT_JSON:
            json_body = build_json_export(
                check=check,
                manifest=manifest,
                scenes=scenes,
                chapters=chapters,
                drafts=drafts,
                summaries=summaries,
            )
            content_hash = hash_export_body(json_body)
        else:
            review_pack = build_review_pack(
                check=check,
                manifest=manifest,
                scenes=scenes,
                drafts=drafts,
                approval_refs=_approval_refs(self._reviews.list_items(project_id)),
            )
            content_hash = hash_export_body(review_pack)
        export = ReleaseExport(
            id=str(uuid4()),
            project_id=project_id,
            check_id=check.id,
            manifest_id=manifest.id,
            fmt=cleaned,
            content_hash=content_hash,
            created_at=_utc_now_z(),
            created_by=_actor_id(editor),
            actor_type=editor.actor_type,
            markdown=markdown,
            json_body=json_body,
            review_pack=review_pack,
        )
        self._repo.add_export(export)
        check.export_ids.append(export.id)
        check.updated_at = _utc_now_z()
        self._repo.save_check(check)
        self._write_audit(
            editor,
            "release_export.create",
            export.id,
            after=export.to_audit_dict(),
        )
        return export

    def create_due_item(
        self,
        *,
        project_id: str,
        actor: Actor,
        title: str,
        scene_id: str | None = None,
        chapter_id: str | None = None,
        note: str | None = None,
    ) -> DueItem:
        self._require_project(project_id)
        editor = self._human(actor, action="create", resource="Due Item")
        cleaned = title.strip()
        if not cleaned:
            raise ReleaseServiceError(
                422,
                {"error": "due_item_title_required"},
            )
        item = DueItem(
            id=str(uuid4()),
            project_id=project_id,
            title=cleaned,
            status=DUE_STATUS_DUE,
            created_at=_utc_now_z(),
            created_by=_actor_id(editor),
            actor_type=editor.actor_type,
            scene_id=scene_id,
            chapter_id=chapter_id,
            note=note,
        )
        self._repo.add_due_item(item)
        self._write_audit(
            editor, "release_due_item.create", item.id, after=item.to_audit_dict()
        )
        return item

    def handle_due_item(self, project_id: str, item_id: str, actor: Actor) -> DueItem:
        editor = self._human(actor, action="handle", resource="Due Item")
        item = self._require_due_item(project_id, item_id)
        before = item.to_audit_dict()
        item.status = DUE_STATUS_HANDLED
        item.handled_at = _utc_now_z()
        self._repo.save_due_item(item)
        self._write_audit(
            editor,
            "release_due_item.handle",
            item.id,
            before=before,
            after=item.to_audit_dict(),
        )
        return item

    def record_safety_check(
        self,
        *,
        project_id: str,
        actor: Actor,
        scene_ids: list[str] | None = None,
        result: str = "placeholder_ok",
    ) -> SafetyCheck:
        self._require_project(project_id)
        editor = self._human(actor, action="record", resource="Safety Check")
        check = SafetyCheck(
            id=str(uuid4()),
            project_id=project_id,
            status=SAFETY_RECORDED,
            result=result or "placeholder_ok",
            created_at=_utc_now_z(),
            created_by=_actor_id(editor),
            actor_type=editor.actor_type,
            scene_ids=list(scene_ids or []),
            vendor=SAFETY_PLACEHOLDER,
        )
        self._repo.add_safety_check(check)
        self._write_audit(
            editor,
            "release_safety_check.record",
            check.id,
            after=check.to_audit_dict(),
        )
        return check

    def waive(
        self,
        *,
        project_id: str,
        actor: Actor,
        kind: str,
        subject_id: str,
        reason_code: str,
        comment: str | None = None,
    ) -> HumanWaiver:
        self._require_project(project_id)
        editor = self._human(actor, action="waive", resource="Release Waiver")
        cleaned_kind = (kind or "").strip()
        if cleaned_kind not in WAIVER_KINDS:
            raise ReleaseServiceError(
                422,
                {"error": "unsupported_waiver_kind", "allowed": sorted(WAIVER_KINDS)},
            )
        if not reason_code.strip():
            raise ReleaseServiceError(
                422,
                {"error": "waiver_reason_code_required"},
            )
        waiver = HumanWaiver(
            id=str(uuid4()),
            project_id=project_id,
            kind=cleaned_kind,
            subject_id=subject_id,
            reason_code=reason_code.strip(),
            created_at=_utc_now_z(),
            created_by=_actor_id(editor),
            actor_type=editor.actor_type,
            comment=comment,
        )
        if cleaned_kind == WAIVER_DUE_ITEM:
            item = self._require_due_item(project_id, subject_id)
            if item.status not in DUE_STATUSES:
                raise ReleaseServiceError(409, {"error": "due_item_invalid_status"})
            item.status = DUE_STATUS_WAIVED
            item.waiver_id = waiver.id
            self._repo.save_due_item(item)
        else:
            safety = self._repo.get_safety_check(subject_id)
            if safety is None:
                safety = SafetyCheck(
                    id=str(uuid4()),
                    project_id=project_id,
                    status=SAFETY_WAIVED,
                    result="human_waiver",
                    created_at=_utc_now_z(),
                    created_by=_actor_id(editor),
                    actor_type=editor.actor_type,
                    waiver_id=waiver.id,
                    vendor=SAFETY_PLACEHOLDER,
                )
                waiver = HumanWaiver(
                    id=waiver.id,
                    project_id=project_id,
                    kind=WAIVER_SAFETY,
                    subject_id=safety.id,
                    reason_code=waiver.reason_code,
                    created_at=waiver.created_at,
                    created_by=waiver.created_by,
                    actor_type=waiver.actor_type,
                    comment=waiver.comment,
                )
                self._repo.add_safety_check(safety)
            else:
                safety.status = SAFETY_WAIVED
                safety.waiver_id = waiver.id
                self._repo.save_safety_check(safety)
        self._repo.add_waiver(waiver)
        self._write_audit(
            editor,
            "release_waiver.create",
            waiver.id,
            after=waiver.to_audit_dict(),
        )
        return waiver

    def reject_canon_write(self, actor: Actor, *, action: str) -> None:
        try:
            if action == "approve":
                self._guard.assert_actor_may_approve_canon(actor)
            else:
                self._guard.assert_actor_may_submit_canon(actor)
        except PermissionDenied as exc:
            raise ReleaseServiceError(exc.status_code, exc.detail) from exc
        raise ReleaseServiceError(
            403,
            {
                "error": "release_cannot_write_canon",
                "message": (
                    "The release package cannot approve or submit Canon. "
                    "Canon write remains 4.2 human submit only."
                ),
                "action": action,
                "writes_canon": False,
            },
        )

    def _build_manifest(
        self, check: ReleaseCheck, actor: Actor, ctx: GateContext
    ) -> ReleaseManifest:
        approval_refs = _approval_refs(ctx.review_items)
        version_refs = {
            "snapshot_id": check.snapshot_id,
            "scene_ids": list(check.scene_ids),
            "chapter_ids": list(check.chapter_ids),
            "draft_ids": [
                {
                    "id": item.id,
                    "revision": item.revision,
                    "content_hash": item.content_hash,
                }
                for item in ctx.drafts
            ],
            "chapter_summary_ids": [
                {"id": item.id, "content_hash": item.content_hash}
                for item in ctx.chapter_summaries
            ],
            "style_validation_ids": [item.id for item in ctx.style_runs],
            "safety_check_ids": [item.id for item in ctx.safety_checks],
            "due_item_ids": [item.id for item in ctx.due_items],
            "waiver_ids": [item.waiver_id for item in ctx.due_items if item.waiver_id],
        }
        model_prompt_versions = [
            {
                "draft_id": item.id,
                "model": item.generation_model,
                "prompt_version": item.prompt_version,
            }
            for item in ctx.drafts
        ]
        rule_versions = sorted(
            {
                *[item.rule_version for item in ctx.style_runs if item.rule_version],
                *[item.schema_version for item in ctx.reports if item.schema_version],
            }
        )
        payload = {
            "version_refs": version_refs,
            "model_prompt_versions": model_prompt_versions,
            "rule_versions": rule_versions,
            "human_approval_records": approval_refs,
            "summary_stats": {
                **gate_stats(check.gate_results),
                "scene_count": len(check.scene_ids),
                "draft_count": len(check.draft_ids),
                "candidate_submitted": sum(
                    1 for item in ctx.candidates if item.status == "Submitted"
                ),
                "candidate_rejected": sum(
                    1 for item in ctx.candidates if item.status == "Rejected"
                ),
                "chapter_summary_count": len(ctx.chapter_summaries),
            },
        }
        manifest = ReleaseManifest(
            id=str(uuid4()),
            project_id=check.project_id,
            check_id=check.id,
            schema_version=MANIFEST_SCHEMA,
            content_hash="",
            payload=payload,
            created_at=_utc_now_z(),
            created_by=_actor_id(actor),
            actor_type=actor.actor_type,
        )
        manifest.content_hash = stable_hash(manifest.hash_payload())
        return manifest

    def _resolve_targets(
        self,
        project_id: str,
        *,
        scene_ids: list[str] | None,
        chapter_ids: list[str] | None,
    ) -> tuple[list[Scene], list[Chapter]]:
        all_scenes = self._scenes.list_scenes(project_id)
        wanted_scenes = set(scene_ids or [])
        wanted_chapters = set(chapter_ids or [])
        if wanted_scenes or wanted_chapters:
            scenes = [
                item
                for item in all_scenes
                if item.id in wanted_scenes or item.chapter_id in wanted_chapters
            ]
        else:
            scenes = list(all_scenes)
        scenes.sort(key=lambda item: (item.story_order, item.id))
        chapter_ids_resolved = {item.chapter_id for item in scenes}
        if wanted_chapters:
            chapter_ids_resolved |= wanted_chapters
        chapters: list[Chapter] = []
        for chapter_id in sorted(chapter_ids_resolved):
            chapter = self._scenes.get_chapter(chapter_id)
            if chapter is not None:
                chapters.append(chapter)
        return scenes, chapters

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise ReleaseServiceError(
                404, {"error": "project_not_found", "project_id": project_id}
            )

    def _require_check(self, project_id: str, check_id: str) -> ReleaseCheck:
        self._require_project(project_id)
        check = self._repo.get_check(check_id)
        if check is None or check.project_id != project_id:
            raise ReleaseServiceError(
                404, {"error": "release_check_not_found", "check_id": check_id}
            )
        return check

    def _require_due_item(self, project_id: str, item_id: str) -> DueItem:
        item = self._repo.get_due_item(item_id)
        if item is None or item.project_id != project_id:
            raise ReleaseServiceError(
                404, {"error": "due_item_not_found", "due_item_id": item_id}
            )
        return item

    def _human(self, actor: Actor, *, action: str, resource: str) -> Actor:
        try:
            return require_human_editor(actor, action=action, resource=resource)
        except ActorError as exc:
            raise ReleaseServiceError(
                403,
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                    "action": action,
                },
            ) from exc

    def _write_audit(
        self,
        actor: Actor,
        action: str,
        resource_id: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        self._audit.write(
            actor_type=actor.actor_type or "unknown",
            actor_id=actor.actor_id,
            action=action,
            resource_type="release",
            resource_id=resource_id,
            before_json=before,
            after_json=after,
            correlation_id=get_request_id(),
        )


def _approval_refs(items: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in items:
        if item.subject_type == SUBJECT_SCENE_DRAFT and item.status == STATUS_APPROVED:
            refs.append(
                {
                    "review_item_id": item.id,
                    "subject_type": item.subject_type,
                    "subject_id": item.subject_id,
                    "status": item.status,
                    "actor_type": item.actor_type,
                }
            )
    return refs


def _actor_id(actor: Actor) -> str:
    return actor.actor_id or "editor-1"


def _utc_now_z() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
