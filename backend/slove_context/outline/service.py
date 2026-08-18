"""Outline Revision write path (node 6.2).

Drafting → Proposed → Confirmed (confirm usable). Confirm is not
Approval and does not write Canon. Confirmed rows are immutable: a
structural change opens a new revision / new id (Revising → Proposed
→ Confirmed). The previous Confirmed becomes Superseded.

Only the human 主编 may Proposed → Confirmed. System / generation /
review agents cannot confirm. Outline is not a generation unit: this
module never starts Scene Plan / Scene Draft / extract jobs and never
exposes chapter- or book-level generate.

Writes go through AuditWriter. Failure and cancel keep the row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.logging import get_request_id
from slove_context.outline.models import (
    ALLOWED_CHILD_TYPES,
    CANCEL_FROM_STATES,
    EDITABLE_STATES,
    FAIL_FROM_STATES,
    NODE_REQUIRED_FIELDS,
    NODE_TYPE_ARC,
    NODE_TYPE_CHAPTER,
    NODE_TYPE_SCENE,
    NODE_TYPES,
    OUTLINE_CANCELLED,
    OUTLINE_CONFIRMED,
    OUTLINE_DRAFTING,
    OUTLINE_FAILED,
    OUTLINE_PROPOSED,
    OUTLINE_REVISING,
    OUTLINE_REWORK,
    OUTLINE_SUPERSEDED,
    PROPOSE_FROM_STATES,
    REWORK_FROM_STATES,
    OutlineNode,
    OutlineRevision,
)
from slove_context.outline.repository import OutlineRepository
from slove_context.scene.models import Chapter, Scene
from slove_context.scene.repository import SceneRepository
from slove_context.story.actors import (
    HUMAN_EDITOR,
    SYSTEM,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.repository import StoryRepository

IN_FLIGHT_STATES = frozenset(
    {OUTLINE_DRAFTING, OUTLINE_PROPOSED, OUTLINE_REVISING, OUTLINE_REWORK}
)


class OutlineServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class OutlineService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        scene_repository: SceneRepository,
        outline_repository: OutlineRepository,
        audit_writer: AuditWriter,
    ) -> None:
        self._story = story_repository
        self._scenes = scene_repository
        self._repo = outline_repository
        self._audit = audit_writer

    def create(
        self,
        *,
        project_id: str,
        actor: Actor,
        nodes: list[dict[str, Any]] | None = None,
        created_by: str | None = None,
    ) -> OutlineRevision:
        self._require_project(project_id)
        trigger = self._require_human(
            actor, action="create", resource="Outline Revision"
        )
        self._reject_second_in_flight(project_id)
        if self._current_confirmed(project_id) is not None:
            raise OutlineServiceError(
                409,
                {
                    "error": "use_revise_for_confirmed",
                    "message": (
                        "A Confirmed Outline Revision already exists. "
                        "Structural changes must POST .../revise to open a "
                        "new revision / new id. Confirmed rows are immutable."
                    ),
                },
            )
        created_by_value = _require_created_by(created_by, trigger)
        now = _utc_now_z()
        parsed = self._parse_nodes(project_id, nodes or [])
        lineage = self._existing_lineage_id(project_id) or str(uuid4())
        revision_number = self._repo.next_revision(lineage)
        status = OUTLINE_DRAFTING
        failure_reason = None
        if getattr(self._repo, "force_fail", False):
            status = OUTLINE_FAILED
            failure_reason = "forced_draft_fail"
        revision = OutlineRevision(
            id=str(uuid4()),
            project_id=project_id,
            lineage_id=lineage,
            revision=revision_number,
            status=status,
            created_at=now,
            created_by=created_by_value,
            actor_type=trigger.actor_type,
            nodes=parsed,
            failure_reason=failure_reason,
        )
        self._repo.add(revision)
        self._write_audit(
            actor=trigger,
            action=(
                "outline_revision.failed"
                if status == OUTLINE_FAILED
                else "outline_revision.create"
            ),
            before_json=None,
            after_json=revision.to_audit_dict(),
            resource_id=revision.id,
        )
        return revision

    def patch(
        self,
        *,
        project_id: str,
        revision_id: str,
        actor: Actor,
        nodes: list[dict[str, Any]] | None = None,
    ) -> OutlineRevision:
        trigger = self._require_human(actor, action="edit", resource="Outline Revision")
        revision = self._get(project_id, revision_id)
        if revision.status == OUTLINE_CONFIRMED:
            raise OutlineServiceError(
                409,
                {
                    "error": "confirmed_not_editable_in_place",
                    "message": (
                        "A Confirmed Outline Revision cannot be edited in "
                        "place. Structural changes must create a new "
                        "revision / new id (Revising → Proposed → Confirmed)."
                    ),
                    "status": revision.status,
                },
            )
        if revision.status not in EDITABLE_STATES:
            raise OutlineServiceError(
                409,
                {
                    "error": "outline_not_editable",
                    "message": (
                        "PATCH is allowed only in Drafting or Revising. "
                        "Confirmed rows are immutable."
                    ),
                    "status": revision.status,
                },
            )
        before = revision.to_audit_dict()
        if getattr(self._repo, "force_fail", False):
            revision.status = OUTLINE_FAILED
            revision.failure_reason = "forced_save_fail"
            self._repo.save(revision)
            self._write_audit(
                actor=trigger,
                action="outline_revision.failed",
                before_json=before,
                after_json=revision.to_audit_dict(),
                resource_id=revision.id,
            )
            return revision
        if nodes is not None:
            revision.nodes = self._parse_nodes(project_id, nodes)
        self._repo.save(revision)
        self._write_audit(
            actor=trigger,
            action="outline_revision.patch",
            before_json=before,
            after_json=revision.to_audit_dict(),
            resource_id=revision.id,
        )
        return revision

    def propose(
        self, project_id: str, revision_id: str, actor: Actor
    ) -> OutlineRevision:
        trigger = self._require_human(
            actor, action="propose", resource="Outline Revision"
        )
        revision = self._get(project_id, revision_id)
        if revision.status not in PROPOSE_FROM_STATES:
            raise OutlineServiceError(
                409,
                {
                    "error": "invalid_outline_transition",
                    "message": (
                        "Only Drafting or Revising may be proposed "
                        "(Drafting / Revising → Proposed)."
                    ),
                    "status": revision.status,
                },
            )
        self._require_written(revision)
        before = revision.to_audit_dict()
        revision.status = OUTLINE_PROPOSED
        self._repo.save(revision)
        self._write_audit(
            actor=trigger,
            action="outline_revision.propose",
            before_json=before,
            after_json=revision.to_audit_dict(),
            resource_id=revision.id,
        )
        return revision

    def confirm(
        self, project_id: str, revision_id: str, actor: Actor
    ) -> OutlineRevision:
        trigger = self._require_human(
            actor, action="confirm", resource="Outline Revision"
        )
        revision = self._get(project_id, revision_id)
        if revision.status != OUTLINE_PROPOSED:
            raise OutlineServiceError(
                409,
                {
                    "error": "invalid_outline_transition",
                    "message": (
                        "Only Proposed may be confirmed usable "
                        "(Proposed → Confirmed). Confirm usable is not "
                        "Approval and does not write Canon."
                    ),
                    "status": revision.status,
                    "is_approval": False,
                    "writes_canon": False,
                },
            )
        self._require_written(revision)
        before = revision.to_audit_dict()
        now = _utc_now_z()
        previous = self._current_confirmed(
            project_id, lineage_id=revision.lineage_id, exclude_id=revision.id
        )
        revision.status = OUTLINE_CONFIRMED
        revision.confirmed_at = now
        revision.confirmed_by = trigger.actor_id or revision.created_by
        self._repo.save(revision)
        self._write_audit(
            actor=trigger,
            action="outline_revision.confirm",
            before_json=before,
            after_json=revision.to_audit_dict(),
            resource_id=revision.id,
        )
        if previous is not None:
            prev_before = previous.to_audit_dict()
            previous.status = OUTLINE_SUPERSEDED
            previous.superseded_by_id = revision.id
            self._repo.save(previous)
            self._write_audit(
                actor=Actor(actor_type=SYSTEM, actor_id="outline"),
                action="outline_revision.supersede",
                before_json=prev_before,
                after_json=previous.to_audit_dict(),
                resource_id=previous.id,
            )
        return revision

    def revise(
        self,
        project_id: str,
        revision_id: str,
        actor: Actor,
        nodes: list[dict[str, Any]] | None = None,
    ) -> OutlineRevision:
        trigger = self._require_human(
            actor, action="revise", resource="Outline Revision"
        )
        source = self._get(project_id, revision_id)
        if source.status != OUTLINE_CONFIRMED:
            raise OutlineServiceError(
                409,
                {
                    "error": "invalid_outline_transition",
                    "message": (
                        "Only a Confirmed Outline Revision may open the "
                        "next revision (Confirmed → Revising). The Confirmed "
                        "row stays usable until the new revision is confirmed."
                    ),
                    "status": source.status,
                },
            )
        inflight = [
            item
            for item in self._repo.list_for_lineage(source.lineage_id)
            if item.status in IN_FLIGHT_STATES
        ]
        if inflight:
            raise OutlineServiceError(
                409,
                {
                    "error": "outline_revision_in_flight",
                    "message": (
                        "A Drafting / Proposed / Revising / Rework revision "
                        "already exists on this lineage. Finish or cancel it "
                        "before opening another."
                    ),
                    "existing_id": inflight[0].id,
                    "status": inflight[0].status,
                },
            )
        created_by_value = trigger.actor_id or source.created_by
        copied = (
            self._parse_nodes(project_id, nodes)
            if nodes is not None
            else _copy_nodes(source.nodes)
        )
        new_revision = OutlineRevision(
            id=str(uuid4()),
            project_id=project_id,
            lineage_id=source.lineage_id,
            parent_revision_id=source.id,
            revision=self._repo.next_revision(source.lineage_id),
            status=OUTLINE_REVISING,
            created_at=_utc_now_z(),
            created_by=created_by_value,
            actor_type=trigger.actor_type,
            nodes=copied,
        )
        self._repo.add(new_revision)
        self._write_audit(
            actor=trigger,
            action="outline_revision.revise",
            before_json=source.to_audit_dict(),
            after_json=new_revision.to_audit_dict(),
            resource_id=new_revision.id,
        )
        return new_revision

    def cancel(
        self, project_id: str, revision_id: str, actor: Actor
    ) -> OutlineRevision:
        trigger = self._require_human(
            actor, action="cancel", resource="Outline Revision"
        )
        revision = self._get(project_id, revision_id)
        if revision.status == OUTLINE_CANCELLED:
            return revision
        if revision.status not in CANCEL_FROM_STATES:
            raise OutlineServiceError(
                409,
                {
                    "error": "invalid_outline_transition",
                    "message": (
                        "This Outline Revision cannot be cancelled from its "
                        "current state. Failure / cancel keep the record; "
                        "Confirmed stays until superseded."
                    ),
                    "status": revision.status,
                },
            )
        before = revision.to_audit_dict()
        revision.status = OUTLINE_CANCELLED
        self._repo.save(revision)
        self._write_audit(
            actor=trigger,
            action="outline_revision.cancel",
            before_json=before,
            after_json=revision.to_audit_dict(),
            resource_id=revision.id,
        )
        return revision

    def fail(
        self,
        project_id: str,
        revision_id: str,
        actor: Actor,
        reason: str | None = None,
    ) -> OutlineRevision:
        trigger = self._require_system(actor)
        revision = self._get(project_id, revision_id)
        if revision.status == OUTLINE_FAILED:
            return revision
        if revision.status not in FAIL_FROM_STATES:
            raise OutlineServiceError(
                409,
                {
                    "error": "invalid_outline_transition",
                    "message": (
                        "Only Drafting or Revising may fail "
                        "(Drafting / Revising → Failed). The record is kept."
                    ),
                    "status": revision.status,
                },
            )
        before = revision.to_audit_dict()
        revision.status = OUTLINE_FAILED
        revision.failure_reason = reason or "save_or_draft_failed"
        self._repo.save(revision)
        self._write_audit(
            actor=trigger,
            action="outline_revision.failed",
            before_json=before,
            after_json=revision.to_audit_dict(),
            resource_id=revision.id,
        )
        return revision

    def rework(
        self, project_id: str, revision_id: str, actor: Actor
    ) -> OutlineRevision:
        trigger = self._require_human(
            actor, action="rework", resource="Outline Revision"
        )
        revision = self._get(project_id, revision_id)
        if revision.status == OUTLINE_REWORK:
            return revision
        if revision.status not in REWORK_FROM_STATES:
            raise OutlineServiceError(
                409,
                {
                    "error": "invalid_outline_transition",
                    "message": (
                        "Rework is allowed from Proposed, Failed, or Cancelled."
                    ),
                    "status": revision.status,
                },
            )
        before = revision.to_audit_dict()
        revision.status = OUTLINE_REWORK
        self._repo.save(revision)
        self._write_audit(
            actor=trigger,
            action="outline_revision.rework",
            before_json=before,
            after_json=revision.to_audit_dict(),
            resource_id=revision.id,
        )
        return revision

    def resume(
        self, project_id: str, revision_id: str, actor: Actor
    ) -> OutlineRevision:
        trigger = self._require_human(
            actor, action="resume", resource="Outline Revision"
        )
        revision = self._get(project_id, revision_id)
        if revision.status != OUTLINE_REWORK:
            raise OutlineServiceError(
                409,
                {
                    "error": "invalid_outline_transition",
                    "message": (
                        "Only Rework may resume. No Confirmed version → "
                        "Drafting; a Confirmed version exists → Revising."
                    ),
                    "status": revision.status,
                },
            )
        before = revision.to_audit_dict()
        has_confirmed = self._current_confirmed(
            project_id, lineage_id=revision.lineage_id, exclude_id=revision.id
        )
        revision.status = OUTLINE_REVISING if has_confirmed else OUTLINE_DRAFTING
        self._repo.save(revision)
        self._write_audit(
            actor=trigger,
            action="outline_revision.resume",
            before_json=before,
            after_json=revision.to_audit_dict(),
            resource_id=revision.id,
        )
        return revision

    def get_revision(self, project_id: str, revision_id: str) -> OutlineRevision:
        return self._get(project_id, revision_id)

    def list_revisions(self, project_id: str) -> list[OutlineRevision]:
        self._require_project(project_id)
        return self._repo.list_for_project(project_id)

    def _get(self, project_id: str, revision_id: str) -> OutlineRevision:
        self._require_project(project_id)
        revision = self._repo.get(revision_id)
        if revision is None or revision.project_id != project_id:
            raise OutlineServiceError(404, {"error": "outline_revision_not_found"})
        return revision

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise OutlineServiceError(404, {"error": "project_not_found"})

    def _require_human(self, actor: Actor, *, action: str, resource: str) -> Actor:
        try:
            return require_human_editor(actor, action=action, resource=resource)
        except ActorError as exc:
            raise OutlineServiceError(
                403,
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                    "actor_type": actor.actor_type or None,
                    "is_approval": False,
                    "writes_canon": False,
                },
            ) from exc

    def _require_system(self, actor: Actor) -> Actor:
        if actor.actor_type != SYSTEM:
            raise OutlineServiceError(
                403,
                {
                    "error": "system_actor_required",
                    "message": (
                        "Drafting / Revising → Failed is a system transition. "
                        "Confirm usable remains human-only and is not Approval."
                    ),
                    "actor_type": actor.actor_type or None,
                },
            )
        return actor

    def _reject_second_in_flight(self, project_id: str) -> None:
        existing = [
            item
            for item in self._repo.list_for_project(project_id)
            if item.status in IN_FLIGHT_STATES
        ]
        if not existing:
            return
        raise OutlineServiceError(
            409,
            {
                "error": "outline_revision_in_flight",
                "message": (
                    "Only one in-flight Outline Revision is allowed. "
                    "Finish, cancel, or resume the existing revision. "
                    "A second novel outline line is not MVP-normal."
                ),
                "existing_id": existing[0].id,
                "status": existing[0].status,
            },
        )

    def _existing_lineage_id(self, project_id: str) -> str | None:
        items = self._repo.list_for_project(project_id)
        if not items:
            return None
        return items[0].lineage_id

    def _current_confirmed(
        self,
        project_id: str,
        *,
        lineage_id: str | None = None,
        exclude_id: str | None = None,
    ) -> OutlineRevision | None:
        for item in self._repo.list_for_project(project_id):
            if item.status != OUTLINE_CONFIRMED:
                continue
            if lineage_id is not None and item.lineage_id != lineage_id:
                continue
            if exclude_id is not None and item.id == exclude_id:
                continue
            return item
        return None

    def _parse_nodes(
        self, project_id: str, raw_nodes: list[dict[str, Any]]
    ) -> list[OutlineNode]:
        if not isinstance(raw_nodes, list):
            raise OutlineServiceError(
                422,
                {
                    "error": "invalid_outline_nodes",
                    "message": "nodes must be a list of Arc / Chapter / Scene nodes.",
                },
            )
        return [
            self._parse_node(project_id, item, parent_type=None, index=index)
            for index, item in enumerate(raw_nodes)
        ]

    def _parse_node(
        self,
        project_id: str,
        raw: Any,
        *,
        parent_type: str | None,
        index: int,
    ) -> OutlineNode:
        if not isinstance(raw, dict):
            raise OutlineServiceError(
                422,
                {
                    "error": "invalid_outline_node",
                    "message": "Each outline node must be an object.",
                },
            )
        node_type = str(raw.get("node_type") or "").strip()
        if node_type not in NODE_TYPES:
            raise OutlineServiceError(
                422,
                {
                    "error": "invalid_outline_node_type",
                    "message": (
                        "node_type must be arc, chapter, or scene "
                        "(Story → Arc/Volume → Chapter → Scene)."
                    ),
                    "node_type": node_type or None,
                },
            )
        if parent_type is None and node_type != NODE_TYPE_ARC:
            raise OutlineServiceError(
                422,
                {
                    "error": "invalid_outline_hierarchy",
                    "message": "Root outline nodes must be arcs (卷或弧).",
                },
            )
        expected_child = ALLOWED_CHILD_TYPES.get(parent_type) if parent_type else None
        if parent_type is not None and expected_child != node_type:
            raise OutlineServiceError(
                422,
                {
                    "error": "invalid_outline_hierarchy",
                    "message": (
                        "Hierarchy is Story → Arc/Volume → Chapter → Scene. "
                        f"A {parent_type} node may only contain {expected_child} nodes."
                    ),
                    "parent_type": parent_type,
                    "node_type": node_type,
                },
            )
        title = str(raw.get("title") or "").strip()
        if not title:
            raise OutlineServiceError(
                422,
                {"error": "invalid_outline_node", "message": "title is required."},
            )
        sort_order = raw.get("sort_order", index + 1)
        if not isinstance(sort_order, int) or isinstance(sort_order, bool):
            raise OutlineServiceError(
                422,
                {
                    "error": "invalid_outline_node",
                    "message": "sort_order must be an integer.",
                },
            )
        constraints = _as_string_list(raw.get("constraints"))
        arc_id = _optional_str(raw.get("arc_id"))
        chapter_id = _optional_str(raw.get("chapter_id"))
        scene_id = _optional_str(raw.get("scene_id"))
        if node_type == NODE_TYPE_ARC and arc_id:
            self._require_arc(project_id, arc_id)
        if node_type == NODE_TYPE_CHAPTER and chapter_id:
            chapter = self._require_chapter(project_id, chapter_id)
            if arc_id and chapter.arc_id != arc_id:
                raise OutlineServiceError(
                    422,
                    {
                        "error": "chapter_arc_mismatch",
                        "message": "chapter_id does not belong to the parent arc.",
                    },
                )
        if node_type == NODE_TYPE_SCENE:
            if not scene_id:
                raise OutlineServiceError(
                    422,
                    {
                        "error": "scene_id_required",
                        "message": (
                            "Scene outline nodes must reference an existing "
                            "3.1 Scene. Outline does not recreate Scene Cards "
                            "or start generate jobs."
                        ),
                    },
                )
            scene = self._require_scene(project_id, scene_id)
            if chapter_id and scene.chapter_id != chapter_id:
                raise OutlineServiceError(
                    422,
                    {
                        "error": "scene_chapter_mismatch",
                        "message": "scene_id does not belong to the parent chapter.",
                    },
                )
        children_raw = raw.get("children") or []
        if node_type == NODE_TYPE_SCENE and children_raw:
            raise OutlineServiceError(
                422,
                {
                    "error": "invalid_outline_hierarchy",
                    "message": "Scene nodes cannot have children. Outline is not a generation unit.",
                },
            )
        children = [
            self._parse_node(
                project_id, child, parent_type=node_type, index=child_index
            )
            for child_index, child in enumerate(children_raw)
        ]
        return OutlineNode(
            id=_optional_str(raw.get("id")) or str(uuid4()),
            node_type=node_type,
            title=title,
            sort_order=sort_order,
            goal=str(raw.get("goal") or ""),
            conflict=str(raw.get("conflict") or ""),
            turning_point=str(raw.get("turning_point") or ""),
            start_state=str(raw.get("start_state") or ""),
            end_state=str(raw.get("end_state") or ""),
            constraints=constraints,
            arc_id=arc_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            children=children,
        )

    def _require_arc(self, project_id: str, arc_id: str) -> None:
        arc = self._scenes.get_arc(arc_id)
        if arc is None or arc.project_id != project_id:
            raise OutlineServiceError(
                422,
                {
                    "error": "arc_not_found",
                    "message": "arc_id must reference an existing 3.1 Arc in this project.",
                    "arc_id": arc_id,
                },
            )

    def _require_chapter(self, project_id: str, chapter_id: str) -> Chapter:
        chapter = self._scenes.get_chapter(chapter_id)
        if chapter is None or chapter.project_id != project_id:
            raise OutlineServiceError(
                422,
                {
                    "error": "chapter_not_found",
                    "message": (
                        "chapter_id must reference an existing 3.1 Chapter. "
                        "Outline does not create chapters as generation units."
                    ),
                    "chapter_id": chapter_id,
                },
            )
        return chapter

    def _require_scene(self, project_id: str, scene_id: str) -> Scene:
        scene = self._scenes.get_scene(scene_id)
        if scene is None or scene.project_id != project_id:
            raise OutlineServiceError(
                422,
                {
                    "error": "scene_not_found",
                    "message": (
                        "scene_id must reference an existing 3.1 Scene. "
                        "Outline does not recreate Scene Cards."
                    ),
                    "scene_id": scene_id,
                },
            )
        return scene

    def _require_written(self, revision: OutlineRevision) -> None:
        if not revision.nodes:
            raise OutlineServiceError(
                409,
                {
                    "error": "outline_not_written",
                    "message": (
                        "This Outline Revision is not yet written. "
                        "Add Arc → Chapter → Scene nodes with goal, conflict, "
                        "turning_point, start_state, end_state, and constraints."
                    ),
                },
            )
        missing = _incomplete_fields(revision.nodes)
        if missing:
            raise OutlineServiceError(
                409,
                {
                    "error": "outline_not_written",
                    "message": (
                        "Every outline node must include goal, conflict, "
                        "turning_point, start_state, end_state, and constraints "
                        "before propose / confirm."
                    ),
                    "incomplete_node_ids": missing,
                },
            )

    def _write_audit(
        self,
        *,
        actor: Actor,
        action: str,
        before_json: dict[str, Any] | None,
        after_json: dict[str, Any] | None,
        resource_id: str,
    ) -> None:
        self._audit.write(
            actor_type=actor.actor_type or HUMAN_EDITOR,
            actor_id=actor.actor_id,
            action=action,
            resource_type="outline_revision",
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            correlation_id=get_request_id(),
        )


def _copy_nodes(nodes: list[OutlineNode]) -> list[OutlineNode]:
    copied: list[OutlineNode] = []
    for node in nodes:
        copied.append(
            OutlineNode(
                id=str(uuid4()),
                node_type=node.node_type,
                title=node.title,
                sort_order=node.sort_order,
                goal=node.goal,
                conflict=node.conflict,
                turning_point=node.turning_point,
                start_state=node.start_state,
                end_state=node.end_state,
                constraints=list(node.constraints),
                arc_id=node.arc_id,
                chapter_id=node.chapter_id,
                scene_id=node.scene_id,
                children=_copy_nodes(node.children),
            )
        )
    return copied


def _incomplete_fields(nodes: list[OutlineNode]) -> list[str]:
    missing: list[str] = []
    for node in nodes:
        values = {
            "goal": node.goal,
            "conflict": node.conflict,
            "turning_point": node.turning_point,
            "start_state": node.start_state,
            "end_state": node.end_state,
            "constraints": node.constraints,
        }
        if any(not values[field] for field in NODE_REQUIRED_FIELDS):
            missing.append(node.id)
        missing.extend(_incomplete_fields(node.children))
    return missing


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise OutlineServiceError(
            422,
            {
                "error": "invalid_outline_node",
                "message": "constraints must be a list of strings.",
            },
        )
    return [item.strip() for item in value if item.strip()]


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _require_created_by(created_by: Any, actor: Actor) -> str:
    if isinstance(created_by, str) and created_by.strip():
        return created_by.strip()
    if actor.actor_id:
        return actor.actor_id
    raise OutlineServiceError(
        422,
        {
            "error": "created_by_required",
            "message": "created_by or X-Actor-Id is required (human 主编).",
        },
    )


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
