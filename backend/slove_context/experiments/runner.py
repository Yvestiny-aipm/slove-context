"""Execute an experiment run on pinned 9.1 cases (node 9.2).

Reuses the 9.1 case loader / 5.x scorer and the 3.2 Fake Provider.
Never writes Canon, never approves, never calls a real model.
Deterministic parts use a fixed seed and 9.1 snapshots.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from slove_context.evals.runner import run_case
from slove_context.experiments.constants import (
    EXPERIMENT_RANDOM_SEED,
    TASK_EXPERIMENT_INVALID,
    TASK_EXPERIMENT_OK,
)
from slove_context.experiments.models import (
    RUN_RUNNING,
    RUN_SUCCEEDED,
    ExperimentConfig,
    ExperimentMetrics,
    ExperimentRun,
    TokenCost,
)
from slove_context.experiments.pin import input_versions, pin_case_set
from slove_context.llm.provider import Provider
from slove_context.llm.types import GenerateRequest, Usage
from slove_context.validation.models import RULE_CANON_CONFLICT


def execute_run(
    run: ExperimentRun,
    *,
    provider: Provider,
) -> ExperimentRun:
    """Fill a queued/running run from Fake Provider + pinned 9.1 cases."""
    started = time.perf_counter()
    pin, cases = pin_case_set(case_ids=list(run.pin.case_ids))
    run.pin = pin
    run.input_versions = input_versions(
        pin,
        prompt_version=run.config.prompt_version,
        random_seed=run.config.random_seed,
    )
    run.status = RUN_RUNNING
    output_refs: list[dict[str, Any]] = []
    schema_ok = 0
    first_pass = 0
    canon_conflicts = 0
    blockers = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    cost_amount = 0.0
    latency_total = 0.0
    task_type = _task_type(run.config.prompt_version)
    for case in cases:
        request = GenerateRequest(
            model=run.config.model,
            system_prompt="experiment-eval; case refs only",
            user_prompt=f"case_id={case.manifest.id}",
            temperature=run.config.temperature,
            max_tokens=run.config.max_tokens,
            correlation_id=run.id,
            task_type=task_type,
            prompt_version=run.config.prompt_version,
        )
        response = provider.generate_structured(request)
        usage = response.usage
        schema_passed = response.error is None and isinstance(
            response.parsed_output, (dict, list)
        )
        if schema_passed:
            schema_ok += 1
        else:
            blockers += 1
        scored = run_case(case)
        case_conflicts = sum(
            1
            for item in scored.observed_violations
            if item.get("rule_id") == RULE_CANON_CONFLICT
        )
        case_blockers = sum(
            1
            for item in scored.observed_violations
            if item.get("severity") == "Blocking"
        )
        canon_conflicts += case_conflicts
        blockers += case_blockers
        if schema_passed and scored.passed:
            first_pass += 1
        latency = _deterministic_latency_ms(run.config, case.manifest.id, usage)
        latency_total += latency
        prompt_tokens += usage.prompt_tokens
        completion_tokens += usage.completion_tokens
        total_tokens += usage.total_tokens
        cost_amount += usage.cost_amount
        output_refs.append(
            {
                "case_id": case.manifest.id,
                "raw_response_reference": response.raw_response_reference,
                "request_id": response.request_id,
                "provider": response.provider,
                "model": response.model,
                "prompt_version": response.prompt_version,
                "schema_ok": schema_passed,
                "first_pass": bool(schema_passed and scored.passed),
                "canon_conflict_count": case_conflicts,
                "blocker_error_count": case_blockers + (0 if schema_passed else 1),
            }
        )
    count = len(cases) or 1
    run.output_refs = output_refs
    run.metrics = ExperimentMetrics(
        canon_conflict_count=canon_conflicts,
        blocker_error_count=blockers,
        schema_success_rate=round(schema_ok / count, 4),
        first_pass_rate=round(first_pass / count, 4),
        token_cost=total_tokens,
        latency_ms=round(latency_total, 3),
    )
    run.cost = TokenCost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_amount=round(cost_amount, 6),
        cost_currency="USD",
    )
    run.latency_ms = run.metrics.latency_ms
    run.duration_ms = round((time.perf_counter() - started) * 1000, 3)
    run.writes_canon = False
    run.auto_approved = False
    run.used_real_model = False
    run.status = RUN_SUCCEEDED
    return run


def _task_type(prompt_version: str) -> str:
    lowered = prompt_version.strip().lower()
    if "invalid" in lowered:
        return TASK_EXPERIMENT_INVALID
    return TASK_EXPERIMENT_OK


def _deterministic_latency_ms(
    config: ExperimentConfig, case_id: str, usage: Usage
) -> float:
    material = "|".join(
        [
            str(EXPERIMENT_RANDOM_SEED),
            case_id,
            config.model,
            config.prompt_version,
            config.retrieval_strategy,
            f"{config.temperature:.4f}",
            str(config.max_tokens),
            str(usage.total_tokens),
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return float((int(digest[:8], 16) % 500) + usage.total_tokens)
