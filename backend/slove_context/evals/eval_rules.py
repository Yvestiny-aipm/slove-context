"""Eval-only deterministic checks.

Used only when a required consistency category cannot be expressed with
the existing 5.x hard rules (Active-fact conflict + Spec forbid-list).
These ids are prefixed ``eval.`` and must not replace production rule ids.
"""

from __future__ import annotations

from typing import Any

from slove_context.evals.constants import RULE_EVAL_LOST_FORESHADOWING
from slove_context.validation.models import (
    ACTION_REGENERATE,
    SEVERITY_BLOCKING,
    Violation,
)


def evaluate_eval_only(
    *,
    story_spec: dict[str, Any],
    draft: dict[str, Any],
) -> list[Violation]:
    """Check Story Spec must_write tokens against draft prose.

    5.x only inspects must_not_write on Candidate Changes. A missing
    foreshadow is an absence in the draft, so it needs this check.
    """
    prose = str(draft.get("prose") or "")
    violations: list[Violation] = []
    for raw in story_spec.get("must_write") or []:
        phrase = _foreshadow_phrase(str(raw))
        if not phrase or phrase in prose:
            continue
        violations.append(
            Violation(
                rule_id=RULE_EVAL_LOST_FORESHADOWING,
                severity=SEVERITY_BLOCKING,
                entity_ids=_entity_ids_for_missing(phrase),
                source_evidence=_draft_excerpt(prose),
                canon_evidence=f"Story Spec must_write: {raw}",
                recommended_action=ACTION_REGENERATE,
            )
        )
    return violations


def _foreshadow_phrase(raw: str) -> str:
    """Only ``伏笔：…`` must_write items are eval-only foreshadow tokens.

    Other must_write lines stay Story Spec scope constraints. 5.x does
    not inspect them; this check must not invent extra hits on them.
    """
    stripped = raw.strip()
    for prefix in ("伏笔：", "伏笔:"):
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return ""


def _entity_ids_for_missing(phrase: str) -> list[str]:
    for name in ("残玉", "林晚", "顾衡"):
        if name in phrase:
            return [name]
    return ["林晚"]


def _draft_excerpt(prose: str, *, limit: int = 40) -> str:
    compact = " ".join(prose.split())
    if not compact:
        return "[empty draft]"
    if len(compact) <= limit:
        return compact
    return compact[:limit]
