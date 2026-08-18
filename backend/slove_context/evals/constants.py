"""Eval-only identifiers. Production 5.x rule ids stay unchanged."""

from __future__ import annotations

from slove_context.validation.models import (
    RULE_CANON_CONFLICT,
    RULE_SPEC_FORBID,
)

EVAL_SCHEMA_VERSION = "eval-9.1.0"

# Eval-only. 5.x does not check Story Spec must_write against draft prose.
RULE_EVAL_LOST_FORESHADOWING = "eval.lost-foreshadowing"

PRODUCTION_RULE_IDS = frozenset({RULE_CANON_CONFLICT, RULE_SPEC_FORBID})
EVAL_ONLY_RULE_IDS = frozenset({RULE_EVAL_LOST_FORESHADOWING})

REQUIRED_CATEGORIES = (
    "timeline_reversal",
    "location_conflict",
    "item_transfer",
    "injury_invalidated",
    "knowledge_leak",
    "world_rule_violation",
    "pov_error",
    "lost_foreshadowing",
    "future_information_leak",
)

DIFFICULTIES = frozenset({"easy", "medium", "hard"})
SEVERITIES = frozenset({"Blocking", "Advisory"})
