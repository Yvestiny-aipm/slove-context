"""Context Pack assemble / freeze / cancel (node 6.1).

Input: one scene, an approved Scene Card, a written / effective Story
Spec, and a frozen Canon Snapshot. Output validates against
contracts/context-pack.schema.json.

The assembler is deterministic: copy / filter Snapshot facts + Spec +
Card. No LLM. No Canon write. Freeze is not Approval. Re-assemble
creates a new id / revision and never overwrites a frozen pack.
Failure and cancel keep the row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.candidate_change.models import CandidateChange
from slove_context.candidate_change.repository import CandidateChangeRepository
from slove_context.canon.models import (
    SNAPSHOT_FROZEN,
    CanonFact,
    CanonSnapshot,
    Entity,
    EvidenceRecord,
)
from slove_context.canon.repository import CanonRepository
from slove_context.canon.service import CanonService, CanonServiceError
from slove_context.context_pack.assembler import assemble_pack_payload
from slove_context.context_pack.models import (
    PACK_ASSEMBLED,
    PACK_CANCELLABLE_STATES,
    PACK_CANCELLED,
    PACK_FAILED,
    PACK_FREEZABLE_STATES,
    PACK_FROZEN,
    PACK_PURPOSES,
    SCENE_CARD_APPROVED_STATUSES,
    SPEC_USABLE_STATUSES,
    ContextPack,
)
from slove_context.context_pack.repository import ContextPackRepository
from slove_context.context_pack.validate import (
    ContextPackSchemaError,
    validate_context_pack,
)
from slove_context.logging import get_request_id
from slove_context.scene.models import Scene
from slove_context.scene.service import SceneService, SceneServiceError
from slove_context.scene_draft.models import (
    DRAFT_EXTRACTED,
    DRAFT_GENERATED,
    SceneDraft,
)
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.scene_plan.models import ScenePlan
from slove_context.scene_plan.repository import ScenePlanRepository
from slove_context.story.actors import (
    GENERATION_AGENT,
    HUMAN_EDITOR,
    REVIEW_AGENT,
    SYSTEM,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.models import SPEC_DRAFT, StorySpecVersion
from slove_context.story.repository import StoryRepository

ALLOWED_ASSEMBLE_ACTORS = frozenset(
    {HUMAN_EDITOR, SYSTEM, GENERATION_AGENT, REVIEW_AGENT}
)
ALLOWED_FREEZE_ACTORS = frozenset({HUMAN_EDITOR, SYSTEM})


class ContextPackServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class ContextPackService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        scene_service: SceneService,
        canon_service: CanonService,
        canon_repository: CanonRepository,
        pack_repository: ContextPackRepository,
        audit_writer: AuditWriter,
        plan_repository: ScenePlanRepository | None = None,
        draft_repository: SceneDraftRepository | None = None,
        candidate_repository: CandidateChangeRepository | None = None,
    ) -> None:
        self._story = story_repository
        self._scenes = scene_service
        self._canon = canon_service
        self._canon_repo = canon_repository
        self._repo = pack_repository
        self._audit = audit_writer
        self._plans = plan_repository
        self._drafts = draft_repository
        self._candidates = candidate_repository

    def assemble(
        self,
        *,
        project_id: str,
        scene_id: str,
        snapshot_id: str,
        purpose: str,
        actor: Actor,
    ) -> ContextPack:
        self._require_project(project_id)
        trigger = _require_assemble_actor(actor)
        cleaned_purpose = _require_purpose(purpose)
        scene = self._require_approved_scene(project_id, scene_id)
        spec = self._require_usable_spec(project_id)
        snapshot = self._require_frozen_snapshot(project_id, snapshot_id)
        created_by = _pack_created_by(trigger, spec, project_id, self._story)
        now = _utc_now_z()
        pack_id = str(uuid4())
        revision = self._repo.next_revision(project_id, scene.id)

        if getattr(self._repo, "force_fail", False):
            failed = ContextPack(
                id=pack_id,
                project_id=project_id,
                scene_id=scene.id,
                scene_card_id=scene.scene_card_id,
                story_spec_id=spec.spec_id,
                snapshot_id=snapshot.id,
                purpose=cleaned_purpose,
                revision=revision,
                status=PACK_FAILED,
                created_at=now,
                created_by=created_by,
                actor_type=trigger.actor_type,
                payload={},
                scene_plan_id=None,
                failure_reason="forced_assemble_fail",
            )
            self._repo.add(failed)
            self._write_audit(
                actor=trigger,
                action="context_pack.failed",
                resource_type="context_pack",
                resource_id=failed.id,
                before_json=None,
                after_json=failed.to_audit_dict(),
            )
            return failed

        facts, entities, evidence = self._load_snapshot_inputs(project_id, snapshot)
        plan = self._current_plan(project_id, scene.id)
        draft = self._current_draft(project_id, scene.id)
        candidates = self._candidates_for_scene(project_id, scene.id)
        payload = assemble_pack_payload(
            pack_id=pack_id,
            project_id=project_id,
            created_at=now,
            created_by=created_by,
            purpose=cleaned_purpose,
            scene=scene,
            spec=spec,
            facts=facts,
            entities=entities,
            evidence=evidence,
            plan=plan,
            draft=draft,
            candidates=candidates,
        )
        pack = ContextPack(
            id=pack_id,
            project_id=project_id,
            scene_id=scene.id,
            scene_card_id=scene.scene_card_id,
            story_spec_id=spec.spec_id,
            snapshot_id=snapshot.id,
            purpose=cleaned_purpose,
            revision=revision,
            status=PACK_ASSEMBLED,
            created_at=now,
            created_by=created_by,
            actor_type=trigger.actor_type,
            payload=payload,
            scene_plan_id=plan.id if plan is not None else None,
        )
        try:
            validate_context_pack(payload)
        except ContextPackSchemaError as exc:
            pack.status = PACK_FAILED
            pack.failure_reason = "context_pack_schema_failed"
            pack.payload = {}
            self._repo.add(pack)
            self._write_audit(
                actor=trigger,
                action="context_pack.failed",
                resource_type="context_pack",
                resource_id=pack.id,
                before_json=None,
                after_json={
                    **pack.to_audit_dict(),
                    "schema_error_count": len(exc.errors),
                },
            )
            return pack

        self._repo.add(pack)
        self._write_audit(
            actor=trigger,
            action="context_pack.assemble",
            resource_type="context_pack",
            resource_id=pack.id,
            before_json=None,
            after_json=pack.to_audit_dict(),
        )
        return pack

    def freeze(self, project_id: str, pack_id: str, *, actor: Actor) -> ContextPack:
        self._require_project(project_id)
        freezer = _require_freeze_actor(actor)
        pack = self.get_pack(project_id, pack_id)
        if pack.status == PACK_FROZEN:
            raise ContextPackServiceError(
                409,
                {
                    "error": "pack_already_frozen",
                    "message": (
                        "A frozen Context Pack is immutable. "
                        "Re-assemble to create a new revision / id. "
                        "Freeze is not Canon approval."
                    ),
                    "status": pack.status,
                },
            )
        if pack.status not in PACK_FREEZABLE_STATES:
            raise ContextPackServiceError(
                409,
                {
                    "error": "pack_not_freezable",
                    "message": (
                        "Only an Assembled pack can be frozen. "
                        "Failed and Cancelled records are kept and "
                        "are not overwritten."
                    ),
                    "status": pack.status,
                },
            )
        before = pack.to_audit_dict()
        pack.status = PACK_FROZEN
        pack.frozen_at = _utc_now_z()
        self._repo.save(pack)
        self._write_audit(
            actor=freezer,
            action="context_pack.freeze",
            resource_type="context_pack",
            resource_id=pack.id,
            before_json=before,
            after_json=pack.to_audit_dict(),
        )
        return pack

    def cancel(self, project_id: str, pack_id: str, *, actor: Actor) -> ContextPack:
        try:
            editor = require_human_editor(
                actor, action="cancel", resource="Context Pack"
            )
        except ActorError as exc:
            raise ContextPackServiceError(
                403,
                {
                    "error": "actor_not_allowed",
                    "message": str(exc),
                },
            ) from exc
        pack = self.get_pack(project_id, pack_id)
        if pack.status not in PACK_CANCELLABLE_STATES:
            raise ContextPackServiceError(
                409,
                {
                    "error": "pack_not_cancellable",
                    "message": (
                        "Cancel only applies to Assembled packs. "
                        "Frozen / Failed / Cancelled records are kept "
                        "and are not deleted."
                    ),
                    "status": pack.status,
                },
            )
        before = pack.to_audit_dict()
        pack.status = PACK_CANCELLED
        self._repo.save(pack)
        self._write_audit(
            actor=editor,
            action="context_pack.cancel",
            resource_type="context_pack",
            resource_id=pack.id,
            before_json=before,
            after_json=pack.to_audit_dict(),
        )
        return pack

    def get_pack(self, project_id: str, pack_id: str) -> ContextPack:
        self._require_project(project_id)
        pack = self._repo.get(pack_id)
        if pack is None or pack.project_id != project_id:
            raise ContextPackServiceError(404, {"error": "context_pack_not_found"})
        return pack

    def list_packs(self, project_id: str, scene_id: str) -> list[ContextPack]:
        scene = self._require_scene(project_id, scene_id)
        return self._repo.list_for_scene(project_id, scene.id)

    def _require_approved_scene(self, project_id: str, scene_id: str) -> Scene:
        scene = self._require_scene(project_id, scene_id)
        if scene.status not in SCENE_CARD_APPROVED_STATUSES:
            raise ContextPackServiceError(
                409,
                {
                    "error": "scene_card_not_approved",
                    "message": (
                        "Assemble requires an approved Scene Card for "
                        "this scene. A missing or draft card cannot "
                        "start a pack. Approving a card is not Canon "
                        "approval."
                    ),
                    "status": scene.status,
                },
            )
        return scene

    def _require_scene(self, project_id: str, scene_id: str) -> Scene:
        try:
            return self._scenes.get_scene(project_id, scene_id)
        except SceneServiceError as exc:
            raise ContextPackServiceError(exc.status_code, exc.detail) from exc

    def _require_usable_spec(self, project_id: str) -> StorySpecVersion:
        spec = self._story.get_spec_for_project(project_id)
        if spec is None:
            raise ContextPackServiceError(
                409,
                {
                    "error": "story_spec_required",
                    "message": (
                        "Assemble requires a written or effective Story "
                        "Spec. A missing spec cannot start a pack."
                    ),
                },
            )
        version = spec.current_version()
        if spec.status == SPEC_DRAFT or version.status not in SPEC_USABLE_STATUSES:
            raise ContextPackServiceError(
                409,
                {
                    "error": "story_spec_not_written",
                    "message": (
                        "Assemble requires a written or effective Story "
                        "Spec. A Draft spec cannot start a pack."
                    ),
                    "status": spec.status,
                },
            )
        return version

    def _require_frozen_snapshot(
        self, project_id: str, snapshot_id: str
    ) -> CanonSnapshot:
        cleaned = _clean_required(snapshot_id)
        if cleaned is None:
            raise ContextPackServiceError(
                422,
                {
                    "error": "snapshot_id_required",
                    "message": (
                        "Assemble requires a Canon Snapshot id. "
                        "canon_excerpts are read-only copies of that "
                        "Snapshot. The pack does not write Canon."
                    ),
                },
            )
        try:
            snapshot = self._canon.get_snapshot(project_id, cleaned)
        except CanonServiceError as exc:
            raise ContextPackServiceError(
                409,
                {
                    "error": "snapshot_required",
                    "message": (
                        "The specified Canon Snapshot is missing. "
                        "Assemble cannot use live Canon in place of a "
                        "Snapshot."
                    ),
                    "snapshot_id": cleaned,
                },
            ) from exc
        if snapshot.status != SNAPSHOT_FROZEN:
            raise ContextPackServiceError(
                409,
                {
                    "error": "snapshot_not_frozen",
                    "message": (
                        "The specified Canon Snapshot must be frozen "
                        "so the pack copies a read-only fact list. "
                        "An unfrozen Snapshot cannot start a pack."
                    ),
                    "snapshot_id": snapshot.id,
                    "status": snapshot.status,
                },
            )
        return snapshot

    def _load_snapshot_inputs(
        self, project_id: str, snapshot: CanonSnapshot
    ) -> tuple[list[CanonFact], dict[str, Entity], dict[str, EvidenceRecord]]:
        facts = self._canon.list_snapshot_facts(project_id, snapshot.id)
        entities = {item.id: item for item in self._canon.list_entities(project_id)}
        evidence: dict[str, EvidenceRecord] = {}
        for fact in facts:
            record = self._canon_repo.get_evidence(fact.evidence_id)
            if record is not None:
                evidence[record.id] = record
        return facts, entities, evidence

    def _current_plan(self, project_id: str, scene_id: str) -> ScenePlan | None:
        if self._plans is None:
            return None
        return self._plans.current_plan(project_id, scene_id)

    def _current_draft(self, project_id: str, scene_id: str) -> SceneDraft | None:
        if self._drafts is None:
            return None
        drafts = self._drafts.list_drafts(project_id, scene_id)
        for draft in drafts:
            if draft.status in {DRAFT_GENERATED, DRAFT_EXTRACTED}:
                return draft
        return None

    def _candidates_for_scene(
        self, project_id: str, scene_id: str
    ) -> list[CandidateChange]:
        if self._candidates is None:
            return []
        return self._candidates.list_candidates(project_id, scene_id)

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise ContextPackServiceError(404, {"error": "project_not_found"})

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


def _pack_created_by(
    actor: Actor,
    spec: StorySpecVersion,
    project_id: str,
    story: StoryRepository,
) -> str:
    if actor.actor_type == HUMAN_EDITOR and actor.actor_id:
        return actor.actor_id
    if spec.created_by:
        return spec.created_by
    project = story.get_project(project_id)
    if project is not None and project.created_by:
        return project.created_by
    return "主编"


def _require_assemble_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or SYSTEM
    if actor_type not in ALLOWED_ASSEMBLE_ACTORS:
        raise ContextPackServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Context Pack assemble may be triggered by the "
                    "human 主编, the system assembler, a generation "
                    "agent, or a review agent. This is not Approval "
                    "and not a Canon write."
                ),
                "actor_type": actor_type,
            },
        )
    return Actor(actor_type=actor_type, actor_id=actor.actor_id)


def _require_freeze_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or SYSTEM
    if actor_type not in ALLOWED_FREEZE_ACTORS:
        raise ContextPackServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "A Context Pack may be frozen by the human 主编 "
                    "or the system assembler. Freeze is not Canon "
                    "approval and does not write Canon."
                ),
                "actor_type": actor_type,
            },
        )
    return Actor(actor_type=actor_type, actor_id=actor.actor_id)


def _require_purpose(purpose: str) -> str:
    cleaned = purpose.strip() if purpose else ""
    if cleaned not in PACK_PURPOSES:
        raise ContextPackServiceError(
            422,
            {
                "error": "invalid_purpose",
                "message": (
                    "Context Pack purpose must be Generate or Validate. "
                    "There is no chapter-level or book-level pack, "
                    "and purpose is not Approval."
                ),
                "purpose": cleaned,
            },
        )
    return cleaned


def _clean_required(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
