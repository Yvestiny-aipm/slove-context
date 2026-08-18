"""Load the versioned Style Validation Prompt (node 7.2).

The template forbids living-author imitation and unauthorized samples.
Filled prompts are not written to logs or audit (1.3 redaction).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slove_context.style.models import StyleGuide
from slove_context.style_validation.models import PROMPT_VERSION

PROMPT_FILENAME = "style_validation.v1.md"


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


def build_user_prompt(*, guide: StyleGuide, draft_revision_id: str, body: str) -> str:
    """Ask only whether the draft conforms to this project's approved Guide."""
    payload: dict[str, Any] = {
        "task": "evaluate_style_guide_conformance_only",
        "forbid_living_author_imitation": True,
        "forbid_unauthorized_samples": True,
        "forbid_canon_write": True,
        "draft_revision_id": draft_revision_id,
        "style_guide_revision_id": guide.id,
        "style_guide": {
            "pov": guide.pov,
            "人称": guide.person,
            "时态": guide.tense,
            "叙述距离": guide.narrative_distance,
            "语气": guide.tone,
            "节奏": guide.rhythm,
            "对话规则": list(guide.dialogue_rules),
            "词汇偏好": list(guide.vocabulary_preferences),
            "禁用表达": list(guide.forbidden_expressions),
        },
        "draft_character_count": len(body),
        "output": (
            "JSON object with conforms, findings "
            "[{problem, text_evidence, severity, minimal_fix}], "
            "score_version. severity must be warning or info."
        ),
    }
    return (
        "只判断下列草稿是否符合本项目已批准 Style Guide。"
        "禁止要求仿写在世作家。禁止把未授权样本当风格参照。"
        "不得写 Canon。只输出 JSON。\n"
        f"{_compact(payload)}\n"
        f"draft_excerpt_ref={draft_revision_id}\n"
        f"draft_body={body}"
    )


def _compact(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
