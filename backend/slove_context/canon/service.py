"""Canon write path (node 2.2).

Facts are append-only. Corrections supersede the old fact and create a
new version. In-place edits of an Active fact body are forbidden.
Create / approve / abandon write audit_events. Only the human 主编 may
approve, abandon, or supersede. No auto-approval. Evidence is not Canon.
Snapshot freeze / replay is node 2.3 and is not implemented here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.canon.models import (
    FACT_ABANDONED,
    FACT_ACTIVE,
    FACT_NOT_IN_CANON,
    FACT_SUPERSEDED,
    NOT_YET_ACTIVE,
    CanonFact,
    CanonFactVersion,
    Entity,
    EvidenceRecord,
)
from slove_context.canon.repository import CanonRepository
from slove_context.canon.validate import (
    CanonValidationError,
    reject_create_as_active,
    require_entity_type,
    require_nonempty_str,
    require_source_type,
    require_uuid,
    require_value_json,
)
from slove_context.logging import get_request_id
from slove_context.story.actors import (
    HUMAN_EDITOR,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.repository import StoryRepository


class CanonServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class CanonService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        canon_repository: CanonRepository,
        audit_writer: AuditWriter,
    ) -> None:
        self._story = story_repository
        self._repo = canon_repository
        self._audit = audit_writer

    def create_entity(
        self,
        *,
        project_id: str,
        name: Any,
        entity_type: Any,
        actor: Actor,
        created_by: Any = None,
    ) -> Entity:
        self._require_project(project_id)
        try:
            cleaned_name = require_nonempty_str(name, "name")
            cleaned_type = require_entity_type(entity_type)
        except CanonValidationError as exc:
            raise CanonServiceError(
                422, {"error": exc.error, "message": exc.message}
            ) from exc
        if self._repo.find_entity(project_id, cleaned_type, cleaned_name) is not None:
            raise CanonServiceError(
                409,
                {
                    "error": "entity_already_exists",
                    "message": "An entity with this type and name already exists.",
                },
            )
        created_by_value = _require_created_by(created_by, actor)
        entity = Entity(
            id=str(uuid4()),
            project_id=project_id,
            entity_type=cleaned_type,
            name=cleaned_name,
            created_at=_utc_now_z(),
            created_by=created_by_value,
        )
        self._repo.add_entity(entity)
        self._write_audit(
            actor=actor,
            action="entity.create",
            resource_type="entity",
            resource_id=entity.id,
            before_json=None,
            after_json=entity.to_public_dict(),
        )
        return entity

    def list_entities(self, project_id: str) -> list[Entity]:
        self._require_project(project_id)
        return sorted(self._repo.list_entities(project_id), key=lambda item: item.name)

    def create_evidence(
        self,
        *,
        project_id: str,
        source_type: Any,
        quote: Any,
        actor: Actor,
        scene_id: Any = None,
        created_by: Any = None,
    ) -> EvidenceRecord:
        self._require_project(project_id)
        try:
            cleaned_source = require_source_type(source_type)
            cleaned_quote = require_nonempty_str(quote, "quote")
            if isinstance(scene_id, str) and not scene_id.strip():
                scene_id = None
            cleaned_scene = (
                require_uuid(scene_id, "scene_id") if scene_id is not None else None
            )
        except CanonValidationError as exc:
            raise CanonServiceError(
                422, {"error": exc.error, "message": exc.message}
            ) from exc
        created_by_value = _require_created_by(created_by, actor)
        evidence = EvidenceRecord(
            id=str(uuid4()),
            project_id=project_id,
            source_type=cleaned_source,
            quote=cleaned_quote,
            scene_id=cleaned_scene,
            created_at=_utc_now_z(),
            created_by=created_by_value,
        )
        self._repo.add_evidence(evidence)
        self._write_audit(
            actor=actor,
            action="evidence.create",
            resource_type="evidence",
            resource_id=evidence.id,
            before_json=None,
            after_json=evidence.to_audit_dict(),
        )
        return evidence

    def create_fact(
        self,
        *,
        project_id: str,
        payload: dict[str, Any],
        actor: Actor,
    ) -> CanonFact:
        self._require_project(project_id)
        try:
            reject_create_as_active(payload.get("status"))
            fields = self._require_fact_fields(project_id, payload)
        except CanonValidationError as exc:
            raise CanonServiceError(
                422, {"error": exc.error, "message": exc.message}
            ) from exc
        created_by_value = _require_created_by(payload.get("created_by"), actor)
        fact = self._new_fact(
            project_id=project_id,
            fields=fields,
            status=FACT_NOT_IN_CANON,
            created_by=created_by_value,
            supersedes_fact_id=None,
        )
        self._repo.add_fact(fact)
        self._write_audit(
            actor=actor,
            action="canon_fact.create",
            resource_type="canon_fact",
            resource_id=fact.id,
            before_json=None,
            after_json=fact.to_audit_dict(),
        )
        return fact

    def list_facts_in_effect(
        self,
        *,
        project_id: str,
        entity_id: str | None = None,
        predicate: str | None = None,
        as_of_story_time: str | None = None,
    ) -> list[CanonFact]:
        self._require_project(project_id)
        cleaned_entity = entity_id.strip() if isinstance(entity_id, str) else None
        cleaned_predicate = predicate.strip() if isinstance(predicate, str) else None
        cleaned_as_of = (
            as_of_story_time.strip() if isinstance(as_of_story_time, str) else None
        )
        if cleaned_entity == "":
            cleaned_entity = None
        if cleaned_predicate == "":
            cleaned_predicate = None
        if cleaned_as_of == "":
            cleaned_as_of = None
        results: list[CanonFact] = []
        for fact in self._repo.list_facts(project_id):
            if fact.status != FACT_ACTIVE:
                continue
            if cleaned_entity is not None and fact.entity_id != cleaned_entity:
                continue
            if cleaned_predicate is not None and fact.predicate != cleaned_predicate:
                continue
            if cleaned_as_of is not None and not _story_time_in_effect(
                fact.effective_story_time, cleaned_as_of
            ):
                continue
            results.append(fact)
        return sorted(
            results,
            key=lambda item: (item.effective_story_time, item.predicate, item.id),
        )

    def approve_fact(self, project_id: str, fact_id: str, actor: Actor) -> CanonFact:
        self._require_human(actor, action="approve")
        fact = self._get_fact(project_id, fact_id)
        if fact.status == FACT_ACTIVE:
            raise CanonServiceError(
                409,
                {
                    "error": "fact_already_active",
                    "message": "This Canon Fact is already Active.",
                    "status": fact.status,
                },
            )
        if fact.status not in NOT_YET_ACTIVE:
            raise CanonServiceError(
                409,
                {
                    "error": "invalid_fact_transition",
                    "message": (
                        "Only a not-yet-active Canon Fact (NotInCanon / Failed / "
                        "Rework) can be approved to Active. Active facts are "
                        "corrected by supersede, not by another approve."
                    ),
                    "status": fact.status,
                },
            )
        before = fact.to_audit_dict()
        fact.status = FACT_ACTIVE
        fact.current_version().status = FACT_ACTIVE
        self._repo.save_fact(fact)
        self._write_audit(
            actor=actor,
            action="canon_fact.approve",
            resource_type="canon_fact",
            resource_id=fact.id,
            before_json=before,
            after_json=fact.to_audit_dict(),
        )
        return fact

    def abandon_fact(self, project_id: str, fact_id: str, actor: Actor) -> CanonFact:
        self._require_human(actor, action="abandon")
        fact = self._get_fact(project_id, fact_id)
        if fact.status == FACT_ABANDONED:
            raise CanonServiceError(
                409,
                {
                    "error": "fact_already_abandoned",
                    "message": "This Canon Fact is already Abandoned.",
                    "status": fact.status,
                },
            )
        if fact.status not in NOT_YET_ACTIVE:
            raise CanonServiceError(
                409,
                {
                    "error": "active_fact_cannot_be_abandoned",
                    "message": (
                        "An Active Canon Fact cannot be abandoned. "
                        "Corrections must supersede (old Active → Superseded, "
                        "new fact Active). Records are not deleted."
                    ),
                    "status": fact.status,
                },
            )
        before = fact.to_audit_dict()
        fact.status = FACT_ABANDONED
        fact.current_version().status = FACT_ABANDONED
        self._repo.save_fact(fact)
        self._write_audit(
            actor=actor,
            action="canon_fact.abandon",
            resource_type="canon_fact",
            resource_id=fact.id,
            before_json=before,
            after_json=fact.to_audit_dict(),
        )
        return fact

    def supersede_fact(
        self,
        *,
        project_id: str,
        fact_id: str,
        payload: dict[str, Any],
        actor: Actor,
    ) -> dict[str, CanonFact]:
        self._require_human(actor, action="supersede")
        old = self._get_fact(project_id, fact_id)
        if old.status != FACT_ACTIVE:
            raise CanonServiceError(
                409,
                {
                    "error": "supersede_requires_active_fact",
                    "message": (
                        "Only an Active Canon Fact can be superseded. "
                        "Not-yet-active facts are abandoned, not superseded."
                    ),
                    "status": old.status,
                },
            )
        merged = {
            "entity_id": payload.get("entity_id") or old.entity_id,
            "predicate": payload.get("predicate") or old.predicate,
            "value_json": payload.get("value_json"),
            "effective_story_time": payload.get("effective_story_time"),
            "valid_from_scene_id": payload.get("valid_from_scene_id"),
            "source_type": payload.get("source_type"),
            "evidence_id": payload.get("evidence_id"),
        }
        try:
            reject_create_as_active(payload.get("status"))
            fields = self._require_fact_fields(project_id, merged)
        except CanonValidationError as exc:
            raise CanonServiceError(
                422, {"error": exc.error, "message": exc.message}
            ) from exc
        created_by_value = _require_created_by(payload.get("created_by"), actor)
        before = old.to_audit_dict()
        new_fact = self._new_fact(
            project_id=project_id,
            fields=fields,
            status=FACT_ACTIVE,
            created_by=created_by_value,
            supersedes_fact_id=old.id,
        )
        old.status = FACT_SUPERSEDED
        old.superseded_by_fact_id = new_fact.id
        self._repo.save_fact(old)
        self._repo.add_fact(new_fact)
        self._write_audit(
            actor=actor,
            action="canon_fact.supersede",
            resource_type="canon_fact",
            resource_id=old.id,
            before_json=before,
            after_json={
                **old.to_audit_dict(),
                "replacement_fact_id": new_fact.id,
            },
        )
        self._write_audit(
            actor=actor,
            action="canon_fact.create",
            resource_type="canon_fact",
            resource_id=new_fact.id,
            before_json=None,
            after_json=new_fact.to_audit_dict(),
        )
        return {"old": old, "new": new_fact}

    def _new_fact(
        self,
        *,
        project_id: str,
        fields: dict[str, Any],
        status: str,
        created_by: str,
        supersedes_fact_id: str | None,
    ) -> CanonFact:
        created_at = _utc_now_z()
        fact_id = str(uuid4())
        version_id = str(uuid4())
        version = CanonFactVersion(
            id=version_id,
            fact_id=fact_id,
            revision_number=1,
            entity_id=fields["entity_id"],
            predicate=fields["predicate"],
            value_json=fields["value_json"],
            effective_story_time=fields["effective_story_time"],
            valid_from_scene_id=fields["valid_from_scene_id"],
            source_type=fields["source_type"],
            evidence_id=fields["evidence_id"],
            status=status,
            created_at=created_at,
            created_by=created_by,
        )
        return CanonFact(
            id=fact_id,
            project_id=project_id,
            entity_id=fields["entity_id"],
            predicate=fields["predicate"],
            value_json=fields["value_json"],
            effective_story_time=fields["effective_story_time"],
            valid_from_scene_id=fields["valid_from_scene_id"],
            status=status,
            source_type=fields["source_type"],
            evidence_id=fields["evidence_id"],
            current_version_id=version_id,
            created_at=created_at,
            created_by=created_by,
            supersedes_fact_id=supersedes_fact_id,
            versions=[version],
        )

    def _require_fact_fields(
        self, project_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        entity_id = require_uuid(payload.get("entity_id"), "entity_id")
        predicate = require_nonempty_str(payload.get("predicate"), "predicate")
        value_json = require_value_json(payload.get("value_json"))
        effective_story_time = require_nonempty_str(
            payload.get("effective_story_time"), "effective_story_time"
        )
        valid_from_scene_id = require_uuid(
            payload.get("valid_from_scene_id"), "valid_from_scene_id"
        )
        source_type = require_source_type(payload.get("source_type"))
        evidence_id = require_uuid(payload.get("evidence_id"), "evidence_id")
        entity = self._repo.get_entity(entity_id)
        if entity is None or entity.project_id != project_id:
            raise CanonServiceError(404, {"error": "entity_not_found"})
        evidence = self._repo.get_evidence(evidence_id)
        if evidence is None or evidence.project_id != project_id:
            raise CanonServiceError(404, {"error": "evidence_not_found"})
        return {
            "entity_id": entity_id,
            "predicate": predicate,
            "value_json": value_json,
            "effective_story_time": effective_story_time,
            "valid_from_scene_id": valid_from_scene_id,
            "source_type": source_type,
            "evidence_id": evidence_id,
        }

    def _get_fact(self, project_id: str, fact_id: str) -> CanonFact:
        self._require_project(project_id)
        fact = self._repo.get_fact(fact_id)
        if fact is None or fact.project_id != project_id:
            raise CanonServiceError(404, {"error": "canon_fact_not_found"})
        return fact

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise CanonServiceError(404, {"error": "project_not_found"})

    def _require_human(self, actor: Actor, *, action: str) -> None:
        try:
            require_human_editor(actor, action=action, resource="Canon Fact")
        except ActorError as exc:
            raise CanonServiceError(
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
        actor_type = actor.actor_type or HUMAN_EDITOR
        self._audit.write(
            actor_type=actor_type,
            actor_id=actor.actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            correlation_id=get_request_id(),
        )


def _require_created_by(created_by: Any, actor: Actor) -> str:
    if isinstance(created_by, str) and created_by.strip():
        return created_by.strip()
    if actor.actor_id:
        return actor.actor_id
    raise CanonServiceError(
        422,
        {
            "error": "created_by_required",
            "message": "created_by or X-Actor-Id is required (human 主编).",
        },
    )


def _story_time_in_effect(effective: str, as_of: str) -> bool:
    """A fact is in effect when its story time is at or before as_of.

    Story time is an opaque comparable string (node 0.4), not wall-clock time.
    """
    return effective <= as_of


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
