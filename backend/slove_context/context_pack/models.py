"""In-process Context Pack records (node 6.1).

A pack is assembled for exactly one scene. After freeze it is
immutable: re-assemble creates a new id / revision and never
overwrites a frozen row. The pack is not Canon and cannot approve
or submit. Purpose is only Generate or Validate.

States: Assembled / Frozen / Failed / Cancelled.
Failure and cancel keep the row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_SCHEMA_VERSION = "0.4.0"

PACK_ASSEMBLED = "Assembled"
PACK_FROZEN = "Frozen"
PACK_FAILED = "Failed"
PACK_CANCELLED = "Cancelled"

PACK_STATES = frozenset({PACK_ASSEMBLED, PACK_FROZEN, PACK_FAILED, PACK_CANCELLED})
PACK_CANCELLABLE_STATES = frozenset({PACK_ASSEMBLED})
PACK_FREEZABLE_STATES = frozenset({PACK_ASSEMBLED})

PURPOSE_GENERATE = "Generate"
PURPOSE_VALIDATE = "Validate"
PACK_PURPOSES = frozenset({PURPOSE_GENERATE, PURPOSE_VALIDATE})

SPEC_USABLE_STATUSES = frozenset({"Written", "Effective"})

SCENE_CARD_APPROVED_STATUSES = frozenset({"approved", "published"})

DRAFT_EXCERPT_MAX_CHARS = 80


@dataclass
class ContextPack:
    id: str
    project_id: str
    scene_id: str
    scene_card_id: str
    story_spec_id: str
    snapshot_id: str
    purpose: str
    revision: int
    status: str
    created_at: str
    created_by: str
    actor_type: str
    payload: dict[str, Any]
    scene_plan_id: str | None = None
    frozen_at: str | None = None
    failure_reason: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        frozen = self.status == PACK_FROZEN
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "scene_card_id": self.scene_card_id,
            "story_spec_id": self.story_spec_id,
            "snapshot_id": self.snapshot_id,
            "scene_plan_id": self.scene_plan_id,
            "purpose": self.purpose,
            "revision": self.revision,
            "status": self.status,
            "frozen": frozen,
            "immutable": frozen,
            "frozen_at": self.frozen_at,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "pack": dict(self.payload),
            "is_canon": False,
            "is_approved": False,
            "writes_canon": False,
            "auto_approved": False,
            "is_approval": False,
            "is_outline": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        # Never include prose, excerpt quotes, or Canon statements (1.3).
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "scene_card_id": self.scene_card_id,
            "story_spec_id": self.story_spec_id,
            "snapshot_id": self.snapshot_id,
            "scene_plan_id": self.scene_plan_id,
            "purpose": self.purpose,
            "revision": self.revision,
            "status": self.status,
            "frozen": self.status == PACK_FROZEN,
            "excerpt_count": _excerpt_count(self.payload),
            "candidate_count": _candidate_count(self.payload),
            "has_scene_draft_excerpt": "scene_draft_excerpt" in self.payload,
            "failure_reason": self.failure_reason,
            "is_canon": False,
            "writes_canon": False,
            "auto_approved": False,
            "is_approval": False,
            "is_outline": False,
        }


def _excerpt_count(payload: dict[str, Any]) -> int:
    excerpts = payload.get("canon_excerpts")
    if not isinstance(excerpts, list):
        return 0
    return len(excerpts)


def _candidate_count(payload: dict[str, Any]) -> int:
    ids = payload.get("candidate_change_ids")
    if not isinstance(ids, list):
        return 0
    return len(ids)
