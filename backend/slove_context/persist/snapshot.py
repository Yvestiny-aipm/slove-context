"""Serialize / restore the in-memory book repositories (node P.1)."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, TypeVar

from slove_context.candidate_change.models import CandidateChange, ExtractJob
from slove_context.candidate_change.repository import InMemoryCandidateChangeRepository
from slove_context.canon.models import (
    CanonFact,
    CanonFactVersion,
    CanonSnapshot,
    Entity,
    EvidenceRecord,
)
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.context_pack.models import ContextPack
from slove_context.context_pack.repository import InMemoryContextPackRepository
from slove_context.scene.models import Arc, Chapter, Scene
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_draft.models import SceneDraft, SceneDraftJob
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.scene_plan.models import ScenePlan, ScenePlanJob
from slove_context.scene_plan.repository import InMemoryScenePlanRepository
from slove_context.story.models import StoryProject, StorySpec, StorySpecVersion
from slove_context.story.repository import InMemoryStoryRepository

SNAPSHOT_VERSION = 1

T = TypeVar("T")


@dataclass
class BookBundle:
    story: InMemoryStoryRepository
    canon: InMemoryCanonRepository
    scene: InMemorySceneRepository
    scene_plan: InMemoryScenePlanRepository
    scene_draft: InMemorySceneDraftRepository
    candidate_change: InMemoryCandidateChangeRepository
    context_pack: InMemoryContextPackRepository


def _as_dict(item: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in fields(item):
        value = getattr(item, field.name)
        if isinstance(value, list):
            payload[field.name] = [
                _as_dict(entry) if hasattr(entry, "__dataclass_fields__") else entry
                for entry in value
            ]
        else:
            payload[field.name] = value
    return payload


def _model(cls: type[T], data: dict[str, Any], **overrides: Any) -> T:
    names = set(getattr(cls, "__dataclass_fields__", {}))
    payload = {key: value for key, value in data.items() if key in names}
    payload.update(overrides)
    return cls(**payload)


def _map_models(cls: type[T], raw: Any) -> dict[str, T]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): _model(cls, dict(value)) for key, value in raw.items()}


def _unwrap(repo: Any) -> Any:
    inner = getattr(repo, "_inner", repo)
    return inner


def dump_book(bundle: BookBundle) -> dict[str, Any]:
    story = _unwrap(bundle.story)
    canon = _unwrap(bundle.canon)
    scene = _unwrap(bundle.scene)
    plans = _unwrap(bundle.scene_plan)
    drafts = _unwrap(bundle.scene_draft)
    candidates = _unwrap(bundle.candidate_change)
    packs = _unwrap(bundle.context_pack)
    current_map = getattr(plans, "_current", {})
    current_plans = [
        {
            "project_id": project_id,
            "scene_id": scene_id,
            "plan_id": plan_id,
        }
        for (project_id, scene_id), plan_id in current_map.items()
    ]
    return {
        "version": SNAPSHOT_VERSION,
        "story": {
            "projects": {key: _as_dict(item) for key, item in story.projects.items()},
            "specs": {key: _as_dict(item) for key, item in story.specs.items()},
        },
        "scene": {
            "arcs": {key: _as_dict(item) for key, item in scene.arcs.items()},
            "chapters": {key: _as_dict(item) for key, item in scene.chapters.items()},
            "scenes": {key: _as_dict(item) for key, item in scene.scenes.items()},
        },
        "scene_plan": {
            "jobs": {key: _as_dict(item) for key, item in plans.jobs.items()},
            "plans": {key: _as_dict(item) for key, item in plans.plans.items()},
            "current": current_plans,
        },
        "scene_draft": {
            "jobs": {key: _as_dict(item) for key, item in drafts.jobs.items()},
            "drafts": {key: _as_dict(item) for key, item in drafts.drafts.items()},
        },
        "canon": {
            "entities": {key: _as_dict(item) for key, item in canon.entities.items()},
            "evidence": {key: _as_dict(item) for key, item in canon.evidence.items()},
            "facts": {key: _as_dict(item) for key, item in canon.facts.items()},
            "snapshots": {key: _as_dict(item) for key, item in canon.snapshots.items()},
        },
        "candidate_change": {
            "jobs": {key: _as_dict(item) for key, item in candidates.jobs.items()},
            "candidates": {
                key: _as_dict(item) for key, item in candidates.candidates.items()
            },
        },
        "context_pack": {
            "packs": {key: _as_dict(item) for key, item in packs.packs.items()},
        },
    }


def apply_snapshot(payload: dict[str, Any], bundle: BookBundle) -> None:
    story_raw = payload.get("story") or {}
    scene_raw = payload.get("scene") or {}
    plan_raw = payload.get("scene_plan") or {}
    draft_raw = payload.get("scene_draft") or {}
    canon_raw = payload.get("canon") or {}
    candidate_raw = payload.get("candidate_change") or {}
    pack_raw = payload.get("context_pack") or {}

    story = _unwrap(bundle.story)
    scene = _unwrap(bundle.scene)
    plans = _unwrap(bundle.scene_plan)
    drafts = _unwrap(bundle.scene_draft)
    canon = _unwrap(bundle.canon)
    candidates = _unwrap(bundle.candidate_change)
    packs = _unwrap(bundle.context_pack)

    story.projects = _map_models(StoryProject, story_raw.get("projects"))
    story.specs = {}
    for spec_id, spec_data in dict(story_raw.get("specs") or {}).items():
        spec_versions = [
            _model(StorySpecVersion, dict(item))
            for item in spec_data.get("versions") or []
        ]
        story.specs[str(spec_id)] = _model(
            StorySpec, dict(spec_data), versions=spec_versions
        )

    scene.arcs = _map_models(Arc, scene_raw.get("arcs"))
    scene.chapters = _map_models(Chapter, scene_raw.get("chapters"))
    scene.scenes = _map_models(Scene, scene_raw.get("scenes"))

    plans.jobs = _map_models(ScenePlanJob, plan_raw.get("jobs"))
    plans.plans = _map_models(ScenePlan, plan_raw.get("plans"))
    current_map: dict[tuple[str, str], str] = {}
    for item in plan_raw.get("current") or []:
        if not isinstance(item, dict):
            continue
        project_id = str(item.get("project_id") or "")
        scene_id = str(item.get("scene_id") or "")
        plan_id = str(item.get("plan_id") or "")
        if project_id and scene_id and plan_id:
            current_map[(project_id, scene_id)] = plan_id
    plans._current = current_map

    drafts.jobs = _map_models(SceneDraftJob, draft_raw.get("jobs"))
    drafts.drafts = _map_models(SceneDraft, draft_raw.get("drafts"))

    canon.entities = _map_models(Entity, canon_raw.get("entities"))
    canon.evidence = _map_models(EvidenceRecord, canon_raw.get("evidence"))
    canon.facts = {}
    for fact_id, fact_data in dict(canon_raw.get("facts") or {}).items():
        fact_versions = [
            _model(CanonFactVersion, dict(item))
            for item in fact_data.get("versions") or []
        ]
        canon.facts[str(fact_id)] = _model(
            CanonFact, dict(fact_data), versions=fact_versions
        )
    canon.snapshots = _map_models(CanonSnapshot, canon_raw.get("snapshots"))

    candidates.jobs = _map_models(ExtractJob, candidate_raw.get("jobs"))
    candidates.candidates = _map_models(
        CandidateChange, candidate_raw.get("candidates")
    )

    packs.packs = _map_models(ContextPack, pack_raw.get("packs"))
