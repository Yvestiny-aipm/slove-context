"""Experiment, run, and comparison records (node 9.2).

Runs are immutable after they leave queued. Changing prompt_version
opens a new run. Experiments never write Canon or approve candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from slove_context.experiments.constants import COMPARE_METRICS

STATUS_CREATED = "created"
STATUS_CANCELLED = "cancelled"

EXPERIMENT_STATUSES = frozenset({STATUS_CREATED, STATUS_CANCELLED})

RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"

RUN_STATUSES = frozenset(
    {RUN_QUEUED, RUN_RUNNING, RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED}
)
RUN_TERMINAL_STATUSES = frozenset({RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED})
KEEP_RUN_STATUSES = RUN_TERMINAL_STATUSES


@dataclass(frozen=True)
class ExperimentConfig:
    """Five swappable knobs plus the pinned 9.1 case set."""

    model: str
    prompt_version: str
    retrieval_strategy: str
    temperature: float
    max_tokens: int
    case_set_version: str
    random_seed: int

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "retrieval_strategy": self.retrieval_strategy,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "case_set_version": self.case_set_version,
            "random_seed": self.random_seed,
        }


@dataclass(frozen=True)
class CaseSetPin:
    """Immutable snapshot of 9.1 case ids, fixture hashes, and snapshot ids."""

    version: str
    case_ids: tuple[str, ...]
    fixture_hashes: dict[str, dict[str, str]]
    expected_hashes: dict[str, dict[str, str]]
    snapshot_ids: dict[str, str]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "case_ids": list(self.case_ids),
            "fixture_hashes": {
                case_id: dict(hashes) for case_id, hashes in self.fixture_hashes.items()
            },
            "expected_hashes": {
                case_id: dict(hashes)
                for case_id, hashes in self.expected_hashes.items()
            },
            "snapshot_ids": dict(self.snapshot_ids),
        }


@dataclass(frozen=True)
class ExperimentMetrics:
    canon_conflict_count: int
    blocker_error_count: int
    schema_success_rate: float
    first_pass_rate: float
    token_cost: int
    latency_ms: float

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "canon_conflict_count": self.canon_conflict_count,
            "blocker_error_count": self.blocker_error_count,
            "schema_success_rate": self.schema_success_rate,
            "first_pass_rate": self.first_pass_rate,
            "token_cost": self.token_cost,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True)
class TokenCost:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_amount: float
    cost_currency: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_amount": self.cost_amount,
            "cost_currency": self.cost_currency,
        }


@dataclass
class Experiment:
    id: str
    name: str
    status: str
    pin: CaseSetPin
    default_config: ExperimentConfig
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    correlation_id: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "case_set_pin": self.pin.to_public_dict(),
            "config": self.default_config.to_public_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "writes_canon": False,
            "auto_approved": False,
            "used_real_model": False,
            "is_release_gate": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "case_set_version": self.pin.version,
            "case_ids": list(self.pin.case_ids),
            "prompt_version": self.default_config.prompt_version,
            "model": self.default_config.model,
            "writes_canon": False,
            "auto_approved": False,
            "used_real_model": False,
        }


@dataclass
class ExperimentRun:
    id: str
    experiment_id: str
    status: str
    config: ExperimentConfig
    pin: CaseSetPin
    input_versions: dict[str, Any]
    output_refs: list[dict[str, Any]]
    metrics: ExperimentMetrics
    cost: TokenCost
    latency_ms: float
    duration_ms: float
    created_at: str
    finished_at: str | None
    created_by: str
    actor_type: str
    correlation_id: str | None = None
    error_code: str | None = None
    writes_canon: bool = False
    auto_approved: bool = False
    used_real_model: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "experiment_id": self.experiment_id,
            "status": self.status,
            "config": self.config.to_public_dict(),
            "input_versions": dict(self.input_versions),
            "output_refs": [dict(item) for item in self.output_refs],
            "metrics": self.metrics.to_public_dict(),
            "cost": self.cost.to_public_dict(),
            "latency_ms": self.latency_ms,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "error_code": self.error_code,
            "writes_canon": False,
            "auto_approved": False,
            "is_approval": False,
            "used_real_model": False,
            "frozen": self.status in RUN_TERMINAL_STATUSES,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "experiment_id": self.experiment_id,
            "status": self.status,
            "model": self.config.model,
            "prompt_version": self.config.prompt_version,
            "retrieval_strategy": self.config.retrieval_strategy,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "case_ids": list(self.pin.case_ids),
            "output_refs": [dict(item) for item in self.output_refs],
            "metrics": self.metrics.to_public_dict(),
            "cost": self.cost.to_public_dict(),
            "latency_ms": self.latency_ms,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "writes_canon": False,
            "auto_approved": False,
            "used_real_model": False,
        }


@dataclass
class MetricDelta:
    metric: str
    baseline: int | float
    candidate: int | float
    delta: int | float

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "delta": self.delta,
        }


@dataclass
class ExperimentComparison:
    id: str
    experiment_id: str
    baseline_run_id: str
    candidate_run_id: str
    metrics: list[MetricDelta] = field(default_factory=list)
    created_at: str = ""
    created_by: str = ""
    actor_type: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        by_name = {item.metric: item.to_public_dict() for item in self.metrics}
        return {
            "id": self.id,
            "experiment_id": self.experiment_id,
            "baseline_run_id": self.baseline_run_id,
            "candidate_run_id": self.candidate_run_id,
            "metrics": [item.to_public_dict() for item in self.metrics],
            "metrics_by_name": by_name,
            "compared_metric_names": list(COMPARE_METRICS),
            "created_at": self.created_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "writes_canon": False,
            "auto_approved": False,
            "used_real_model": False,
            "is_release_gate": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "experiment_id": self.experiment_id,
            "baseline_run_id": self.baseline_run_id,
            "candidate_run_id": self.candidate_run_id,
            "metric_names": [item.metric for item in self.metrics],
            "writes_canon": False,
            "auto_approved": False,
        }


def empty_metrics() -> ExperimentMetrics:
    return ExperimentMetrics(
        canon_conflict_count=0,
        blocker_error_count=0,
        schema_success_rate=0.0,
        first_pass_rate=0.0,
        token_cost=0,
        latency_ms=0.0,
    )


def empty_cost() -> TokenCost:
    return TokenCost(
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        cost_amount=0.0,
        cost_currency="USD",
    )
