"""Experiment Run identifiers (node 9.2).

Pins the 9.1 eval case set. Does not change 9.1 expected answers.
Not a release gate (9.3).
"""

from __future__ import annotations

from slove_context.evals.constants import EVAL_SCHEMA_VERSION

CASE_SET_VERSION = EVAL_SCHEMA_VERSION
EXPERIMENT_RANDOM_SEED = 92

DEFAULT_MODEL = "fake-eval"
DEFAULT_PROMPT_VERSION = "eval-experiment.v1"
INVALID_PROMPT_VERSION = "eval-experiment.invalid"
DEFAULT_RETRIEVAL_STRATEGY = "snapshot"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 256

RETRIEVAL_SNAPSHOT = "snapshot"
RETRIEVAL_PINNED = "pinned"
ALLOWED_RETRIEVAL_STRATEGIES = frozenset({RETRIEVAL_SNAPSHOT, RETRIEVAL_PINNED})

TASK_EXPERIMENT_OK = "experiment_eval"
TASK_EXPERIMENT_INVALID = "experiment_eval_invalid"

COMPARE_METRICS = (
    "canon_conflict_count",
    "blocker_error_count",
    "schema_success_rate",
    "first_pass_rate",
    "token_cost",
    "latency_ms",
)
