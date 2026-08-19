"""Deterministic Chinese shuttle prompts (node UI.2).

Assembled from Scene Card / Spec / Snapshot excerpts. No LLM.
Filled prompts are not written to logs or audit (1.3 redaction).
"""

from __future__ import annotations

from typing import Any

from slove_context.scene.models import Scene
from slove_context.scene_draft.models import SceneDraft
from slove_context.story.models import StorySpecVersion


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
