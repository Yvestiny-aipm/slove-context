"""Scene Card / order / dependency write path (node 3.1).

Writes go through AuditWriter. Approving a Scene Card never writes Canon.
Only the human 主编 can approve. Generatable is derived: approved or
published card, and every dependency scene is approved or published.
Cycles and in-story-order conflicts are rejected. This module does not
generate Scene Plan or Scene Draft; node 3.3 consumes is_generatable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from slove_context.audit import AuditWriter
from slove_context.logging import get_request_id
from slove_context.scene.models import (
    CARD_WRITTEN,
    DEFAULT_SCHEMA_VERSION,
    DEPENDENCY_SATISFYING_STATUSES,
    SCENE_APPROVED,
    SCENE_CARD_READY,
    SCENE_DRAFT,
    SCENE_FIELD_ALIASES,
    SCENE_PUBLISHED,
    Arc,
    Chapter,
    Scene,
)
from slove_context.scene.repository import SceneRepository
from slove_context.scene.validate import SceneCardSchemaError, validate_scene_card
from slove_context.story.actors import (
    HUMAN_EDITOR,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.repository import StoryRepository

SCENE_CARD_KEYS = (
    "location",
    "present_entities",
    "generation_boundary",
    "forbidden",
    "knowledge_boundaries",
)


class SceneServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class SceneService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        scene_repository: SceneRepository,
        audit_writer: AuditWriter,
    ) -> None:
        self._story = story_repository
        self._repo = scene_repository
        self._audit = audit_writer

    def create_arc(
        self,
        *,
        project_id: str,
        title: str,
        sort_order: int | None,
        actor: Actor,
        created_by: str | None = None,
        arc_id: str | None = None,
    ) -> Arc:
        self._require_project(project_id)
        cleaned_title = _require_nonempty(title, "title")
        order = _require_positive_int(
            sort_order if sort_order is not None else 1, "sort_order"
        )
        created_by_value = _require_created_by(created_by, actor)
        arc = Arc(
            id=arc_id or str(uuid4()),
            project_id=project_id,
            title=cleaned_title,
            sort_order=order,
            created_at=_utc_now_z(),
            created_by=created_by_value,
        )
        self._repo.add_arc(arc)
        self._write_audit(
            actor=actor,
            action="arc.create",
            resource_type="arc",
            resource_id=arc.id,
            before_json=None,
            after_json=arc.to_public_dict(),
        )
        return arc

    def create_chapter(
        self,
        *,
        project_id: str,
        arc_id: str,
        title: str,
        sort_order: int | None,
        actor: Actor,
        created_by: str | None = None,
        chapter_id: str | None = None,
    ) -> Chapter:
        self._require_project(project_id)
        arc = self._repo.get_arc(arc_id)
        if arc is None or arc.project_id != project_id:
            raise SceneServiceError(404, {"error": "arc_not_found"})
        cleaned_title = _require_nonempty(title, "title")
        order = _require_positive_int(
            sort_order if sort_order is not None else 1, "sort_order"
        )
        created_by_value = _require_created_by(created_by, actor)
        chapter = Chapter(
            id=chapter_id or str(uuid4()),
            project_id=project_id,
            arc_id=arc.id,
            title=cleaned_title,
            sort_order=order,
            created_at=_utc_now_z(),
            created_by=created_by_value,
        )
        self._repo.add_chapter(chapter)
        self._write_audit(
            actor=actor,
            action="chapter.create",
            resource_type="chapter",
            resource_id=chapter.id,
            before_json=None,
            after_json=chapter.to_public_dict(),
        )
        return chapter

    def create_scene(
        self,
        *,
        project_id: str,
        payload: dict[str, Any],
        actor: Actor,
    ) -> Scene:
        self._require_project(project_id)
        self._reject_unapproved_as_approved(payload, action="create")
        fields = _normalize_scene_fields(payload)
        chapter = self._require_chapter(project_id, fields.get("chapter_id"))
        story_order = _require_positive_int(fields.get("story_order"), "story_order")
        self._reject_duplicate_order(project_id, story_order, exclude_scene_id=None)
        created_at = _utc_now_z()
        created_by = _require_created_by(payload.get("created_by"), actor)
        scene_id = _optional_uuid(payload.get("id")) or str(uuid4())
        card_id = _optional_uuid(_nested_card(payload).get("id")) or str(uuid4())
        scene = self._build_scene(
            scene_id=scene_id,
            project_id=project_id,
            chapter_id=chapter.id,
            scene_card_id=card_id,
            story_order=story_order,
            status=SCENE_DRAFT,
            fields=fields,
            created_at=created_at,
            created_by=created_by,
            depends_on=[],
        )
        self._repo.add_scene(scene)
        self._write_audit(
            actor=actor,
            action="scene.create",
            resource_type="scene",
            resource_id=scene.id,
            before_json=None,
            after_json=_scene_audit_after(scene),
        )
        return scene

    def get_scene(self, project_id: str, scene_id: str) -> Scene:
        self._require_project(project_id)
        scene = self._repo.get_scene(scene_id)
        if scene is None or scene.project_id != project_id:
            raise SceneServiceError(404, {"error": "scene_not_found"})
        return scene

    def list_scenes(self, project_id: str) -> list[Scene]:
        self._require_project(project_id)
        scenes = self._repo.list_scenes(project_id)
        return sorted(scenes, key=lambda item: item.story_order)

    def list_generatable(self, project_id: str) -> list[Scene]:
        return [
            scene
            for scene in self.list_scenes(project_id)
            if self.is_generatable(scene)
        ]

    def is_generatable(self, scene: Scene) -> bool:
        if scene.status not in DEPENDENCY_SATISFYING_STATUSES:
            return False
        return all(
            self._dependency_satisfies(dep_id, project_id=scene.project_id)
            for dep_id in scene.depends_on
        )

    def unsatisfied_dependencies(self, scene: Scene) -> list[str]:
        """Scene ids that block generatable (node 3.1 derived flag)."""
        if scene.status not in DEPENDENCY_SATISFYING_STATUSES:
            return list(scene.depends_on)
        return [
            dep_id
            for dep_id in scene.depends_on
            if not self._dependency_satisfies(dep_id, project_id=scene.project_id)
        ]

    def patch_scene(
        self,
        *,
        project_id: str,
        scene_id: str,
        payload: dict[str, Any],
        actor: Actor,
    ) -> Scene:
        scene = self.get_scene(project_id, scene_id)
        if scene.status != SCENE_DRAFT:
            raise SceneServiceError(
                409,
                {
                    "error": "approved_scene_immutable",
                    "message": (
                        "An approved Scene Card cannot be modified in place. "
                        "PATCH is allowed only while the scene is draft. "
                        "Approving a Scene Card is not Canon approval."
                    ),
                    "status": scene.status,
                },
            )
        self._reject_unapproved_as_approved(payload, action="patch")
        before = _scene_audit_after(scene)
        merged = _merge_scene_patch(scene, payload)
        if "chapter_id" in payload:
            chapter = self._require_chapter(project_id, merged.get("chapter_id"))
            scene.chapter_id = chapter.id
        story_order = _require_positive_int(merged.get("story_order"), "story_order")
        self._reject_duplicate_order(project_id, story_order, exclude_scene_id=scene.id)
        scene.story_order = story_order
        scene.pov = _require_nonempty(merged.get("pov"), "pov")
        scene.story_time = _require_nonempty(merged.get("story_time"), "story_time")
        scene.starting_state = _require_nonempty(
            merged.get("starting_state"), "starting_state"
        )
        scene.goal = _require_nonempty(merged.get("goal"), "goal")
        scene.conflict = _require_nonempty(merged.get("conflict"), "conflict")
        scene.expected_end_state = _require_nonempty(
            merged.get("expected_end_state"), "expected_end_state"
        )
        scene.location = _require_nonempty(merged.get("location"), "location")
        scene.generation_boundary = _require_nonempty(
            merged.get("generation_boundary"), "generation_boundary"
        )
        scene.present_entities = _require_str_list(
            merged.get("present_entities"), "present_entities"
        )
        scene.forbidden = _require_str_list(merged.get("forbidden"), "forbidden")
        scene.knowledge_boundaries = _require_str_list(
            merged.get("knowledge_boundaries"), "knowledge_boundaries"
        )
        scene.scene_card = self._assemble_and_validate_card(
            scene_id=scene.id,
            project_id=project_id,
            card_id=scene.scene_card_id,
            created_at=scene.scene_card.get("created_at") or scene.created_at,
            created_by=scene.created_by,
            fields=_scene_as_payload(scene),
        )
        self._sync_card_fields(scene)
        self._reject_order_vs_dependencies(scene)
        self._repo.save_scene(scene)
        self._write_audit(
            actor=actor,
            action="scene.update_draft",
            resource_type="scene",
            resource_id=scene.id,
            before_json=before,
            after_json=_scene_audit_after(scene),
        )
        return scene

    def approve_scene(self, project_id: str, scene_id: str, actor: Actor) -> Scene:
        try:
            require_human_editor(actor, action="approve", resource="Scene Card")
        except ActorError as exc:
            raise SceneServiceError(
                403,
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                    "actor_type": actor.actor_type or None,
                },
            ) from exc
        scene = self.get_scene(project_id, scene_id)
        if scene.status in DEPENDENCY_SATISFYING_STATUSES:
            raise SceneServiceError(
                409,
                {
                    "error": "scene_already_approved",
                    "message": (
                        "Scene Card is already approved. "
                        "This is not Canon approval and does not write Canon."
                    ),
                    "status": scene.status,
                },
            )
        if scene.status != SCENE_DRAFT:
            raise SceneServiceError(
                409,
                {
                    "error": "unapproved_scene_cannot_be_frozen",
                    "message": (
                        "Only a draft Scene Card can be approved. "
                        "No auto-approval path exists. "
                        "Approving a Scene Card is not Canon approval."
                    ),
                    "status": scene.status,
                },
            )
        before = _scene_audit_after(scene)
        scene.status = SCENE_APPROVED
        self._repo.save_scene(scene)
        self._write_audit(
            actor=actor,
            action="scene.approve",
            resource_type="scene",
            resource_id=scene.id,
            before_json=before,
            after_json=_scene_audit_after(scene),
        )
        return scene

    def set_dependencies(
        self,
        *,
        project_id: str,
        scene_id: str,
        depends_on: list[str],
        actor: Actor,
    ) -> Scene:
        scene = self.get_scene(project_id, scene_id)
        before = _scene_audit_after(scene)
        cleaned = _unique_scene_ids(depends_on)
        if scene.id in cleaned:
            raise SceneServiceError(
                409,
                {
                    "error": "cycle_dependency",
                    "message": "A scene cannot depend on itself.",
                    "cycle": [scene.id],
                },
            )
        for dep_id in cleaned:
            dep = self._repo.get_scene(dep_id)
            if dep is None or dep.project_id != project_id:
                raise SceneServiceError(
                    404,
                    {"error": "dependency_scene_not_found", "scene_id": dep_id},
                )
        graph = self._dependency_graph(project_id)
        graph[scene.id] = set(cleaned)
        cycle = _find_cycle(graph)
        if cycle is not None:
            raise SceneServiceError(
                409,
                {
                    "error": "cycle_dependency",
                    "message": "Scene dependencies must be a DAG. Cycles are rejected.",
                    "cycle": cycle,
                },
            )
        scene.depends_on = cleaned
        self._reject_order_vs_dependencies(scene)
        self._repo.save_scene(scene)
        self._write_audit(
            actor=actor,
            action="scene.set_dependencies",
            resource_type="scene",
            resource_id=scene.id,
            before_json=before,
            after_json=_scene_audit_after(scene),
        )
        return scene

    def list_dependencies(self, project_id: str, scene_id: str) -> dict[str, Any]:
        scene = self.get_scene(project_id, scene_id)
        items: list[dict[str, Any]] = []
        for dep_id in scene.depends_on:
            dep = self._repo.get_scene(dep_id)
            if dep is None:
                items.append(
                    {
                        "id": dep_id,
                        "status": None,
                        "satisfies": False,
                    }
                )
                continue
            items.append(
                {
                    "id": dep.id,
                    "story_order": dep.story_order,
                    "status": dep.status,
                    "satisfies": dep.status in DEPENDENCY_SATISFYING_STATUSES,
                }
            )
        return {
            "scene_id": scene.id,
            "project_id": project_id,
            "depends_on": items,
            "generatable": self.is_generatable(scene),
        }

    def public_scene(self, scene: Scene) -> dict[str, Any]:
        return scene.to_public_dict(generatable=self.is_generatable(scene))

    def _build_scene(
        self,
        *,
        scene_id: str,
        project_id: str,
        chapter_id: str,
        scene_card_id: str,
        story_order: int,
        status: str,
        fields: dict[str, Any],
        created_at: str,
        created_by: str,
        depends_on: list[str],
    ) -> Scene:
        scene_card = self._assemble_and_validate_card(
            scene_id=scene_id,
            project_id=project_id,
            card_id=scene_card_id,
            created_at=created_at,
            created_by=created_by,
            fields=fields,
        )
        return Scene(
            id=scene_id,
            project_id=project_id,
            chapter_id=chapter_id,
            scene_card_id=scene_card_id,
            story_order=story_order,
            status=status,
            scene_status=SCENE_CARD_READY,
            pov=_require_nonempty(fields.get("pov"), "pov"),
            story_time=_require_nonempty(fields.get("story_time"), "story_time"),
            location=str(scene_card["location"]),
            present_entities=list(scene_card["present_entities"]),
            starting_state=_require_nonempty(
                fields.get("starting_state"), "starting_state"
            ),
            goal=_require_nonempty(fields.get("goal"), "goal"),
            conflict=_require_nonempty(fields.get("conflict"), "conflict"),
            expected_end_state=_require_nonempty(
                fields.get("expected_end_state"), "expected_end_state"
            ),
            forbidden=list(scene_card["forbidden"]),
            knowledge_boundaries=list(scene_card["knowledge_boundaries"]),
            generation_boundary=str(scene_card["generation_boundary"]),
            scene_card=scene_card,
            created_at=created_at,
            created_by=created_by,
            depends_on=list(depends_on),
        )

    def _assemble_and_validate_card(
        self,
        *,
        scene_id: str,
        project_id: str,
        card_id: str,
        created_at: str,
        created_by: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        assembled: dict[str, Any] = {
            "schema_version": fields.get("schema_version") or DEFAULT_SCHEMA_VERSION,
            "id": card_id,
            "project_id": project_id,
            "created_at": created_at if _looks_like_utc_z(created_at) else _utc_now_z(),
            "created_by": created_by,
            "scene_id": scene_id,
            "status": CARD_WRITTEN,
            "location": fields.get("location"),
            "present_entities": fields.get("present_entities"),
            "generation_boundary": fields.get("generation_boundary"),
            "forbidden": fields.get("forbidden")
            if fields.get("forbidden") is not None
            else [],
            "knowledge_boundaries": (
                fields.get("knowledge_boundaries")
                if fields.get("knowledge_boundaries") is not None
                else []
            ),
        }
        try:
            validate_scene_card(assembled)
        except SceneCardSchemaError as exc:
            raise SceneServiceError(
                422,
                {
                    "error": "scene_card_schema_invalid",
                    "message": "Scene Card failed contracts/scene-card.schema.json.",
                    "errors": exc.errors,
                },
            ) from exc
        return assembled

    def _sync_card_fields(self, scene: Scene) -> None:
        card = scene.scene_card
        scene.location = str(card["location"])
        scene.present_entities = list(card["present_entities"])
        scene.generation_boundary = str(card["generation_boundary"])
        scene.forbidden = list(card["forbidden"])
        scene.knowledge_boundaries = list(card["knowledge_boundaries"])

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise SceneServiceError(404, {"error": "project_not_found"})

    def _require_chapter(self, project_id: str, chapter_id: Any) -> Chapter:
        cleaned = _require_nonempty(chapter_id, "chapter_id")
        chapter = self._repo.get_chapter(cleaned)
        if chapter is None or chapter.project_id != project_id:
            raise SceneServiceError(404, {"error": "chapter_not_found"})
        return chapter

    def _reject_duplicate_order(
        self, project_id: str, story_order: int, *, exclude_scene_id: str | None
    ) -> None:
        existing = self._repo.find_scene_by_order(project_id, story_order)
        if existing is None:
            return
        if exclude_scene_id is not None and existing.id == exclude_scene_id:
            return
        raise SceneServiceError(
            409,
            {
                "error": "story_order_conflict",
                "message": (
                    "Two scenes cannot share the same in-story order "
                    "in one Story Project."
                ),
                "story_order": story_order,
                "existing_scene_id": existing.id,
            },
        )

    def _reject_order_vs_dependencies(self, scene: Scene) -> None:
        for dep_id in scene.depends_on:
            dep = self._repo.get_scene(dep_id)
            if dep is None:
                continue
            if scene.story_order <= dep.story_order:
                raise SceneServiceError(
                    409,
                    {
                        "error": "story_order_conflict",
                        "message": (
                            "A scene cannot be ordered at or before a "
                            "scene it depends on."
                        ),
                        "scene_id": scene.id,
                        "story_order": scene.story_order,
                        "depends_on_scene_id": dep.id,
                        "depends_on_story_order": dep.story_order,
                    },
                )
        for dependent in self._repo.scenes_depending_on(scene.id):
            if dependent.story_order <= scene.story_order:
                raise SceneServiceError(
                    409,
                    {
                        "error": "story_order_conflict",
                        "message": (
                            "A scene cannot be ordered at or after a "
                            "scene that depends on it."
                        ),
                        "scene_id": scene.id,
                        "story_order": scene.story_order,
                        "dependent_scene_id": dependent.id,
                        "dependent_story_order": dependent.story_order,
                    },
                )

    def _reject_unapproved_as_approved(
        self, payload: dict[str, Any], *, action: str
    ) -> None:
        status = payload.get("status")
        if status in (SCENE_APPROVED, SCENE_PUBLISHED):
            raise SceneServiceError(
                422,
                {
                    "error": "unapproved_scene_cannot_be_frozen",
                    "message": (
                        "An unapproved Scene Card cannot be created or edited "
                        f"as {status}. {action} always produces draft. "
                        "Only the human 主编 can later approve. "
                        "No auto-approval path exists. "
                        "Approving a Scene Card is not Canon approval."
                    ),
                    "status": status,
                },
            )

    def _dependency_satisfies(self, dep_id: str, *, project_id: str) -> bool:
        dep = self._repo.get_scene(dep_id)
        if dep is None or dep.project_id != project_id:
            return False
        return dep.status in DEPENDENCY_SATISFYING_STATUSES

    def _dependency_graph(self, project_id: str) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = {}
        for scene in self._repo.list_scenes(project_id):
            graph.setdefault(scene.id, set())
            graph[scene.id] = set(scene.depends_on)
            for dep_id in scene.depends_on:
                graph.setdefault(dep_id, set())
        return graph

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


def _normalize_scene_fields(payload: dict[str, Any]) -> dict[str, Any]:
    fields = dict(payload)
    nested = _nested_card(payload)
    for key in SCENE_CARD_KEYS:
        if key not in fields and key in nested:
            fields[key] = nested[key]
    for alias, canonical in SCENE_FIELD_ALIASES.items():
        if alias in fields and canonical not in fields:
            fields[canonical] = fields[alias]
        if alias in nested and canonical not in fields:
            fields[canonical] = nested[alias]
    return fields


def _nested_card(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("scene_card")
    return raw if isinstance(raw, dict) else {}


def _merge_scene_patch(scene: Scene, payload: dict[str, Any]) -> dict[str, Any]:
    merged = _scene_as_payload(scene)
    incoming = _normalize_scene_fields(payload)
    nested = _nested_card(payload)
    aliases_present = {
        SCENE_FIELD_ALIASES[alias]
        for alias in {*payload, *nested}
        if alias in SCENE_FIELD_ALIASES
    }
    patchable = {
        "chapter_id",
        "story_order",
        "pov",
        "story_time",
        "starting_state",
        "goal",
        "conflict",
        "expected_end_state",
        *SCENE_CARD_KEYS,
        "schema_version",
    }
    for key in patchable:
        if key in incoming and (
            key in payload or key in nested or key in aliases_present
        ):
            merged[key] = incoming[key]
    return merged


def _scene_as_payload(scene: Scene) -> dict[str, Any]:
    return {
        "chapter_id": scene.chapter_id,
        "story_order": scene.story_order,
        "pov": scene.pov,
        "story_time": scene.story_time,
        "starting_state": scene.starting_state,
        "goal": scene.goal,
        "conflict": scene.conflict,
        "expected_end_state": scene.expected_end_state,
        "location": scene.location,
        "present_entities": list(scene.present_entities),
        "generation_boundary": scene.generation_boundary,
        "forbidden": list(scene.forbidden),
        "knowledge_boundaries": list(scene.knowledge_boundaries),
        "schema_version": scene.scene_card.get("schema_version"),
    }


def _scene_audit_after(scene: Scene) -> dict[str, Any]:
    return {
        "id": scene.id,
        "project_id": scene.project_id,
        "status": scene.status,
        "scene_status": scene.scene_status,
        "story_order": scene.story_order,
        "depends_on": list(scene.depends_on),
    }


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}
    parent: dict[str, str | None] = {node: None for node in graph}

    def dfs(node: str) -> list[str] | None:
        color[node] = GRAY
        for nxt in graph.get(node, ()):
            if nxt not in color:
                color[nxt] = WHITE
                parent[nxt] = None
            if color[nxt] == GRAY:
                cycle = [nxt, node]
                current = node
                while current != nxt and parent.get(current) is not None:
                    current = parent[current]  # type: ignore[assignment]
                    cycle.append(current)
                cycle.reverse()
                return cycle
            if color[nxt] == WHITE:
                parent[nxt] = node
                found = dfs(nxt)
                if found is not None:
                    return found
        color[node] = BLACK
        return None

    for node in list(graph):
        if color[node] == WHITE:
            found = dfs(node)
            if found is not None:
                return found
    return None


def _unique_scene_ids(values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise SceneServiceError(
            422,
            {
                "error": "invalid_dependencies",
                "message": "depends_on must be a list of scene ids.",
            },
        )
    seen: list[str] = []
    for item in values:
        cleaned = _require_uuid(item, "depends_on")
        if cleaned not in seen:
            seen.append(cleaned)
    return seen


def _require_created_by(created_by: Any, actor: Actor) -> str:
    if isinstance(created_by, str) and created_by.strip():
        return created_by.strip()
    if actor.actor_id:
        return actor.actor_id
    raise SceneServiceError(
        422,
        {
            "error": "created_by_required",
            "message": "created_by or X-Actor-Id is required (human 主编).",
        },
    )


def _require_nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SceneServiceError(
            422,
            {
                "error": "invalid_field",
                "message": f"{field} is required and must be a non-empty string.",
                "field": field,
            },
        )
    return value.strip()


def _require_str_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise SceneServiceError(
            422,
            {
                "error": "invalid_field",
                "message": f"{field} must be a list of non-empty strings.",
                "field": field,
            },
        )
    return [item.strip() for item in value]


def _require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SceneServiceError(
            422,
            {
                "error": "invalid_field",
                "message": f"{field} must be a positive integer.",
                "field": field,
            },
        )
    return value


def _require_uuid(value: Any, field: str) -> str:
    text = _require_nonempty(value, field)
    try:
        return str(UUID(text))
    except ValueError as exc:
        raise SceneServiceError(
            422,
            {
                "error": "invalid_uuid",
                "message": f"{field} must be a UUID.",
                "field": field,
            },
        ) from exc


def _optional_uuid(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        try:
            return str(UUID(value.strip()))
        except ValueError:
            return None
    return None


def _looks_like_utc_z(value: str) -> bool:
    return value.endswith("Z") and "T" in value


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
