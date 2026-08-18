"""In-process Outline Revision records (node 6.2).

States follow docs/state-machines.md §7:
Drafting / Proposed / Confirmed / Revising / Failed / Cancelled /
Rework / Superseded.

Confirm usable is not Approval and does not write Canon.
Confirmed rows are immutable: structural change is a new revision /
new id. Failure and cancel keep the row. Outline is not a generation
unit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 0.3 Outline Revision states (ASCII names from §7.1).
OUTLINE_DRAFTING = "Drafting"
OUTLINE_PROPOSED = "Proposed"
OUTLINE_CONFIRMED = "Confirmed"
OUTLINE_REVISING = "Revising"
OUTLINE_FAILED = "Failed"
OUTLINE_CANCELLED = "Cancelled"
OUTLINE_REWORK = "Rework"
OUTLINE_SUPERSEDED = "Superseded"

OUTLINE_STATES = frozenset(
    {
        OUTLINE_DRAFTING,
        OUTLINE_PROPOSED,
        OUTLINE_CONFIRMED,
        OUTLINE_REVISING,
        OUTLINE_FAILED,
        OUTLINE_CANCELLED,
        OUTLINE_REWORK,
        OUTLINE_SUPERSEDED,
    }
)

EDITABLE_STATES = frozenset({OUTLINE_DRAFTING, OUTLINE_REVISING})
PROPOSE_FROM_STATES = frozenset({OUTLINE_DRAFTING, OUTLINE_REVISING})
CANCEL_FROM_STATES = frozenset(
    {
        OUTLINE_DRAFTING,
        OUTLINE_PROPOSED,
        OUTLINE_REVISING,
        OUTLINE_FAILED,
        OUTLINE_REWORK,
    }
)
FAIL_FROM_STATES = frozenset({OUTLINE_DRAFTING, OUTLINE_REVISING})
REWORK_FROM_STATES = frozenset({OUTLINE_PROPOSED, OUTLINE_FAILED, OUTLINE_CANCELLED})
IMMUTABLE_STATES = frozenset({OUTLINE_CONFIRMED, OUTLINE_SUPERSEDED})

NODE_TYPE_ARC = "arc"
NODE_TYPE_CHAPTER = "chapter"
NODE_TYPE_SCENE = "scene"
NODE_TYPES = frozenset({NODE_TYPE_ARC, NODE_TYPE_CHAPTER, NODE_TYPE_SCENE})

NODE_REQUIRED_FIELDS = (
    "goal",
    "conflict",
    "turning_point",
    "start_state",
    "end_state",
    "constraints",
)

ALLOWED_CHILD_TYPES = {
    NODE_TYPE_ARC: NODE_TYPE_CHAPTER,
    NODE_TYPE_CHAPTER: NODE_TYPE_SCENE,
    NODE_TYPE_SCENE: None,
}


@dataclass
class OutlineNode:
    """One Arc / Chapter / Scene node in an Outline Revision tree."""

    id: str
    node_type: str
    title: str
    sort_order: int
    goal: str
    conflict: str
    turning_point: str
    start_state: str
    end_state: str
    constraints: list[str]
    arc_id: str | None = None
    chapter_id: str | None = None
    scene_id: str | None = None
    children: list[OutlineNode] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "node_type": self.node_type,
            "title": self.title,
            "sort_order": self.sort_order,
            "goal": self.goal,
            "conflict": self.conflict,
            "turning_point": self.turning_point,
            "start_state": self.start_state,
            "end_state": self.end_state,
            "constraints": list(self.constraints),
            "children": [child.to_public_dict() for child in self.children],
            "is_generation_unit": False,
        }
        if self.arc_id is not None:
            payload["arc_id"] = self.arc_id
        if self.chapter_id is not None:
            payload["chapter_id"] = self.chapter_id
        if self.scene_id is not None:
            payload["scene_id"] = self.scene_id
        return payload


@dataclass
class OutlineRevision:
    id: str
    project_id: str
    lineage_id: str
    revision: int
    status: str
    created_at: str
    created_by: str
    actor_type: str
    nodes: list[OutlineNode] = field(default_factory=list)
    parent_revision_id: str | None = None
    superseded_by_id: str | None = None
    confirmed_at: str | None = None
    confirmed_by: str | None = None
    failure_reason: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        confirmed = self.status == OUTLINE_CONFIRMED
        return {
            "id": self.id,
            "project_id": self.project_id,
            "lineage_id": self.lineage_id,
            "parent_revision_id": self.parent_revision_id,
            "superseded_by_id": self.superseded_by_id,
            "revision": self.revision,
            "status": self.status,
            "nodes": [node.to_public_dict() for node in self.nodes],
            "confirmed_at": self.confirmed_at,
            "confirmed_by": self.confirmed_by,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "current": confirmed,
            "immutable": self.status in IMMUTABLE_STATES,
            "is_generation_unit": False,
            "is_canon": False,
            "is_approval": False,
            "is_canon_approval": False,
            "writes_canon": False,
            "auto_approved": False,
            "confirm_usable": confirmed,
            "is_outline": True,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        # Do not persist node prose (goal / conflict / turning point).
        return {
            "id": self.id,
            "project_id": self.project_id,
            "lineage_id": self.lineage_id,
            "parent_revision_id": self.parent_revision_id,
            "superseded_by_id": self.superseded_by_id,
            "revision": self.revision,
            "status": self.status,
            "node_count": _count_nodes(self.nodes),
            "scene_ref_count": _count_scene_refs(self.nodes),
            "confirmed_at": self.confirmed_at,
            "failure_reason": self.failure_reason,
            "is_generation_unit": False,
            "is_canon": False,
            "is_approval": False,
            "is_canon_approval": False,
            "writes_canon": False,
            "auto_approved": False,
            "confirm_usable": self.status == OUTLINE_CONFIRMED,
        }


def _count_nodes(nodes: list[OutlineNode]) -> int:
    total = 0
    for node in nodes:
        total += 1 + _count_nodes(node.children)
    return total


def _count_scene_refs(nodes: list[OutlineNode]) -> int:
    total = 0
    for node in nodes:
        if node.node_type == NODE_TYPE_SCENE and node.scene_id:
            total += 1
        total += _count_scene_refs(node.children)
    return total
