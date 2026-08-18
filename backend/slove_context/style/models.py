"""In-process Style Guide / Style Sample records (node 7.1).

A Style Guide is a versioned writing-style asset (POV, 人称, 时态,
叙述距离, 语气, 节奏, 对话规则, 词汇偏好, 禁用表达, 正例, 反例).
A Style Sample is a versioned excerpt with source, copyright /
authorization mark, scope of use, and approval status.

Approve / authorize is human-only, freezes the row, and is not Canon
approval. Changes after freeze create a new revision / new id.
Failure and cancel keep the row. No style scoring (7.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

GUIDE_DRAFT = "Draft"
GUIDE_APPROVED = "Approved"
GUIDE_SUPERSEDED = "Superseded"
GUIDE_FAILED = "Failed"
GUIDE_CANCELLED = "Cancelled"

GUIDE_STATES = frozenset(
    {
        GUIDE_DRAFT,
        GUIDE_APPROVED,
        GUIDE_SUPERSEDED,
        GUIDE_FAILED,
        GUIDE_CANCELLED,
    }
)
GUIDE_EDITABLE_STATES = frozenset({GUIDE_DRAFT})
GUIDE_IMMUTABLE_STATES = frozenset({GUIDE_APPROVED, GUIDE_SUPERSEDED})
GUIDE_CANCEL_FROM_STATES = frozenset({GUIDE_DRAFT, GUIDE_FAILED})
GUIDE_FAIL_FROM_STATES = frozenset({GUIDE_DRAFT})

SAMPLE_DRAFT = "Draft"
SAMPLE_AUTHORIZED = "Authorized"
SAMPLE_SUPERSEDED = "Superseded"
SAMPLE_FAILED = "Failed"
SAMPLE_CANCELLED = "Cancelled"

SAMPLE_STATES = frozenset(
    {
        SAMPLE_DRAFT,
        SAMPLE_AUTHORIZED,
        SAMPLE_SUPERSEDED,
        SAMPLE_FAILED,
        SAMPLE_CANCELLED,
    }
)
SAMPLE_EDITABLE_STATES = frozenset({SAMPLE_DRAFT})
SAMPLE_IMMUTABLE_STATES = frozenset({SAMPLE_AUTHORIZED, SAMPLE_SUPERSEDED})
SAMPLE_CANCEL_FROM_STATES = frozenset({SAMPLE_DRAFT, SAMPLE_FAILED})
SAMPLE_FAIL_FROM_STATES = frozenset({SAMPLE_DRAFT})

GUIDE_REQUIRED_FIELDS = (
    "pov",
    "person",
    "tense",
    "narrative_distance",
    "tone",
    "rhythm",
    "dialogue_rules",
    "vocabulary_preferences",
    "forbidden_expressions",
    "positive_examples",
    "negative_examples",
)

GUIDE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "pov": ("pov", "POV"),
    "person": ("person", "人称", "narrative_person"),
    "tense": ("tense", "时态"),
    "narrative_distance": ("narrative_distance", "叙述距离"),
    "tone": ("tone", "语气"),
    "rhythm": ("rhythm", "节奏"),
    "dialogue_rules": ("dialogue_rules", "对话规则"),
    "vocabulary_preferences": ("vocabulary_preferences", "词汇偏好"),
    "forbidden_expressions": ("forbidden_expressions", "禁用表达"),
    "positive_examples": ("positive_examples", "正例"),
    "negative_examples": ("negative_examples", "反例"),
}

LIST_FIELDS = frozenset(
    {
        "dialogue_rules",
        "vocabulary_preferences",
        "forbidden_expressions",
        "positive_examples",
        "negative_examples",
    }
)


@dataclass
class StyleGuide:
    id: str
    project_id: str
    lineage_id: str
    revision: int
    status: str
    created_at: str
    created_by: str
    actor_type: str
    pov: str = ""
    person: str = ""
    tense: str = ""
    narrative_distance: str = ""
    tone: str = ""
    rhythm: str = ""
    dialogue_rules: list[str] = field(default_factory=list)
    vocabulary_preferences: list[str] = field(default_factory=list)
    forbidden_expressions: list[str] = field(default_factory=list)
    positive_examples: list[str] = field(default_factory=list)
    negative_examples: list[str] = field(default_factory=list)
    parent_revision_id: str | None = None
    superseded_by_id: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None
    failure_reason: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        approved = self.status == GUIDE_APPROVED
        return {
            "id": self.id,
            "project_id": self.project_id,
            "lineage_id": self.lineage_id,
            "parent_revision_id": self.parent_revision_id,
            "superseded_by_id": self.superseded_by_id,
            "revision": self.revision,
            "status": self.status,
            "approval_status": self.status,
            "pov": self.pov,
            "POV": self.pov,
            "person": self.person,
            "人称": self.person,
            "tense": self.tense,
            "时态": self.tense,
            "narrative_distance": self.narrative_distance,
            "叙述距离": self.narrative_distance,
            "tone": self.tone,
            "语气": self.tone,
            "rhythm": self.rhythm,
            "节奏": self.rhythm,
            "dialogue_rules": list(self.dialogue_rules),
            "对话规则": list(self.dialogue_rules),
            "vocabulary_preferences": list(self.vocabulary_preferences),
            "词汇偏好": list(self.vocabulary_preferences),
            "forbidden_expressions": list(self.forbidden_expressions),
            "禁用表达": list(self.forbidden_expressions),
            "positive_examples": list(self.positive_examples),
            "正例": list(self.positive_examples),
            "negative_examples": list(self.negative_examples),
            "反例": list(self.negative_examples),
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "current": approved,
            "immutable": self.status in GUIDE_IMMUTABLE_STATES,
            "usable": approved,
            "is_canon": False,
            "is_approval": False,
            "is_canon_approval": False,
            "writes_canon": False,
            "auto_approved": False,
            "is_style_scoring": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        # Never persist 正例 / 反例 / example prose. Counts + ids only.
        return {
            "id": self.id,
            "project_id": self.project_id,
            "lineage_id": self.lineage_id,
            "parent_revision_id": self.parent_revision_id,
            "superseded_by_id": self.superseded_by_id,
            "revision": self.revision,
            "status": self.status,
            "pov": self.pov,
            "person": self.person,
            "tense": self.tense,
            "narrative_distance": self.narrative_distance,
            "tone": self.tone,
            "rhythm": self.rhythm,
            "dialogue_rule_count": len(self.dialogue_rules),
            "vocabulary_preference_count": len(self.vocabulary_preferences),
            "forbidden_expression_count": len(self.forbidden_expressions),
            "positive_example_count": len(self.positive_examples),
            "negative_example_count": len(self.negative_examples),
            "approved_at": self.approved_at,
            "failure_reason": self.failure_reason,
            "is_canon": False,
            "is_approval": False,
            "is_canon_approval": False,
            "writes_canon": False,
            "auto_approved": False,
            "is_style_scoring": False,
        }


@dataclass
class StyleSample:
    id: str
    project_id: str
    lineage_id: str
    revision: int
    status: str
    source: str
    copyright_mark: str
    scope_of_use: str
    created_at: str
    created_by: str
    actor_type: str
    body: str = ""
    parent_revision_id: str | None = None
    superseded_by_id: str | None = None
    authorized_at: str | None = None
    authorized_by: str | None = None
    failure_reason: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        authorized = self.status == SAMPLE_AUTHORIZED
        return {
            "id": self.id,
            "project_id": self.project_id,
            "lineage_id": self.lineage_id,
            "parent_revision_id": self.parent_revision_id,
            "superseded_by_id": self.superseded_by_id,
            "revision": self.revision,
            "status": self.status,
            "approval_status": self.status,
            "source": self.source,
            "copyright_mark": self.copyright_mark,
            "authorization_mark": self.copyright_mark,
            "scope_of_use": self.scope_of_use,
            "body": self.body,
            "authorized_at": self.authorized_at,
            "authorized_by": self.authorized_by,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "current": authorized,
            "immutable": self.status in SAMPLE_IMMUTABLE_STATES,
            "usable": authorized,
            "is_canon": False,
            "is_approval": False,
            "is_canon_approval": False,
            "writes_canon": False,
            "auto_approved": False,
            "is_style_scoring": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        # Never persist sample body. Source / marks / counts only.
        return {
            "id": self.id,
            "project_id": self.project_id,
            "lineage_id": self.lineage_id,
            "parent_revision_id": self.parent_revision_id,
            "superseded_by_id": self.superseded_by_id,
            "revision": self.revision,
            "status": self.status,
            "source": self.source,
            "copyright_mark": self.copyright_mark,
            "scope_of_use": self.scope_of_use,
            "body_character_count": len(self.body),
            "authorized_at": self.authorized_at,
            "failure_reason": self.failure_reason,
            "is_canon": False,
            "is_approval": False,
            "is_canon_approval": False,
            "writes_canon": False,
            "auto_approved": False,
            "is_style_scoring": False,
        }
