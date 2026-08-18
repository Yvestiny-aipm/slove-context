"""Load versioned Scene / Chapter summary Prompt templates (node 4.3).

Templates live under prompts/ with explicit version numbers.
Scene summaries recap one Scene Draft. Chapter summaries roll up
existing Scene Summaries only — they do not generate chapter prose.
Filled prompts are not written to logs or audit (1.3 redaction).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slove_context.scene.models import Scene
from slove_context.scene_draft.models import SceneDraft
from slove_context.summary.models import (
    CHAPTER_PROMPT_VERSION,
    SCENE_PROMPT_VERSION,
    SceneSummary,
)

SCENE_PROMPT_FILENAME = "scene_summary.v1.md"
CHAPTER_PROMPT_FILENAME = "chapter_summary.v1.md"


def _find_prompt_path(filename: str) -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "prompts" / filename
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Could not locate prompts/{filename} from {here}")


def load_scene_prompt_template() -> str:
    return _find_prompt_path(SCENE_PROMPT_FILENAME).read_text(encoding="utf-8")


def load_chapter_prompt_template() -> str:
    return _find_prompt_path(CHAPTER_PROMPT_FILENAME).read_text(encoding="utf-8")


def scene_prompt_version() -> str:
    return SCENE_PROMPT_VERSION


def chapter_prompt_version() -> str:
    return CHAPTER_PROMPT_VERSION


def build_scene_system_prompt() -> str:
    return load_scene_prompt_template()


def build_chapter_system_prompt() -> str:
    return load_chapter_prompt_template()


def build_scene_user_prompt(*, scene: Scene, draft: SceneDraft) -> str:
    """Task input refs. Full Prompt / draft prose are redacted in logs."""
    payload: dict[str, Any] = {
        "task": "summarize_one_scene_draft",
        "forbid_canon_write": True,
        "forbid_auto_approve": True,
        "forbid_candidate_extract": True,
        "forbid_new_prose": True,
        "generation_unit": "one_scene",
        "scene_id": scene.id,
        "draft_revision_id": draft.id,
        "draft_revision": draft.revision,
        "draft_content_hash": draft.content_hash,
        "draft_status": draft.status,
        "output": "本场短摘要。不得写 Canon，不得抽取候选，不得生成新散文。",
    }
    return (
        "根据已有且不可变的 Scene Draft 修订版本，只写这一场的短摘要。"
        "必须引用草稿修订 id 与内容哈希。不得写 Canon。不得自动批准。"
        "不得一次写整章。不得当作 Candidate Change。\n"
        f"{_compact(payload)}\n"
        f"draft_body_ref={draft.id}"
    )


def build_chapter_user_prompt(
    *,
    chapter_id: str,
    scene_summaries: list[SceneSummary],
) -> str:
    """Roll-up input refs only. Does not ask for chapter prose."""
    sources = [
        {
            "scene_id": item.scene_id,
            "scene_summary_revision_id": item.id,
            "revision": item.revision,
            "content_hash": item.content_hash,
            "source_draft_revision_id": item.source_draft_revision_id,
        }
        for item in scene_summaries
    ]
    payload: dict[str, Any] = {
        "task": "rollup_chapter_from_scene_summaries",
        "forbid_chapter_prose_generate": True,
        "forbid_canon_write": True,
        "forbid_auto_approve": True,
        "forbid_candidate_extract": True,
        "generation_unit": "scene_summaries_only",
        "chapter_id": chapter_id,
        "source_scene_summaries": sources,
        "output": "由已有场景摘要汇总的章摘要。不得生成整章散文。",
    }
    return (
        "根据本章已有的 Scene Summary 修订版本做汇总。"
        "不得一次生成整章散文。不得写 Canon。不得自动批准。"
        "不得抽取候选变更。缺少任一所需场景摘要时不得编造。\n"
        f"{_compact(payload)}"
    )


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
