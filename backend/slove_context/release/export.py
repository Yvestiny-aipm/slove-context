"""Formal export of already-approved Scene Drafts. Does not generate prose."""

from __future__ import annotations

from typing import Any

from slove_context.release.models import (
    REVIEW_PACK_SCHEMA,
    ReleaseCheck,
    ReleaseManifest,
    stable_hash,
)
from slove_context.scene.models import Chapter, Scene
from slove_context.scene_draft.models import SceneDraft
from slove_context.summary.models import ChapterSummary


def build_markdown(
    *,
    check: ReleaseCheck,
    manifest: ReleaseManifest,
    scenes: list[Scene],
    chapters: list[Chapter],
    drafts: list[SceneDraft],
) -> str:
    scene_by_id = {item.id: item for item in scenes}
    chapter_by_id = {item.id: item for item in chapters}
    lines = [
        "# Formal release export",
        "",
        f"- check_id: `{check.id}`",
        f"- manifest_id: `{manifest.id}`",
        f"- content_hash: `{manifest.content_hash}`",
        f"- snapshot_id: `{check.snapshot_id}`",
        "",
        "Existing approved Scene Drafts only. No new prose was generated.",
        "",
    ]

    def _scene_order(item: SceneDraft) -> int:
        scene = scene_by_id.get(item.scene_id)
        return scene.story_order if scene is not None else 0

    ordered = sorted(
        drafts,
        key=lambda item: (_scene_order(item), item.revision),
    )
    for draft in ordered:
        scene = scene_by_id.get(draft.scene_id)
        chapter = chapter_by_id.get(scene.chapter_id) if scene is not None else None
        chapter_title = chapter.title if chapter is not None else ""
        scene_label = scene.id if scene is not None else draft.scene_id
        lines.extend(
            [
                f"## {chapter_title} / {scene_label}",
                "",
                f"- draft_id: `{draft.id}`",
                f"- revision: {draft.revision}",
                f"- content_hash: `{draft.content_hash}`",
                "",
                draft.body,
                "",
            ]
        )
    return "\n".join(lines)


def build_json_export(
    *,
    check: ReleaseCheck,
    manifest: ReleaseManifest,
    scenes: list[Scene],
    chapters: list[Chapter],
    drafts: list[SceneDraft],
    summaries: list[ChapterSummary],
) -> dict[str, Any]:
    return {
        "schema": "release-export.v1",
        "check_id": check.id,
        "manifest_id": manifest.id,
        "manifest_hash": manifest.content_hash,
        "snapshot_id": check.snapshot_id,
        "chapters": [item.to_public_dict() for item in chapters],
        "scenes": [
            {
                "id": item.id,
                "chapter_id": item.chapter_id,
                "story_order": item.story_order,
            }
            for item in scenes
        ],
        "drafts": [
            {
                "id": item.id,
                "scene_id": item.scene_id,
                "revision": item.revision,
                "status": item.status,
                "content_hash": item.content_hash,
                "generation_model": item.generation_model,
                "prompt_version": item.prompt_version,
                "body": item.body,
            }
            for item in drafts
        ],
        "chapter_summaries": [
            {
                "id": item.id,
                "chapter_id": item.chapter_id,
                "revision": item.revision,
                "content_hash": item.content_hash,
                "prompt_version": item.prompt_version,
            }
            for item in summaries
        ],
        "writes_canon": False,
        "auto_approved": False,
        "generates_prose": False,
        "is_formal_release": True,
        "used_real_model": False,
    }


def build_review_pack(
    *,
    check: ReleaseCheck,
    manifest: ReleaseManifest,
    scenes: list[Scene],
    drafts: list[SceneDraft],
    approval_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": REVIEW_PACK_SCHEMA,
        "check_id": check.id,
        "manifest_id": manifest.id,
        "manifest_hash": manifest.content_hash,
        "snapshot_id": check.snapshot_id,
        "drafts": [
            {
                "id": item.id,
                "scene_id": item.scene_id,
                "revision": item.revision,
                "content_hash": item.content_hash,
                "prompt_version": item.prompt_version,
                "generation_model": item.generation_model,
            }
            for item in drafts
        ],
        "scenes": [
            {
                "id": item.id,
                "chapter_id": item.chapter_id,
                "story_order": item.story_order,
            }
            for item in scenes
        ],
        "human_approval_records": approval_refs,
        "gates": [item.to_public_dict() for item in check.gate_results],
        "note": (
            "Editor review pack for a formal release. Copies existing "
            "approved drafts only. Does not submit Canon or generate prose."
        ),
        "writes_canon": False,
        "auto_approved": False,
        "is_canon_approval": False,
        "generates_prose": False,
        "is_formal_release": True,
    }


def hash_export_body(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        return stable_hash({"markdown": payload})
    return stable_hash(payload)
