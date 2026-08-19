"""Deterministic Chinese shuttle prompts (nodes UI.2 / UI.3).

Assembled from Scene Card / Spec / Snapshot excerpts / existing
draft or scene-summary bodies. No LLM. Filled prompts are not
written to logs or audit (1.3 redaction).
"""

from __future__ import annotations

from typing import Any

from slove_context.scene.models import Scene
from slove_context.scene_draft.models import SceneDraft
from slove_context.story.models import StorySpecVersion
from slove_context.summary.models import SceneSummary
from slove_context.summary.prompt import (
    load_chapter_prompt_template,
    load_scene_prompt_template,
)


def build_draft_prompt(
    *,
    scene: Scene,
    spec: StorySpecVersion | None,
    snapshot_id: str | None,
    excerpts: list[dict[str, str]],
) -> str:
    """Chinese write-draft prompt. Includes 目标 / 禁止 / 知识边界."""
    must_write = list(spec.must_write) if spec is not None else []
    must_not_write = list(spec.must_not_write) if spec is not None else []
    excerpt_lines = _excerpt_lines(excerpts)
    forbidden = [item for item in scene.forbidden if item]
    knowledge = [item for item in scene.knowledge_boundaries if item]
    return "\n".join(
        [
            "请根据下列已批准场景卡与规格要点，只写这一场的中文散文正文。",
            "不得写 Canon。不得批准。不得一次写整章。候选变更不是本任务。",
            "",
            f"场景 id：{scene.id}",
            f"POV：{scene.pov}",
            f"故事时间：{scene.story_time}",
            f"地点：{scene.location}",
            f"起始状态：{scene.starting_state}",
            f"目标：{scene.goal}",
            f"冲突：{scene.conflict}",
            f"预期结束状态：{scene.expected_end_state}",
            f"在场：{'、'.join(scene.present_entities) if scene.present_entities else '无'}",
            f"生成边界：{scene.generation_boundary}",
            f"禁止：{_join_or_none(forbidden)}",
            f"知识边界：{_join_or_none(knowledge)}",
            "",
            "规格要点（编辑约束，不是 Canon）：",
            f"必须写：{_join_or_none(must_write)}",
            f"不得写：{_join_or_none(must_not_write)}",
            "",
            f"冻结 Snapshot 摘录（只读，id={snapshot_id or '无'}）：",
            excerpt_lines,
            "",
            "只输出本场散文。不要解释，不要 JSON，不要写 Canon。",
        ]
    )


def build_extract_prompt(*, scene: Scene, draft: SceneDraft) -> str:
    """Chinese extract prompt. Model must output only a JSON array."""
    forbidden = [item for item in scene.forbidden if item]
    return "\n".join(
        [
            "根据下列已生成且不可变的场景草稿，抽取候选变更。",
            "只输出一个 JSON 数组，不要任何其他文字。",
            (
                "每条对象字段只能是：subject, predicate, object, value, "
                "effective_story_time, evidence_quote, confidence。"
            ),
            "evidence_quote 必须是该草稿正文的连续摘录（contiguous excerpt）。",
            "候选变更不是真相，不得写 Canon，不得批准。",
            "",
            f"场景 id：{scene.id}",
            f"草稿 id：{draft.id}",
            f"目标：{scene.goal}",
            f"禁止：{_join_or_none(forbidden)}",
            f"故事时间：{scene.story_time}",
            "",
            "草稿正文（只读，禁止改写）：",
            draft.body,
            "",
            "只输出 JSON 数组。候选不是真相。不得写 Canon。",
        ]
    )


def build_scene_summary_prompt(*, scene: Scene, draft: SceneDraft) -> str:
    """Chinese scene-summary prompt. Reuses scene_summary.v1 + draft body."""
    template = load_scene_prompt_template().rstrip()
    return "\n".join(
        [
            template,
            "",
            "## 本场草稿修订（只读，禁止改写）",
            f"场景 id：{scene.id}",
            f"草稿修订 id：{draft.id}",
            f"草稿修订号：{draft.revision}",
            f"草稿内容哈希：{draft.content_hash}",
            f"草稿状态：{draft.status}",
            "",
            "草稿正文：",
            draft.body,
            "",
            "只输出这一场的短摘要。不得写 Canon。不得生成新散文。不得抽取候选。",
        ]
    )


def build_chapter_summary_prompt(
    *,
    chapter_id: str,
    scene_summaries: list[SceneSummary],
) -> str:
    """Chinese chapter-summary prompt. Reuses chapter_summary.v1 + scene summaries."""
    template = load_chapter_prompt_template().rstrip()
    blocks: list[str] = []
    for item in scene_summaries:
        blocks.extend(
            [
                f"场景 id：{item.scene_id}",
                f"场景摘要修订 id：{item.id}",
                f"修订号：{item.revision}",
                f"内容哈希：{item.content_hash}",
                f"来源草稿修订 id：{item.source_draft_revision_id}",
                "摘要正文：",
                item.body,
                "",
            ]
        )
    source_block = "\n".join(blocks).rstrip() if blocks else "（无场景摘要）"
    source_ids = "、".join(item.id for item in scene_summaries) or "无"
    return "\n".join(
        [
            template,
            "",
            f"## 本章已有场景摘要（只读，chapter_id={chapter_id}）",
            f"所用场景摘要修订 id：{source_ids}",
            "",
            source_block,
            "",
            "只输出由已有场景摘要汇总而成的短章摘要。不得生成整章散文。不得写 Canon。",
        ]
    )


def _excerpt_lines(excerpts: list[dict[str, str]]) -> str:
    if not excerpts:
        return "（当前冻结快照无摘录）"
    lines: list[str] = []
    for index, item in enumerate(excerpts, start=1):
        statement = str(item.get("statement") or "").strip()
        story_time = str(item.get("effective_story_time") or "").strip()
        lines.append(f"{index}. {statement}（故事时间：{story_time or '未标注'}）")
    return "\n".join(lines)


def _join_or_none(items: list[Any]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    return "；".join(cleaned) if cleaned else "无"
