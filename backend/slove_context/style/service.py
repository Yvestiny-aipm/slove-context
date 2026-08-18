"""Style Guide / Style Sample write path (node 7.1).

Create draft → human approve / authorize → frozen. Changes after freeze
open a new revision / new id. Approving a style asset is not Canon
approval and does not write Canon.

Only the human 主编 may approve a Style Guide or authorize a Sample.
System / generation / review agents are rejected (403).

Use-style (associate on a Scene Draft) accepts only an Approved guide
revision and Authorized samples. Unapproved, unauthorized, or version-
mismatched references are rejected.

Writes go through AuditWriter. Audit payloads omit 正例 / 反例 /
sample body. Failure and cancel keep the row. No style scoring (7.2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.logging import get_request_id
from slove_context.scene.repository import SceneRepository
from slove_context.scene_draft.models import SceneDraft
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.story.actors import (
    HUMAN_EDITOR,
    SYSTEM,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.repository import StoryRepository
from slove_context.style.models import (
    GUIDE_APPROVED,
    GUIDE_CANCEL_FROM_STATES,
    GUIDE_CANCELLED,
    GUIDE_DRAFT,
    GUIDE_EDITABLE_STATES,
    GUIDE_FAIL_FROM_STATES,
    GUIDE_FAILED,
    GUIDE_FIELD_ALIASES,
    GUIDE_REQUIRED_FIELDS,
    GUIDE_SUPERSEDED,
    LIST_FIELDS,
    SAMPLE_AUTHORIZED,
    SAMPLE_CANCEL_FROM_STATES,
    SAMPLE_CANCELLED,
    SAMPLE_DRAFT,
    SAMPLE_EDITABLE_STATES,
    SAMPLE_FAIL_FROM_STATES,
    SAMPLE_FAILED,
    SAMPLE_SUPERSEDED,
    StyleGuide,
    StyleSample,
)
from slove_context.style.repository import StyleRepository


class StyleServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class StyleService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        style_repository: StyleRepository,
        audit_writer: AuditWriter,
        scene_repository: SceneRepository | None = None,
        draft_repository: SceneDraftRepository | None = None,
    ) -> None:
        self._story = story_repository
        self._repo = style_repository
        self._audit = audit_writer
        self._scenes = scene_repository
        self._drafts = draft_repository

    def create_guide(
        self,
        *,
        project_id: str,
        actor: Actor,
        payload: dict[str, Any] | None = None,
        created_by: str | None = None,
    ) -> StyleGuide:
        self._require_project(project_id)
        trigger = self._require_human(actor, action="create", resource="Style Guide")
        created_by_value = _require_created_by(created_by, trigger)
        fields = self._parse_guide_fields(payload or {})
        now = _utc_now_z()
        status = GUIDE_DRAFT
        failure_reason = None
        if getattr(self._repo, "force_fail", False):
            status = GUIDE_FAILED
            failure_reason = "forced_draft_fail"
        guide = StyleGuide(
            id=str(uuid4()),
            project_id=project_id,
            lineage_id=str(uuid4()),
            revision=1,
            status=status,
            created_at=now,
            created_by=created_by_value,
            actor_type=trigger.actor_type,
            failure_reason=failure_reason,
            **fields,
        )
        self._repo.add_guide(guide)
        self._write_audit(
            actor=trigger,
            action=(
                "style_guide.failed" if status == GUIDE_FAILED else "style_guide.create"
            ),
            resource_type="style_guide",
            resource_id=guide.id,
            before_json=None,
            after_json=guide.to_audit_dict(),
        )
        return guide

    def patch_guide(
        self,
        *,
        project_id: str,
        guide_id: str,
        actor: Actor,
        payload: dict[str, Any] | None = None,
    ) -> StyleGuide:
        trigger = self._require_human(actor, action="edit", resource="Style Guide")
        guide = self._get_guide(project_id, guide_id)
        if guide.status == GUIDE_APPROVED:
            raise StyleServiceError(
                409,
                {
                    "error": "approved_not_editable_in_place",
                    "message": (
                        "An approved Style Guide cannot be edited in place. "
                        "Changes must POST .../revise to open a new revision / "
                        "new id. Approving a style asset is not Canon approval."
                    ),
                    "status": guide.status,
                    "writes_canon": False,
                    "is_canon_approval": False,
                },
            )
        if guide.status not in GUIDE_EDITABLE_STATES:
            raise StyleServiceError(
                409,
                {
                    "error": "style_guide_not_editable",
                    "message": (
                        "PATCH is allowed only on a Draft Style Guide. "
                        "Approved / Authorized rows are frozen."
                    ),
                    "status": guide.status,
                },
            )
        before = guide.to_audit_dict()
        if getattr(self._repo, "force_fail", False):
            guide.status = GUIDE_FAILED
            guide.failure_reason = "forced_save_fail"
            self._repo.save_guide(guide)
            self._write_audit(
                actor=trigger,
                action="style_guide.failed",
                resource_type="style_guide",
                resource_id=guide.id,
                before_json=before,
                after_json=guide.to_audit_dict(),
            )
            return guide
        if payload:
            fields = self._parse_guide_fields(payload, partial=True)
            for key, value in fields.items():
                setattr(guide, key, value)
        self._repo.save_guide(guide)
        self._write_audit(
            actor=trigger,
            action="style_guide.patch",
            resource_type="style_guide",
            resource_id=guide.id,
            before_json=before,
            after_json=guide.to_audit_dict(),
        )
        return guide

    def approve_guide(self, project_id: str, guide_id: str, actor: Actor) -> StyleGuide:
        trigger = self._require_human(actor, action="approve", resource="Style Guide")
        guide = self._get_guide(project_id, guide_id)
        if guide.status != GUIDE_DRAFT:
            raise StyleServiceError(
                409,
                {
                    "error": "invalid_style_guide_transition",
                    "message": (
                        "Only a Draft Style Guide may be approved "
                        "(Draft → Approved). Approving a style asset is not "
                        "Canon approval and does not write Canon."
                    ),
                    "status": guide.status,
                    "is_canon_approval": False,
                    "writes_canon": False,
                },
            )
        self._require_guide_written(guide)
        before = guide.to_audit_dict()
        now = _utc_now_z()
        previous = self._current_approved(
            project_id, lineage_id=guide.lineage_id, exclude_id=guide.id
        )
        guide.status = GUIDE_APPROVED
        guide.approved_at = now
        guide.approved_by = trigger.actor_id or guide.created_by
        self._repo.save_guide(guide)
        self._write_audit(
            actor=trigger,
            action="style_guide.approve",
            resource_type="style_guide",
            resource_id=guide.id,
            before_json=before,
            after_json=guide.to_audit_dict(),
        )
        if previous is not None:
            prev_before = previous.to_audit_dict()
            previous.status = GUIDE_SUPERSEDED
            previous.superseded_by_id = guide.id
            self._repo.save_guide(previous)
            self._write_audit(
                actor=Actor(actor_type=SYSTEM, actor_id="style"),
                action="style_guide.supersede",
                resource_type="style_guide",
                resource_id=previous.id,
                before_json=prev_before,
                after_json=previous.to_audit_dict(),
            )
        return guide

    def revise_guide(
        self,
        project_id: str,
        guide_id: str,
        actor: Actor,
        payload: dict[str, Any] | None = None,
    ) -> StyleGuide:
        trigger = self._require_human(actor, action="revise", resource="Style Guide")
        source = self._get_guide(project_id, guide_id)
        if source.status != GUIDE_APPROVED:
            raise StyleServiceError(
                409,
                {
                    "error": "invalid_style_guide_transition",
                    "message": (
                        "Only an Approved Style Guide may open the next "
                        "revision. The approved row stays frozen; the new "
                        "revision has a new id."
                    ),
                    "status": source.status,
                },
            )
        inflight = [
            item
            for item in self._repo.list_guides_for_lineage(source.lineage_id)
            if item.status == GUIDE_DRAFT
        ]
        if inflight:
            raise StyleServiceError(
                409,
                {
                    "error": "style_guide_revision_in_flight",
                    "message": (
                        "A Draft Style Guide already exists on this lineage. "
                        "Finish, cancel, or approve it before opening another."
                    ),
                    "existing_id": inflight[0].id,
                    "status": inflight[0].status,
                },
            )
        fields = _copy_guide_fields(source)
        if payload:
            fields.update(self._parse_guide_fields(payload, partial=True))
        new_guide = StyleGuide(
            id=str(uuid4()),
            project_id=project_id,
            lineage_id=source.lineage_id,
            parent_revision_id=source.id,
            revision=self._repo.next_guide_revision(source.lineage_id),
            status=GUIDE_DRAFT,
            created_at=_utc_now_z(),
            created_by=trigger.actor_id or source.created_by,
            actor_type=trigger.actor_type,
            **fields,
        )
        self._repo.add_guide(new_guide)
        self._write_audit(
            actor=trigger,
            action="style_guide.revise",
            resource_type="style_guide",
            resource_id=new_guide.id,
            before_json=source.to_audit_dict(),
            after_json=new_guide.to_audit_dict(),
        )
        return new_guide

    def cancel_guide(self, project_id: str, guide_id: str, actor: Actor) -> StyleGuide:
        trigger = self._require_human(actor, action="cancel", resource="Style Guide")
        guide = self._get_guide(project_id, guide_id)
        if guide.status == GUIDE_CANCELLED:
            return guide
        if guide.status not in GUIDE_CANCEL_FROM_STATES:
            raise StyleServiceError(
                409,
                {
                    "error": "invalid_style_guide_transition",
                    "message": (
                        "This Style Guide cannot be cancelled from its current "
                        "state. Failure / cancel keep the record; Approved "
                        "stays until superseded."
                    ),
                    "status": guide.status,
                },
            )
        before = guide.to_audit_dict()
        guide.status = GUIDE_CANCELLED
        self._repo.save_guide(guide)
        self._write_audit(
            actor=trigger,
            action="style_guide.cancel",
            resource_type="style_guide",
            resource_id=guide.id,
            before_json=before,
            after_json=guide.to_audit_dict(),
        )
        return guide

    def fail_guide(
        self,
        project_id: str,
        guide_id: str,
        actor: Actor,
        reason: str | None = None,
    ) -> StyleGuide:
        trigger = self._require_system(actor)
        guide = self._get_guide(project_id, guide_id)
        if guide.status == GUIDE_FAILED:
            return guide
        if guide.status not in GUIDE_FAIL_FROM_STATES:
            raise StyleServiceError(
                409,
                {
                    "error": "invalid_style_guide_transition",
                    "message": (
                        "Only a Draft Style Guide may fail. The record is kept."
                    ),
                    "status": guide.status,
                },
            )
        before = guide.to_audit_dict()
        guide.status = GUIDE_FAILED
        guide.failure_reason = reason or "save_or_draft_failed"
        self._repo.save_guide(guide)
        self._write_audit(
            actor=trigger,
            action="style_guide.failed",
            resource_type="style_guide",
            resource_id=guide.id,
            before_json=before,
            after_json=guide.to_audit_dict(),
        )
        return guide

    def get_guide(self, project_id: str, guide_id: str) -> StyleGuide:
        return self._get_guide(project_id, guide_id)

    def list_guides(self, project_id: str) -> list[StyleGuide]:
        self._require_project(project_id)
        return self._repo.list_guides(project_id)

    def create_sample(
        self,
        *,
        project_id: str,
        actor: Actor,
        payload: dict[str, Any] | None = None,
        created_by: str | None = None,
    ) -> StyleSample:
        self._require_project(project_id)
        trigger = self._require_human(actor, action="create", resource="Style Sample")
        created_by_value = _require_created_by(created_by, trigger)
        fields = self._parse_sample_fields(payload or {})
        now = _utc_now_z()
        status = SAMPLE_DRAFT
        failure_reason = None
        if getattr(self._repo, "force_fail", False):
            status = SAMPLE_FAILED
            failure_reason = "forced_draft_fail"
        sample = StyleSample(
            id=str(uuid4()),
            project_id=project_id,
            lineage_id=str(uuid4()),
            revision=1,
            status=status,
            created_at=now,
            created_by=created_by_value,
            actor_type=trigger.actor_type,
            failure_reason=failure_reason,
            **fields,
        )
        self._repo.add_sample(sample)
        self._write_audit(
            actor=trigger,
            action=(
                "style_sample.failed"
                if status == SAMPLE_FAILED
                else "style_sample.create"
            ),
            resource_type="style_sample",
            resource_id=sample.id,
            before_json=None,
            after_json=sample.to_audit_dict(),
        )
        return sample

    def patch_sample(
        self,
        *,
        project_id: str,
        sample_id: str,
        actor: Actor,
        payload: dict[str, Any] | None = None,
    ) -> StyleSample:
        trigger = self._require_human(actor, action="edit", resource="Style Sample")
        sample = self._get_sample(project_id, sample_id)
        if sample.status == SAMPLE_AUTHORIZED:
            raise StyleServiceError(
                409,
                {
                    "error": "authorized_not_editable_in_place",
                    "message": (
                        "An authorized Style Sample cannot be edited in place. "
                        "Changes must POST .../revise to open a new revision / "
                        "new id. Authorizing a sample is not Canon approval."
                    ),
                    "status": sample.status,
                    "writes_canon": False,
                    "is_canon_approval": False,
                },
            )
        if sample.status not in SAMPLE_EDITABLE_STATES:
            raise StyleServiceError(
                409,
                {
                    "error": "style_sample_not_editable",
                    "message": (
                        "PATCH is allowed only on a Draft Style Sample. "
                        "Authorized rows are frozen."
                    ),
                    "status": sample.status,
                },
            )
        before = sample.to_audit_dict()
        if getattr(self._repo, "force_fail", False):
            sample.status = SAMPLE_FAILED
            sample.failure_reason = "forced_save_fail"
            self._repo.save_sample(sample)
            self._write_audit(
                actor=trigger,
                action="style_sample.failed",
                resource_type="style_sample",
                resource_id=sample.id,
                before_json=before,
                after_json=sample.to_audit_dict(),
            )
            return sample
        if payload:
            fields = self._parse_sample_fields(payload, partial=True)
            for key, value in fields.items():
                setattr(sample, key, value)
        self._repo.save_sample(sample)
        self._write_audit(
            actor=trigger,
            action="style_sample.patch",
            resource_type="style_sample",
            resource_id=sample.id,
            before_json=before,
            after_json=sample.to_audit_dict(),
        )
        return sample

    def authorize_sample(
        self, project_id: str, sample_id: str, actor: Actor
    ) -> StyleSample:
        trigger = self._require_human(
            actor, action="authorize", resource="Style Sample"
        )
        sample = self._get_sample(project_id, sample_id)
        if sample.status != SAMPLE_DRAFT:
            raise StyleServiceError(
                409,
                {
                    "error": "invalid_style_sample_transition",
                    "message": (
                        "Only a Draft Style Sample may be authorized "
                        "(Draft → Authorized). Authorizing a sample is not "
                        "Canon approval and does not write Canon."
                    ),
                    "status": sample.status,
                    "is_canon_approval": False,
                    "writes_canon": False,
                },
            )
        self._require_sample_written(sample)
        before = sample.to_audit_dict()
        now = _utc_now_z()
        previous = self._current_authorized(
            project_id, lineage_id=sample.lineage_id, exclude_id=sample.id
        )
        sample.status = SAMPLE_AUTHORIZED
        sample.authorized_at = now
        sample.authorized_by = trigger.actor_id or sample.created_by
        self._repo.save_sample(sample)
        self._write_audit(
            actor=trigger,
            action="style_sample.authorize",
            resource_type="style_sample",
            resource_id=sample.id,
            before_json=before,
            after_json=sample.to_audit_dict(),
        )
        if previous is not None:
            prev_before = previous.to_audit_dict()
            previous.status = SAMPLE_SUPERSEDED
            previous.superseded_by_id = sample.id
            self._repo.save_sample(previous)
            self._write_audit(
                actor=Actor(actor_type=SYSTEM, actor_id="style"),
                action="style_sample.supersede",
                resource_type="style_sample",
                resource_id=previous.id,
                before_json=prev_before,
                after_json=previous.to_audit_dict(),
            )
        return sample

    def revise_sample(
        self,
        project_id: str,
        sample_id: str,
        actor: Actor,
        payload: dict[str, Any] | None = None,
    ) -> StyleSample:
        trigger = self._require_human(actor, action="revise", resource="Style Sample")
        source = self._get_sample(project_id, sample_id)
        if source.status != SAMPLE_AUTHORIZED:
            raise StyleServiceError(
                409,
                {
                    "error": "invalid_style_sample_transition",
                    "message": (
                        "Only an Authorized Style Sample may open the next "
                        "revision. The authorized row stays frozen; the new "
                        "revision has a new id."
                    ),
                    "status": source.status,
                },
            )
        inflight = [
            item
            for item in self._repo.list_samples_for_lineage(source.lineage_id)
            if item.status == SAMPLE_DRAFT
        ]
        if inflight:
            raise StyleServiceError(
                409,
                {
                    "error": "style_sample_revision_in_flight",
                    "message": (
                        "A Draft Style Sample already exists on this lineage. "
                        "Finish, cancel, or authorize it before opening another."
                    ),
                    "existing_id": inflight[0].id,
                    "status": inflight[0].status,
                },
            )
        fields = _copy_sample_fields(source)
        if payload:
            fields.update(self._parse_sample_fields(payload, partial=True))
        new_sample = StyleSample(
            id=str(uuid4()),
            project_id=project_id,
            lineage_id=source.lineage_id,
            parent_revision_id=source.id,
            revision=self._repo.next_sample_revision(source.lineage_id),
            status=SAMPLE_DRAFT,
            created_at=_utc_now_z(),
            created_by=trigger.actor_id or source.created_by,
            actor_type=trigger.actor_type,
            **fields,
        )
        self._repo.add_sample(new_sample)
        self._write_audit(
            actor=trigger,
            action="style_sample.revise",
            resource_type="style_sample",
            resource_id=new_sample.id,
            before_json=source.to_audit_dict(),
            after_json=new_sample.to_audit_dict(),
        )
        return new_sample

    def cancel_sample(
        self, project_id: str, sample_id: str, actor: Actor
    ) -> StyleSample:
        trigger = self._require_human(actor, action="cancel", resource="Style Sample")
        sample = self._get_sample(project_id, sample_id)
        if sample.status == SAMPLE_CANCELLED:
            return sample
        if sample.status not in SAMPLE_CANCEL_FROM_STATES:
            raise StyleServiceError(
                409,
                {
                    "error": "invalid_style_sample_transition",
                    "message": (
                        "This Style Sample cannot be cancelled from its current "
                        "state. Failure / cancel keep the record; Authorized "
                        "stays until superseded."
                    ),
                    "status": sample.status,
                },
            )
        before = sample.to_audit_dict()
        sample.status = SAMPLE_CANCELLED
        self._repo.save_sample(sample)
        self._write_audit(
            actor=trigger,
            action="style_sample.cancel",
            resource_type="style_sample",
            resource_id=sample.id,
            before_json=before,
            after_json=sample.to_audit_dict(),
        )
        return sample

    def fail_sample(
        self,
        project_id: str,
        sample_id: str,
        actor: Actor,
        reason: str | None = None,
    ) -> StyleSample:
        trigger = self._require_system(actor)
        sample = self._get_sample(project_id, sample_id)
        if sample.status == SAMPLE_FAILED:
            return sample
        if sample.status not in SAMPLE_FAIL_FROM_STATES:
            raise StyleServiceError(
                409,
                {
                    "error": "invalid_style_sample_transition",
                    "message": (
                        "Only a Draft Style Sample may fail. The record is kept."
                    ),
                    "status": sample.status,
                },
            )
        before = sample.to_audit_dict()
        sample.status = SAMPLE_FAILED
        sample.failure_reason = reason or "save_or_draft_failed"
        self._repo.save_sample(sample)
        self._write_audit(
            actor=trigger,
            action="style_sample.failed",
            resource_type="style_sample",
            resource_id=sample.id,
            before_json=before,
            after_json=sample.to_audit_dict(),
        )
        return sample

    def get_sample(self, project_id: str, sample_id: str) -> StyleSample:
        return self._get_sample(project_id, sample_id)

    def list_samples(self, project_id: str) -> list[StyleSample]:
        self._require_project(project_id)
        return self._repo.list_samples(project_id)

    def associate_on_draft(
        self,
        *,
        project_id: str,
        scene_id: str,
        revision_id: str,
        actor: Actor,
        style_guide_revision_id: str | None,
        style_sample_ids: list[str] | None = None,
    ) -> SceneDraft:
        self._require_project(project_id)
        if self._drafts is None or self._scenes is None:
            raise StyleServiceError(500, {"error": "scene_draft_repository_missing"})
        scene = self._scenes.get_scene(scene_id)
        if scene is None or scene.project_id != project_id:
            raise StyleServiceError(404, {"error": "scene_not_found"})
        draft = self._drafts.get_draft(revision_id)
        if (
            draft is None
            or draft.project_id != project_id
            or draft.scene_id != scene.id
        ):
            raise StyleServiceError(404, {"error": "scene_draft_not_found"})
        resolved_guide: StyleGuide | None = None
        if style_guide_revision_id:
            resolved_guide = self.require_usable_guide(
                project_id, style_guide_revision_id
            )
        resolved_samples = [
            self.require_usable_sample(project_id, sample_id)
            for sample_id in (style_sample_ids or [])
        ]
        before = draft.to_audit_dict()
        draft.style_guide_revision_id = (
            resolved_guide.id if resolved_guide is not None else None
        )
        draft.style_sample_ids = [item.id for item in resolved_samples]
        self._drafts.save_draft(draft)
        self._write_audit(
            actor=actor if actor.actor_type else Actor(HUMAN_EDITOR, None),
            action="scene_draft.associate_style",
            resource_type="scene_draft",
            resource_id=draft.id,
            before_json=before,
            after_json=draft.to_audit_dict(),
        )
        return draft

    def require_usable_guide(self, project_id: str, guide_id: str) -> StyleGuide:
        guide = self._repo.get_guide(guide_id)
        if guide is None or guide.project_id != project_id:
            raise StyleServiceError(404, {"error": "style_guide_not_found"})
        if guide.status == GUIDE_SUPERSEDED:
            raise StyleServiceError(
                409,
                {
                    "error": "style_guide_version_mismatch",
                    "message": (
                        "This Style Guide revision is superseded. Use-style "
                        "may only cite the currently approved revision."
                    ),
                    "cited_id": guide.id,
                    "status": guide.status,
                    "superseded_by_id": guide.superseded_by_id,
                },
            )
        if guide.status != GUIDE_APPROVED:
            current = self._current_approved(
                project_id, lineage_id=guide.lineage_id, exclude_id=None
            )
            if current is not None and current.id != guide.id:
                raise StyleServiceError(
                    409,
                    {
                        "error": "style_guide_version_mismatch",
                        "message": (
                            "The cited Style Guide revision is not the "
                            "approved revision on this lineage."
                        ),
                        "cited_id": guide.id,
                        "cited_status": guide.status,
                        "approved_revision_id": current.id,
                    },
                )
            raise StyleServiceError(
                409,
                {
                    "error": "style_guide_unapproved",
                    "message": (
                        "Use-style may only reference an approved Style Guide. "
                        "Unapproved drafts cannot be cited."
                    ),
                    "cited_id": guide.id,
                    "status": guide.status,
                },
            )
        return guide

    def require_usable_sample(self, project_id: str, sample_id: str) -> StyleSample:
        sample = self._repo.get_sample(sample_id)
        if sample is None or sample.project_id != project_id:
            raise StyleServiceError(404, {"error": "style_sample_not_found"})
        if sample.status == SAMPLE_SUPERSEDED:
            raise StyleServiceError(
                409,
                {
                    "error": "style_sample_version_mismatch",
                    "message": (
                        "This Style Sample revision is superseded. Use-style "
                        "may only cite the currently authorized revision."
                    ),
                    "cited_id": sample.id,
                    "status": sample.status,
                    "superseded_by_id": sample.superseded_by_id,
                },
            )
        if sample.status != SAMPLE_AUTHORIZED:
            current = self._current_authorized(
                project_id, lineage_id=sample.lineage_id, exclude_id=None
            )
            if current is not None and current.id != sample.id:
                raise StyleServiceError(
                    409,
                    {
                        "error": "style_sample_version_mismatch",
                        "message": (
                            "The cited Style Sample revision is not the "
                            "authorized revision on this lineage."
                        ),
                        "cited_id": sample.id,
                        "cited_status": sample.status,
                        "authorized_revision_id": current.id,
                    },
                )
            raise StyleServiceError(
                409,
                {
                    "error": "style_sample_unauthorized",
                    "message": (
                        "Use-style may only reference an authorized Style "
                        "Sample. Unauthorized samples cannot be cited."
                    ),
                    "cited_id": sample.id,
                    "status": sample.status,
                },
            )
        return sample

    def _get_guide(self, project_id: str, guide_id: str) -> StyleGuide:
        self._require_project(project_id)
        guide = self._repo.get_guide(guide_id)
        if guide is None or guide.project_id != project_id:
            raise StyleServiceError(404, {"error": "style_guide_not_found"})
        return guide

    def _get_sample(self, project_id: str, sample_id: str) -> StyleSample:
        self._require_project(project_id)
        sample = self._repo.get_sample(sample_id)
        if sample is None or sample.project_id != project_id:
            raise StyleServiceError(404, {"error": "style_sample_not_found"})
        return sample

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise StyleServiceError(404, {"error": "project_not_found"})

    def _require_human(self, actor: Actor, *, action: str, resource: str) -> Actor:
        try:
            return require_human_editor(actor, action=action, resource=resource)
        except ActorError as exc:
            raise StyleServiceError(
                403,
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                    "actor_type": actor.actor_type or None,
                    "is_approval": False,
                    "is_canon_approval": False,
                    "writes_canon": False,
                },
            ) from exc

    def _require_system(self, actor: Actor) -> Actor:
        if actor.actor_type != SYSTEM:
            raise StyleServiceError(
                403,
                {
                    "error": "system_actor_required",
                    "message": (
                        "Draft → Failed is a system transition. Approve / "
                        "authorize remain human-only and are not Canon approval."
                    ),
                    "actor_type": actor.actor_type or None,
                },
            )
        return actor

    def _current_approved(
        self,
        project_id: str,
        *,
        lineage_id: str | None = None,
        exclude_id: str | None = None,
    ) -> StyleGuide | None:
        for item in self._repo.list_guides(project_id):
            if item.status != GUIDE_APPROVED:
                continue
            if lineage_id is not None and item.lineage_id != lineage_id:
                continue
            if exclude_id is not None and item.id == exclude_id:
                continue
            return item
        return None

    def _current_authorized(
        self,
        project_id: str,
        *,
        lineage_id: str | None = None,
        exclude_id: str | None = None,
    ) -> StyleSample | None:
        for item in self._repo.list_samples(project_id):
            if item.status != SAMPLE_AUTHORIZED:
                continue
            if lineage_id is not None and item.lineage_id != lineage_id:
                continue
            if exclude_id is not None and item.id == exclude_id:
                continue
            return item
        return None

    def _parse_guide_fields(
        self, raw: dict[str, Any], *, partial: bool = False
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise StyleServiceError(
                422,
                {
                    "error": "invalid_style_guide",
                    "message": "Style Guide payload must be an object.",
                },
            )
        parsed: dict[str, Any] = {}
        for field, aliases in GUIDE_FIELD_ALIASES.items():
            present = next((alias for alias in aliases if alias in raw), None)
            if present is None:
                if partial:
                    continue
                parsed[field] = [] if field in LIST_FIELDS else ""
                continue
            value = raw[present]
            if field in LIST_FIELDS:
                parsed[field] = _as_string_list(value, field)
            else:
                parsed[field] = _as_string(value, field)
        return parsed

    def _parse_sample_fields(
        self, raw: dict[str, Any], *, partial: bool = False
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise StyleServiceError(
                422,
                {
                    "error": "invalid_style_sample",
                    "message": "Style Sample payload must be an object.",
                },
            )
        mapping = {
            "source": ("source", "来源"),
            "copyright_mark": (
                "copyright_mark",
                "authorization_mark",
                "版权标记",
                "授权标记",
            ),
            "scope_of_use": ("scope_of_use", "使用范围"),
            "body": ("body", "sample_body", "sample_text", "正文"),
        }
        parsed: dict[str, Any] = {}
        for field, aliases in mapping.items():
            present = next((alias for alias in aliases if alias in raw), None)
            if present is None:
                if partial:
                    continue
                parsed[field] = ""
                continue
            parsed[field] = _as_string(raw[present], field)
        return parsed

    def _require_guide_written(self, guide: StyleGuide) -> None:
        missing: list[str] = []
        for field in GUIDE_REQUIRED_FIELDS:
            value = getattr(guide, field)
            if not value:
                missing.append(field)
        if missing:
            raise StyleServiceError(
                409,
                {
                    "error": "style_guide_not_written",
                    "message": (
                        "A Style Guide must include POV, 人称, 时态, 叙述距离, "
                        "语气, 节奏, 对话规则, 词汇偏好, 禁用表达, 正例, and "
                        "反例 before approve."
                    ),
                    "missing_fields": missing,
                },
            )

    def _require_sample_written(self, sample: StyleSample) -> None:
        missing: list[str] = []
        if not sample.source:
            missing.append("source")
        if not sample.copyright_mark:
            missing.append("copyright_mark")
        if not sample.scope_of_use:
            missing.append("scope_of_use")
        if not sample.body:
            missing.append("body")
        if missing:
            raise StyleServiceError(
                409,
                {
                    "error": "style_sample_not_written",
                    "message": (
                        "A Style Sample must include source, copyright / "
                        "authorization mark, scope of use, and sample body "
                        "before authorize."
                    ),
                    "missing_fields": missing,
                },
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
            actor_type=actor.actor_type or HUMAN_EDITOR,
            actor_id=actor.actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            correlation_id=get_request_id(),
        )


def _copy_guide_fields(guide: StyleGuide) -> dict[str, Any]:
    return {
        "pov": guide.pov,
        "person": guide.person,
        "tense": guide.tense,
        "narrative_distance": guide.narrative_distance,
        "tone": guide.tone,
        "rhythm": guide.rhythm,
        "dialogue_rules": list(guide.dialogue_rules),
        "vocabulary_preferences": list(guide.vocabulary_preferences),
        "forbidden_expressions": list(guide.forbidden_expressions),
        "positive_examples": list(guide.positive_examples),
        "negative_examples": list(guide.negative_examples),
    }


def _copy_sample_fields(sample: StyleSample) -> dict[str, Any]:
    return {
        "source": sample.source,
        "copyright_mark": sample.copyright_mark,
        "scope_of_use": sample.scope_of_use,
        "body": sample.body,
    }


def _as_string(value: Any, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise StyleServiceError(
            422,
            {
                "error": "invalid_style_field",
                "message": f"{field} must be a string.",
                "field": field,
            },
        )
    return value.strip()


def _as_string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise StyleServiceError(
            422,
            {
                "error": "invalid_style_field",
                "message": f"{field} must be a list of strings or a string.",
                "field": field,
            },
        )
    return [item.strip() for item in value if item.strip()]


def _require_created_by(created_by: Any, actor: Actor) -> str:
    if isinstance(created_by, str) and created_by.strip():
        return created_by.strip()
    if actor.actor_id:
        return actor.actor_id
    raise StyleServiceError(
        422,
        {
            "error": "created_by_required",
            "message": "created_by or X-Actor-Id is required (human 主编).",
        },
    )


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
