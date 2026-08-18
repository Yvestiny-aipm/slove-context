"""Build in-memory 5.x models from eval fixtures. No repositories, no writes."""

from __future__ import annotations

from typing import Any

from slove_context.candidate_change.models import (
    CANDIDATE_EXTRACTED,
    CandidateChange,
)
from slove_context.canon.models import FACT_ACTIVE, CanonFact, Entity
from slove_context.story.models import StorySpecVersion


def story_spec_version(payload: dict[str, Any]) -> StorySpecVersion:
    spec_id = str(payload["id"])
    return StorySpecVersion(
        id=spec_id,
        spec_id=spec_id,
        revision_number=1,
        schema_version=str(payload["schema_version"]),
        title=str(payload["title"]),
        language=str(payload["language"]),
        status=str(payload["status"]),
        must_write=[str(item) for item in payload.get("must_write") or []],
        must_not_write=[str(item) for item in payload.get("must_not_write") or []],
        notes=payload.get("notes"),
        payload=dict(payload),
        created_at=str(payload["created_at"]),
        created_by=str(payload["created_by"]),
    )


def entities_from_snapshot(snapshot: dict[str, Any]) -> list[Entity]:
    project_id = str(snapshot["project_id"])
    created_at = str(snapshot.get("created_at") or "2026-08-18T03:00:00Z")
    created_by = str(snapshot.get("created_by") or "editor-1")
    items: list[Entity] = []
    for raw in snapshot.get("entities") or []:
        if not isinstance(raw, dict):
            continue
        items.append(
            Entity(
                id=str(raw["id"]),
                project_id=project_id,
                entity_type=str(raw.get("entity_type") or "character"),
                name=str(raw["name"]),
                created_at=str(raw.get("created_at") or created_at),
                created_by=str(raw.get("created_by") or created_by),
            )
        )
    return items


def facts_from_snapshot(snapshot: dict[str, Any]) -> list[CanonFact]:
    project_id = str(snapshot["project_id"])
    created_at = str(snapshot.get("created_at") or "2026-08-18T03:00:00Z")
    created_by = str(snapshot.get("created_by") or "editor-1")
    items: list[CanonFact] = []
    for raw in snapshot.get("facts") or []:
        if not isinstance(raw, dict):
            continue
        fact_id = str(raw["id"])
        items.append(
            CanonFact(
                id=fact_id,
                project_id=project_id,
                entity_id=str(raw["entity_id"]),
                predicate=str(raw["predicate"]),
                value_json=raw.get("value_json"),
                effective_story_time=str(raw.get("effective_story_time") or ""),
                valid_from_scene_id=str(raw.get("valid_from_scene_id") or ""),
                status=str(raw.get("status") or FACT_ACTIVE),
                source_type=str(raw.get("source_type") or "editor"),
                evidence_id=str(raw.get("evidence_id") or fact_id),
                current_version_id=str(raw.get("current_version_id") or fact_id),
                created_at=created_at,
                created_by=created_by,
            )
        )
    return items


def candidate_from_payload(
    payload: dict[str, Any], *, draft_id: str
) -> CandidateChange:
    candidate_id = str(payload["id"])
    scene_id = str(payload["source_scene_id"])
    return CandidateChange(
        id=candidate_id,
        project_id=str(payload["project_id"]),
        scene_id=scene_id,
        draft_id=draft_id,
        job_id="eval-not-a-job",
        extract_batch=1,
        schema_version=str(payload["schema_version"]),
        subject=str(payload["subject"]),
        predicate=str(payload["predicate"]),
        object=str(payload["object"]),
        value=str(payload["value"]),
        effective_story_time=str(payload["effective_story_time"]),
        source_scene_id=scene_id,
        evidence_quote=str(payload["evidence_quote"]),
        confidence=float(payload["confidence"]),
        status=str(payload.get("status") or CANDIDATE_EXTRACTED),
        created_at=str(payload["created_at"]),
        created_by=str(payload["created_by"]),
        payload=dict(payload),
    )
