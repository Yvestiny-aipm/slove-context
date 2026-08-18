"""Compare an experiment run to a baseline on the six 9.2 metrics."""

from __future__ import annotations

from slove_context.experiments.constants import COMPARE_METRICS
from slove_context.experiments.models import (
    ExperimentComparison,
    ExperimentRun,
    MetricDelta,
)


def compare_runs(
    *,
    comparison_id: str,
    experiment_id: str,
    baseline: ExperimentRun,
    candidate: ExperimentRun,
    created_at: str,
    created_by: str,
    actor_type: str,
) -> ExperimentComparison:
    baseline_metrics = baseline.metrics.to_public_dict()
    candidate_metrics = candidate.metrics.to_public_dict()
    deltas: list[MetricDelta] = []
    for name in COMPARE_METRICS:
        left = baseline_metrics[name]
        right = candidate_metrics[name]
        delta: int | float
        if isinstance(left, int) and isinstance(right, int):
            delta = right - left
        else:
            delta = round(float(right) - float(left), 4)
        deltas.append(
            MetricDelta(
                metric=name,
                baseline=left,
                candidate=right,
                delta=delta,
            )
        )
    return ExperimentComparison(
        id=comparison_id,
        experiment_id=experiment_id,
        baseline_run_id=baseline.id,
        candidate_run_id=candidate.id,
        metrics=deltas,
        created_at=created_at,
        created_by=created_by,
        actor_type=actor_type,
    )
