"""Load the versioned Candidate Change extract Prompt (node 4.1).

The template lives under prompts/ with an explicit version number.
It requires JSON output and forbids Canon writes, approval, and new prose.
Filled prompts are not written to logs or audit (1.3 redaction).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slove_context.candidate_change.models import PROMPT_VERSION
from slove_context.scene.models import Scene
from slove_context.scene_draft.models import SceneDraft

PROMPT_FILENAME = "extract_candidates.v1.md"


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


def build_user_prompt(*, scene: Scene, draft: SceneDraft) -> str:
    """Structured extract input. Draft body is read-only source text."""
    payload: dict[str, Any] = {
        "task": "extract_candidate_changes_json_only",
        "forbid_new_prose": True,
        "forbid_canon_write": True,
        "forbid_approve": True,
        "scene_id": scene.id,
        "draft_id": draft.id,
        "draft_revision": draft.revision,
        "draft_status": draft.status,
        "draft_content_hash": draft.content_hash,
        "story_time": scene.story_time,
        "source_scene_id": scene.id,
        "draft_body": draft.body,
        "output": (
            "JSON object {candidates:[...]} or a JSON array of candidates. "
            "Each item needs subject, predicate, object, value, "
            "effective_story_time, evidence_quote, confidence. No 正文."
        ),
    }
    return (
        "根据下列已生成且不可变的 Scene Draft 抽取 Candidate Change JSON。"
        "只输出 JSON。禁止写 Canon。禁止批准。禁止生成新散文。"
        "每条必须带 evidence_quote。初始状态只能是 Extracted。\n"
        f"{_compact(payload)}"
    )


def build_repair_user_prompt(*, validation_errors: list[dict[str, str]]) -> str:
    return (
        "上一次结构化输出未通过 contracts/candidate-change.schema.json。"
        "这是唯一一次 format repair。"
        "只输出修正后的 JSON 对象或候选数组。"
        "禁止写 Canon。禁止批准。禁止生成新散文。"
        "不要重复解释。"
        f"validation_errors={_compact(validation_errors)}"
    )


def _compact(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
