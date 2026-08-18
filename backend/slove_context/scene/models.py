"""In-process Arc / Chapter / Scene / Scene Card records (node 3.1).

Scene Card payload validates against contracts/scene-card.schema.json.
Scene approval status is draft / approved / (optional) published.
0.3 Scene machine alignment for this node: Specified / CardReady.
Generatable is derived, not a stored generated-draft state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_SCHEMA_VERSION = "0.4.0"

# Scene Card human-approval status (node 3.1). Not Canon approval.
SCENE_DRAFT = "draft"
SCENE_APPROVED = "approved"
SCENE_PUBLISHED = "published"

SCENE_APPROVAL_STATUSES = frozenset({SCENE_DRAFT, SCENE_APPROVED, SCENE_PUBLISHED})
DEPENDENCY_SATISFYING_STATUSES = frozenset({SCENE_APPROVED, SCENE_PUBLISHED})

# 0.3 Scene machine (practical subset for 3.1; no Generating / DraftReady).
SCENE_SPECIFIED = "Specified"
SCENE_CARD_READY = "CardReady"
SCENE_MACHINE_STATUSES = frozenset({SCENE_SPECIFIED, SCENE_CARD_READY})

# Scene Card contract status (0.4). Written = 已编写. Not InUse (no generate).
CARD_WRITTEN = "Written"

SCENE_FIELD_ALIASES = {
    "appearing_entities": "present_entities",
    "forbidden_items": "forbidden",
    "time": "story_time",
    "in_story_order": "story_order",
}


@dataclass
class Arc:
    id: str
    project_id: str
    title: str
    sort_order: int
    created_at: str
    created_by: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "sort_order": self.sort_order,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "is_generation_unit": False,
        }


@dataclass
class Chapter:
    id: str
    project_id: str
    arc_id: str
    title: str
    sort_order: int
    created_at: str
    created_by: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "arc_id": self.arc_id,
            "title": self.title,
            "sort_order": self.sort_order,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "is_generation_unit": False,
        }


@dataclass
class Scene:
    id: str
    project_id: str
    chapter_id: str
    scene_card_id: str
    story_order: int
    status: str
    scene_status: str
    pov: str
    story_time: str
    location: str
    present_entities: list[str]
    starting_state: str
    goal: str
    conflict: str
    expected_end_state: str
    forbidden: list[str]
    knowledge_boundaries: list[str]
    generation_boundary: str
    scene_card: dict[str, Any]
    created_at: str
    created_by: str
    depends_on: list[str] = field(default_factory=list)

    def to_public_dict(self, *, generatable: bool) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "scene_card_id": self.scene_card_id,
            "story_order": self.story_order,
            "status": self.status,
            "scene_status": self.scene_status,
            "generatable": generatable,
            "pov": self.pov,
            "story_time": self.story_time,
            "location": self.location,
            "present_entities": list(self.present_entities),
            "appearing_entities": list(self.present_entities),
            "starting_state": self.starting_state,
            "goal": self.goal,
            "conflict": self.conflict,
            "expected_end_state": self.expected_end_state,
            "forbidden": list(self.forbidden),
            "knowledge_boundaries": list(self.knowledge_boundaries),
            "generation_boundary": self.generation_boundary,
            "scene_card": dict(self.scene_card),
            "depends_on": list(self.depends_on),
            "created_at": self.created_at,
            "created_by": self.created_by,
        }
