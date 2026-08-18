"""Deterministic Context Pack assembler (node 6.1).

Copies / filters an approved Scene Card, a written Story Spec, and
read-only facts from a frozen Canon Snapshot into one per-scene pack.
No LLM. No network. Does not write Canon.
"""

from __future__ import annotations

from typing import Any

from slove_context.candidate_change.models import CandidateChange
from slove_context.canon.models import CanonFact, Entity, EvidenceRecord
from slove_context.context_pack.models import (
    DEFAULT_SCHEMA_VERSION,
    DRAFT_EXCERPT_MAX_CHARS,
    PURPOSE_VALIDATE,
)
from slove_context.scene.models import Scene
from slove_context.scene_draft.models import SceneDraft
from slove_context.scene_plan.models import ScenePlan
from slove_context.story.models import StorySpecVersion


def assemble_pack_payload(
    *,
    pack_id: str,
    project_id: str,
    created_at: str,
    created_by: str,
    purpose: str,
    scene: Scene,
    spec: StorySpecVersion,
    facts: list[CanonFact],
    entities: dict[str, Entity],
    evidence: dict[str, EvidenceRecord],
    plan: ScenePlan | None = None,
    draft: SceneDraft | None = None,
    candidates: list[CandidateChange] | None = None,
) -> dict[str, Any]:
    """Build a schema-shaped Context Pack from frozen inputs.

    canon_excerpts are read-only copies of Snapshot facts. They are
    not a writable Canon block.
    """
    payload: dict[str, Any] = {
        "schema_version": DEFAULT_SCHEMA_VERSION,
        "id": pack_id,
        "project_id": project_id,
        "created_at": created_at,
        "created_by": created_by,
        "scene_id": scene.id,
        "purpose": purpose,
        "story_spec_id": spec.spec_id,
        "scene_card_id": scene.scene_card_id,
        "knowledge_boundaries": [item for item in scene.knowledge_boundaries if item],
        "canon_excerpts": _excerpts_from_snapshot(facts, entities, evidence),
    }
    if plan is not None:
        payload["scene_plan_id"] = plan.id
    excerpt = _draft_excerpt(draft)
    if excerpt is not None:
        payload["scene_draft_excerpt"] = excerpt
    if purpose == PURPOSE_VALIDATE:
        payload["candidate_change_ids"] = _candidate_ids(candidates)
    return payload


def _excerpts_from_snapshot(
    facts: list[CanonFact],
    entities: dict[str, Entity],
    evidence: dict[str, EvidenceRecord],
) -> list[dict[str, str]]:
    ordered = sorted(facts, key=lambda item: (item.id, item.predicate))
    excerpts: list[dict[str, str]] = []
    for fact in ordered:
        statement = _statement_for(fact, entities.get(fact.entity_id))
        source = _source_evidence(fact, evidence.get(fact.evidence_id), statement)
        story_time = fact.effective_story_time.strip() or "未标注故事时间"
        excerpts.append(
            {
                "statement": statement,
                "source_evidence": source,
                "effective_story_time": story_time,
            }
        )
    return excerpts


def _statement_for(fact: CanonFact, entity: Entity | None) -> str:
    name = entity.name.strip() if entity is not None else ""
    value = _value_text(fact.value_json)
    parts = [part for part in (name, fact.predicate.strip(), value) if part]
    if parts:
        return " ".join(parts)
    return fact.predicate.strip() or "已批准 Canon 事实"


def _source_evidence(
    fact: CanonFact,
    record: EvidenceRecord | None,
    statement: str,
) -> str:
    if record is not None and record.quote.strip():
        return record.quote.strip()
    return f"主编已批准并提交：{statement}"


def _value_text(value_json: Any) -> str:
    if isinstance(value_json, str):
        return value_json.strip()
    if isinstance(value_json, dict):
        for key in ("text", "value", "object", "statement"):
            item = value_json.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
    if value_json is None:
        return ""
    return str(value_json).strip()


def _draft_excerpt(draft: SceneDraft | None) -> str | None:
    if draft is None:
        return None
    body = draft.body.strip()
    if not body:
        return None
    if len(body) <= DRAFT_EXCERPT_MAX_CHARS:
        return body
    return body[:DRAFT_EXCERPT_MAX_CHARS]


def _candidate_ids(candidates: list[CandidateChange] | None) -> list[str]:
    if not candidates:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for item in sorted(candidates, key=lambda value: (value.id,)):
        if item.id in seen:
            continue
        seen.add(item.id)
        ordered.append(item.id)
    return ordered
