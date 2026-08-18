"""In-process Canon records (node 2.2 + 2.3).

Statuses match docs/state-machines.md §4 Canon Fact.
Entity types are generic (角色 / 地点 / 物品 / 组织 / 规则); this is not
a character or scene product. Evidence is not Canon.
Snapshot is a read-only copy at a moment; it does not replace current Canon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 0.3 Canon Fact: NotInCanon, Active, Superseded, Failed, Abandoned, Rework
FACT_NOT_IN_CANON = "NotInCanon"
FACT_ACTIVE = "Active"
FACT_SUPERSEDED = "Superseded"
FACT_FAILED = "Failed"
FACT_ABANDONED = "Abandoned"
FACT_REWORK = "Rework"

FACT_STATUSES = frozenset(
    {
        FACT_NOT_IN_CANON,
        FACT_ACTIVE,
        FACT_SUPERSEDED,
        FACT_FAILED,
        FACT_ABANDONED,
        FACT_REWORK,
    }
)

NOT_YET_ACTIVE = frozenset({FACT_NOT_IN_CANON, FACT_FAILED, FACT_REWORK})

ENTITY_CHARACTER = "character"
ENTITY_LOCATION = "location"
ENTITY_ITEM = "item"
ENTITY_ORGANIZATION = "organization"
ENTITY_WORLD_RULE = "world_rule"

ENTITY_TYPES = frozenset(
    {
        ENTITY_CHARACTER,
        ENTITY_LOCATION,
        ENTITY_ITEM,
        ENTITY_ORGANIZATION,
        ENTITY_WORLD_RULE,
    }
)

_ENTITY_ALIASES = {
    "character": ENTITY_CHARACTER,
    "角色": ENTITY_CHARACTER,
    "location": ENTITY_LOCATION,
    "地点": ENTITY_LOCATION,
    "item": ENTITY_ITEM,
    "物品": ENTITY_ITEM,
    "organization": ENTITY_ORGANIZATION,
    "组织": ENTITY_ORGANIZATION,
    "world_rule": ENTITY_WORLD_RULE,
    "rule": ENTITY_WORLD_RULE,
    "规则": ENTITY_WORLD_RULE,
    "世界规则": ENTITY_WORLD_RULE,
}

SOURCE_PROSE = "prose"
SOURCE_EDITOR = "editor"

SOURCE_TYPES = frozenset({SOURCE_PROSE, SOURCE_EDITOR})

SNAPSHOT_UNFROZEN = "unfrozen"
SNAPSHOT_FROZEN = "frozen"

SNAPSHOT_STATUSES = frozenset({SNAPSHOT_UNFROZEN, SNAPSHOT_FROZEN})

_SOURCE_ALIASES = {
    "prose": SOURCE_PROSE,
    "scene_draft": SOURCE_PROSE,
    "散文": SOURCE_PROSE,
    "场景草稿": SOURCE_PROSE,
    "editor": SOURCE_EDITOR,
    "story_spec": SOURCE_EDITOR,
    "主编": SOURCE_EDITOR,
    "规格": SOURCE_EDITOR,
    "故事规格": SOURCE_EDITOR,
}


def normalize_entity_type(raw: str) -> str | None:
    stripped = raw.strip()
    if not stripped:
        return None
    if stripped in _ENTITY_ALIASES:
        return _ENTITY_ALIASES[stripped]
    lowered = stripped.lower().replace("-", "_").replace(" ", "_")
    return _ENTITY_ALIASES.get(lowered)


def normalize_source_type(raw: str) -> str | None:
    stripped = raw.strip()
    if not stripped:
        return None
    if stripped in _SOURCE_ALIASES:
        return _SOURCE_ALIASES[stripped]
    lowered = stripped.lower().replace("-", "_").replace(" ", "_")
    return _SOURCE_ALIASES.get(lowered)


@dataclass
class Entity:
    id: str
    project_id: str
    entity_type: str
    name: str
    created_at: str
    created_by: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "entity_type": self.entity_type,
            "name": self.name,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }


@dataclass
class EvidenceRecord:
    """Prose or editor evidence. Evidence is not Canon."""

    id: str
    project_id: str
    source_type: str
    quote: str
    scene_id: str | None
    created_at: str
    created_by: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "source_type": self.source_type,
            "quote": self.quote,
            "scene_id": self.scene_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        """Audit payload without the quote (prose is not stored in audit)."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "source_type": self.source_type,
            "scene_id": self.scene_id,
        }


@dataclass
class CanonFactVersion:
    """Immutable copy of a fact's body. Never updated in place."""

    id: str
    fact_id: str
    revision_number: int
    entity_id: str
    predicate: str
    value_json: Any
    effective_story_time: str
    valid_from_scene_id: str
    source_type: str
    evidence_id: str
    status: str
    created_at: str
    created_by: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fact_id": self.fact_id,
            "revision_number": self.revision_number,
            "entity_id": self.entity_id,
            "predicate": self.predicate,
            "value_json": _copy_json(self.value_json),
            "effective_story_time": self.effective_story_time,
            "valid_from_scene_id": self.valid_from_scene_id,
            "source_type": self.source_type,
            "evidence_id": self.evidence_id,
            "status": self.status,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }


@dataclass
class CanonFact:
    id: str
    project_id: str
    entity_id: str
    predicate: str
    value_json: Any
    effective_story_time: str
    valid_from_scene_id: str
    status: str
    source_type: str
    evidence_id: str
    current_version_id: str
    created_at: str
    created_by: str
    supersedes_fact_id: str | None = None
    superseded_by_fact_id: str | None = None
    versions: list[CanonFactVersion] = field(default_factory=list)

    def current_version(self) -> CanonFactVersion:
        for version in self.versions:
            if version.id == self.current_version_id:
                return version
        raise KeyError(f"current version {self.current_version_id} missing")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "entity_id": self.entity_id,
            "predicate": self.predicate,
            "value_json": _copy_json(self.value_json),
            "effective_story_time": self.effective_story_time,
            "valid_from_scene_id": self.valid_from_scene_id,
            "status": self.status,
            "source_type": self.source_type,
            "evidence_id": self.evidence_id,
            "current_version_id": self.current_version_id,
            "supersedes_fact_id": self.supersedes_fact_id,
            "superseded_by_fact_id": self.superseded_by_fact_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "entity_id": self.entity_id,
            "predicate": self.predicate,
            "status": self.status,
            "source_type": self.source_type,
            "evidence_id": self.evidence_id,
            "effective_story_time": self.effective_story_time,
            "supersedes_fact_id": self.supersedes_fact_id,
            "superseded_by_fact_id": self.superseded_by_fact_id,
        }


@dataclass
class CanonSnapshot:
    """Read-only copy of Active Canon at a moment. Does not replace live Canon."""

    id: str
    project_id: str
    created_at: str
    created_by: str
    fact_ids: list[str]
    status: str
    as_of_scene_seq: int | None = None
    as_of_story_time: str | None = None
    frozen_at: str | None = None
    note: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "fact_ids": list(self.fact_ids),
            "status": self.status,
            "as_of_scene_seq": self.as_of_scene_seq,
            "as_of_story_time": self.as_of_story_time,
            "frozen_at": self.frozen_at,
            "note": self.note,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "status": self.status,
            "fact_ids": list(self.fact_ids),
            "as_of_scene_seq": self.as_of_scene_seq,
            "as_of_story_time": self.as_of_story_time,
            "frozen_at": self.frozen_at,
        }


def _copy_json(value: Any) -> Any:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value
