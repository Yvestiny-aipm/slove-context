"""Load the versioned Scene Draft Prompt template (node 3.4).

The template lives under prompts/ with an explicit version number.
It asks for this one scene's prose only and forbids writing Canon.
Filled prompts are not written to logs or audit (1.3 redaction).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slove_context.scene.models import Scene
from slove_context.scene_draft.models import PROMPT_VERSION
from slove_context.scene_plan.models import ScenePlan

PROMPT_FILENAME = "scene_draft.v1.md"


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
    plan: ScenePlan,
    snapshot_id: str,
    context_pack_id: str,
    context_pack: dict[str, Any],
) -> str:
    """Task input refs. Full Prompt is redacted in logs (1.3)."""
    card = scene.scene_card
    payload: dict[str, Any] = {
        "task": "generate_scene_draft_prose_only",
        "forbid_canon_write": True,
        "forbid_auto_approve": True,
        "forbid_fact_extraction": True,
        "generation_unit": "one_scene",
        "scene_id": scene.id,
        "scene_card_id": scene.scene_card_id,
        "plan_id": plan.id,
        "snapshot_id": snapshot_id,
        "context_pack_id": context_pack_id,
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
        "scene_plan": {
            "id": plan.id,
            "status": plan.status,
            "intent": plan.payload.get("intent"),
            "beats": plan.payload.get("beats"),
        },
        "context_pack_ref": {
            "id": context_pack.get("id"),
            "purpose": context_pack.get("purpose"),
            "pre_frozen": True,
        },
        "output": "本场散文正文。不得写 Canon，不得抽取候选变更。",
    }
    return (
        "根据已批准 Scene Card、有效 Scene Plan、指定 Canon Snapshot "
        "与预冻结 Context Pack 引用，只生成这一场的散文正文。"
        "不得写 Canon。不得自动批准。不得一次写整章。\n"
        f"{_compact(payload)}"
    )


def _compact(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
