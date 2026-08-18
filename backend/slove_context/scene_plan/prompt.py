"""Load the versioned Scene Plan Prompt template (node 3.3).

The template lives under prompts/ with an explicit version number.
It requires JSON output and forbids Scene Draft prose / 正文.
Filled prompts are not written to logs or audit (1.3 redaction).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slove_context.scene.models import Scene
from slove_context.scene_plan.models import PROMPT_VERSION

PROMPT_FILENAME = "scene_plan.v1.md"


def _find_prompt_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "prompts" / PROMPT_FILENAME
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Could not locate prompts/{PROMPT_FILENAME} from {here}")


def load_prompt_template() -> str:
    return _find_prompt_path().read_text(encoding="utf-8")


def prompt_version() -> str:
    return PROMPT_VERSION


def build_system_prompt() -> str:
    return load_prompt_template()


def build_user_prompt(
    *,
    scene: Scene,
    snapshot_id: str,
    snapshot_fact_ids: list[str],
) -> str:
    """Structured task input. Not Scene Draft prose."""
    card = scene.scene_card
    payload: dict[str, Any] = {
        "task": "generate_scene_plan_json_only",
        "forbid_scene_draft": True,
        "forbid_prose": True,
        "forbid_canon_write": True,
        "scene_id": scene.id,
        "scene_card_id": scene.scene_card_id,
        "snapshot_id": snapshot_id,
        "snapshot_fact_ids": list(snapshot_fact_ids),
        "scene_card": {
            "location": card.get("location", scene.location),
            "present_entities": list(scene.present_entities),
            "generation_boundary": scene.generation_boundary,
            "forbidden": list(scene.forbidden),
            "knowledge_boundaries": list(scene.knowledge_boundaries),
            "pov": scene.pov,
            "story_time": scene.story_time,
            "starting_state": scene.starting_state,
            "goal": scene.goal,
            "conflict": scene.conflict,
            "expected_end_state": scene.expected_end_state,
        },
        "output": "JSON object with intent and beats. No 正文.",
    }
    return (
        "根据下列已批准 Scene Card 与指定 Canon Snapshot 生成 Scene Plan JSON。"
        "只输出 JSON。禁止散文 / 正文 / Scene Draft。不得写 Canon。\n"
        f"{_compact(payload)}"
    )


def build_repair_user_prompt(*, validation_errors: list[dict[str, str]]) -> str:
    return (
        "上一次结构化输出未通过 contracts/scene-plan.schema.json。"
        "这是唯一一次 format repair。"
        "只输出修正后的 JSON 对象。"
        "禁止散文 / 正文 / Scene Draft。"
        "不要重复解释。"
        f"validation_errors={_compact(validation_errors)}"
    )


def _compact(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
