"""Experiment Run service (node 9.2).

Pins 9.1 cases, swaps Fake Provider knobs, compares to a baseline.
Does not write Canon. Does not approve. Does not call a real model.
Finished runs are immutable. Failed / cancelled rows are kept.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.evals.models import LoadedEvalCase
from slove_context.experiments.compare import compare_runs
from slove_context.experiments.constants import (
    ALLOWED_RETRIEVAL_STRATEGIES,
    CASE_SET_VERSION,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROMPT_VERSION,
    DEFAULT_RETRIEVAL_STRATEGY,
    DEFAULT_TEMPERATURE,
    EXPERIMENT_RANDOM_SEED,
)
from slove_context.experiments.export import (
    export_comparison_csv,
    export_comparison_json,
    export_run_csv,
    export_run_json,
)
from slove_context.experiments.models import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_SUCCEEDED,
    RUN_TERMINAL_STATUSES,
    STATUS_CANCELLED,
    STATUS_CREATED,
    CaseSetPin,
    Experiment,
    ExperimentComparison,
    ExperimentConfig,
    ExperimentRun,
    empty_cost,
    empty_metrics,
)
from slove_context.experiments.pin import input_versions, pin_case_set
from slove_context.experiments.repository import ExperimentRepository
from slove_context.experiments.runner import execute_run
from slove_context.llm.provider import Provider
from slove_context.logging import get_request_id
from slove_context.story.actors import Actor


class ExperimentServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class ExperimentService:
    def __init__(
        self,
        *,
        repository: ExperimentRepository,
        audit_writer: AuditWriter,
        provider: Provider,
    ) -> None:
        self._repo = repository
        self._audit = audit_writer
        self._provider = provider

    def create_experiment(
        self,
        *,
        actor: Actor,
        name: str,
        case_ids: list[str] | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        retrieval_strategy: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Experiment:
        _require_actor(actor)
        pin, _cases = _safe_pin(case_ids)
        now = _utc_now_z()
        experiment = Experiment(
            id=str(uuid4()),
            name=_require_name(name),
            status=STATUS_CREATED,
            pin=pin,
            default_config=_build_config(
                model=model,
                prompt_version=prompt_version,
                retrieval_strategy=retrieval_strategy,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            created_at=now,
            updated_at=now,
            created_by=_actor_id(actor),
            actor_type=actor.actor_type,
            correlation_id=get_request_id(),
        )
        self._repo.add_experiment(experiment)
        self._audit.write(
            actor_type=actor.actor_type or "system",
            actor_id=actor.actor_id,
            action="experiment_create",
            resource_type="experiment",
            resource_id=experiment.id,
            after_json=experiment.to_audit_dict(),
            correlation_id=experiment.correlation_id,
        )
        return experiment

    def get_experiment(self, experiment_id: str) -> Experiment:
        experiment = self._repo.get_experiment(experiment_id)
        if experiment is None:
            raise ExperimentServiceError(
                404, {"error": "experiment_not_found", "id": experiment_id}
            )
        return experiment

    def list_experiments(self) -> list[Experiment]:
        return self._repo.list_experiments()

    def update_default_prompt(
        self,
        experiment_id: str,
        *,
        actor: Actor,
        prompt_version: str,
    ) -> Experiment:
        """Unfrozen default prompt. Historical runs stay readable as-is."""
        _require_actor(actor)
        experiment = self.get_experiment(experiment_id)
        if experiment.status == STATUS_CANCELLED:
            raise ExperimentServiceError(
                409,
                {
                    "error": "experiment_cancelled",
                    "id": experiment_id,
                    "message": "Cancelled experiments are kept and not mutated.",
                },
            )
        cleaned = _require_prompt_version(prompt_version)
        before = experiment.to_audit_dict()
        experiment.default_config = ExperimentConfig(
            model=experiment.default_config.model,
            prompt_version=cleaned,
            retrieval_strategy=experiment.default_config.retrieval_strategy,
            temperature=experiment.default_config.temperature,
            max_tokens=experiment.default_config.max_tokens,
            case_set_version=experiment.default_config.case_set_version,
            random_seed=experiment.default_config.random_seed,
        )
        experiment.updated_at = _utc_now_z()
        self._repo.save_experiment(experiment)
        self._audit.write(
            actor_type=actor.actor_type or "system",
            actor_id=actor.actor_id,
            action="experiment_update_prompt_default",
            resource_type="experiment",
            resource_id=experiment.id,
            before_json=before,
            after_json=experiment.to_audit_dict(),
            correlation_id=get_request_id(),
        )
        return experiment

    def execute(
        self,
        experiment_id: str,
        *,
        actor: Actor,
        model: str | None = None,
        prompt_version: str | None = None,
        retrieval_strategy: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ExperimentRun:
        _require_actor(actor)
        experiment = self.get_experiment(experiment_id)
        if experiment.status == STATUS_CANCELLED:
            raise ExperimentServiceError(
                409,
                {
                    "error": "experiment_cancelled",
                    "id": experiment_id,
                    "message": "Cancelled experiments are kept; no new runs.",
                },
            )
        config = _build_config(
            model=model if model is not None else experiment.default_config.model,
            prompt_version=(
                prompt_version
                if prompt_version is not None
                else experiment.default_config.prompt_version
            ),
            retrieval_strategy=(
                retrieval_strategy
                if retrieval_strategy is not None
                else experiment.default_config.retrieval_strategy
            ),
            temperature=(
                temperature
                if temperature is not None
                else experiment.default_config.temperature
            ),
            max_tokens=(
                max_tokens
                if max_tokens is not None
                else experiment.default_config.max_tokens
            ),
        )
        now = _utc_now_z()
        run = ExperimentRun(
            id=str(uuid4()),
            experiment_id=experiment.id,
            status=RUN_QUEUED,
            config=config,
            pin=experiment.pin,
            input_versions=input_versions(
                experiment.pin,
                prompt_version=config.prompt_version,
                random_seed=config.random_seed,
            ),
            output_refs=[],
            metrics=empty_metrics(),
            cost=empty_cost(),
            latency_ms=0.0,
            duration_ms=0.0,
            created_at=now,
            finished_at=None,
            created_by=_actor_id(actor),
            actor_type=actor.actor_type,
            correlation_id=get_request_id(),
        )
        self._repo.add_run(run)
        try:
            execute_run(run, provider=self._provider)
            run.finished_at = _utc_now_z()
        except Exception as exc:
            run.status = RUN_FAILED
            run.error_code = type(exc).__name__
            run.finished_at = _utc_now_z()
            self._repo.save_run(run)
            self._audit.write(
                actor_type=actor.actor_type or "system",
                actor_id=actor.actor_id,
                action="experiment_run_failed",
                resource_type="experiment_run",
                resource_id=run.id,
                after_json=run.to_audit_dict(),
                correlation_id=run.correlation_id,
            )
            raise ExperimentServiceError(
                500,
                {
                    "error": "experiment_run_failed",
                    "id": run.id,
                    "code": run.error_code,
                    "kept": True,
                },
            ) from exc
        self._repo.save_run(run)
        self._audit.write(
            actor_type=actor.actor_type or "system",
            actor_id=actor.actor_id,
            action="experiment_run",
            resource_type="experiment_run",
            resource_id=run.id,
            after_json=run.to_audit_dict(),
            correlation_id=run.correlation_id,
        )
        return run

    def get_run(self, experiment_id: str, run_id: str) -> ExperimentRun:
        self.get_experiment(experiment_id)
        run = self._repo.get_run(run_id)
        if run is None or run.experiment_id != experiment_id:
            raise ExperimentServiceError(
                404, {"error": "experiment_run_not_found", "id": run_id}
            )
        return run

    def list_runs(self, experiment_id: str) -> list[ExperimentRun]:
        self.get_experiment(experiment_id)
        return self._repo.list_runs(experiment_id)

    def reject_mutate_run(self, experiment_id: str, run_id: str) -> None:
        run = self.get_run(experiment_id, run_id)
        if run.status in RUN_TERMINAL_STATUSES:
            raise ExperimentServiceError(
                409,
                {
                    "error": "experiment_run_immutable",
                    "id": run_id,
                    "status": run.status,
                    "message": (
                        "Finished experiment runs are immutable. "
                        "Change prompt_version or other knobs on a new run."
                    ),
                },
            )
        raise ExperimentServiceError(
            409,
            {
                "error": "experiment_run_immutable",
                "id": run_id,
                "message": "Experiment runs cannot be mutated in place.",
            },
        )

    def cancel_run(
        self, experiment_id: str, run_id: str, *, actor: Actor
    ) -> ExperimentRun:
        _require_actor(actor)
        run = self.get_run(experiment_id, run_id)
        if run.status in RUN_TERMINAL_STATUSES:
            raise ExperimentServiceError(
                409,
                {
                    "error": "experiment_run_terminal",
                    "id": run_id,
                    "status": run.status,
                    "message": "Terminal runs are kept and not deleted.",
                },
            )
        before = run.to_audit_dict()
        run.status = RUN_CANCELLED
        run.finished_at = _utc_now_z()
        self._repo.save_run(run)
        self._audit.write(
            actor_type=actor.actor_type or "system",
            actor_id=actor.actor_id,
            action="experiment_run_cancel",
            resource_type="experiment_run",
            resource_id=run.id,
            before_json=before,
            after_json=run.to_audit_dict(),
            correlation_id=get_request_id(),
        )
        return run

    def cancel_experiment(self, experiment_id: str, *, actor: Actor) -> Experiment:
        _require_actor(actor)
        experiment = self.get_experiment(experiment_id)
        if experiment.status == STATUS_CANCELLED:
            return experiment
        before = experiment.to_audit_dict()
        experiment.status = STATUS_CANCELLED
        experiment.updated_at = _utc_now_z()
        self._repo.save_experiment(experiment)
        self._audit.write(
            actor_type=actor.actor_type or "system",
            actor_id=actor.actor_id,
            action="experiment_cancel",
            resource_type="experiment",
            resource_id=experiment.id,
            before_json=before,
            after_json=experiment.to_audit_dict(),
            correlation_id=get_request_id(),
        )
        return experiment

    def compare(
        self,
        experiment_id: str,
        run_id: str,
        *,
        actor: Actor,
        baseline_run_id: str,
    ) -> ExperimentComparison:
        _require_actor(actor)
        candidate = self.get_run(experiment_id, run_id)
        baseline = self.get_run(experiment_id, baseline_run_id)
        if candidate.status != RUN_SUCCEEDED or baseline.status != RUN_SUCCEEDED:
            raise ExperimentServiceError(
                409,
                {
                    "error": "experiment_compare_requires_succeeded_runs",
                    "baseline_status": baseline.status,
                    "candidate_status": candidate.status,
                },
            )
        comparison = compare_runs(
            comparison_id=str(uuid4()),
            experiment_id=experiment_id,
            baseline=baseline,
            candidate=candidate,
            created_at=_utc_now_z(),
            created_by=_actor_id(actor),
            actor_type=actor.actor_type,
        )
        self._repo.add_comparison(comparison)
        self._audit.write(
            actor_type=actor.actor_type or "system",
            actor_id=actor.actor_id,
            action="experiment_compare",
            resource_type="experiment_comparison",
            resource_id=comparison.id,
            after_json=comparison.to_audit_dict(),
            correlation_id=get_request_id(),
        )
        return comparison

    def get_comparison(
        self, experiment_id: str, comparison_id: str
    ) -> ExperimentComparison:
        self.get_experiment(experiment_id)
        comparison = self._repo.get_comparison(comparison_id)
        if comparison is None or comparison.experiment_id != experiment_id:
            raise ExperimentServiceError(
                404,
                {"error": "experiment_comparison_not_found", "id": comparison_id},
            )
        return comparison

    def export_run(
        self, experiment_id: str, run_id: str, *, fmt: str
    ) -> tuple[str, str]:
        run = self.get_run(experiment_id, run_id)
        cleaned = fmt.strip().lower()
        if cleaned == "csv":
            return export_run_csv(run), "text/csv"
        if cleaned == "json":
            return export_run_json(run), "application/json"
        raise ExperimentServiceError(
            422, {"error": "unsupported_export_format", "format": fmt}
        )

    def export_comparison(
        self, experiment_id: str, comparison_id: str, *, fmt: str
    ) -> tuple[str, str]:
        comparison = self.get_comparison(experiment_id, comparison_id)
        cleaned = fmt.strip().lower()
        if cleaned == "csv":
            return export_comparison_csv(comparison), "text/csv"
        if cleaned == "json":
            return export_comparison_json(comparison), "application/json"
        raise ExperimentServiceError(
            422, {"error": "unsupported_export_format", "format": fmt}
        )

    def reject_canon_write(self, *, actor: Actor, action: str) -> None:
        self._audit.write(
            actor_type=actor.actor_type or "system",
            actor_id=actor.actor_id,
            action=f"experiment_reject_{action}_canon",
            resource_type="experiment",
            resource_id="canon-gate",
            after_json={
                "error": "experiment_cannot_write_canon",
                "action": action,
                "writes_canon": False,
                "auto_approved": False,
            },
            correlation_id=get_request_id(),
        )
        raise ExperimentServiceError(
            403,
            {
                "error": "experiment_cannot_write_canon",
                "action": action,
                "message": (
                    "Experiment runs cannot approve Candidate Changes or "
                    "submit Canon. Human submit remains the 4.2 path."
                ),
            },
        )


def _safe_pin(
    case_ids: list[str] | None,
) -> tuple[CaseSetPin, list[LoadedEvalCase]]:
    try:
        return pin_case_set(case_ids=case_ids)
    except ValueError as exc:
        raise ExperimentServiceError(
            422, {"error": "invalid_case_set_pin", "message": str(exc)}
        ) from exc


def _build_config(
    *,
    model: str | None,
    prompt_version: str | None,
    retrieval_strategy: str | None,
    temperature: float | None,
    max_tokens: int | None,
) -> ExperimentConfig:
    cleaned_model = (model or DEFAULT_MODEL).strip()
    if not cleaned_model:
        raise ExperimentServiceError(422, {"error": "model_required"})
    cleaned_prompt = _require_prompt_version(prompt_version or DEFAULT_PROMPT_VERSION)
    strategy = (retrieval_strategy or DEFAULT_RETRIEVAL_STRATEGY).strip()
    if strategy not in ALLOWED_RETRIEVAL_STRATEGIES:
        raise ExperimentServiceError(
            422,
            {
                "error": "unsupported_retrieval_strategy",
                "retrieval_strategy": strategy,
                "allowed": sorted(ALLOWED_RETRIEVAL_STRATEGIES),
                "message": (
                    "Only snapshot / pinned 9.1 fixtures are allowed. "
                    "Vector retrieval is out of scope."
                ),
            },
        )
    temp = DEFAULT_TEMPERATURE if temperature is None else float(temperature)
    if temp < 0:
        raise ExperimentServiceError(422, {"error": "temperature_must_be_gte_0"})
    tokens = DEFAULT_MAX_TOKENS if max_tokens is None else int(max_tokens)
    if tokens <= 0:
        raise ExperimentServiceError(422, {"error": "max_tokens_must_be_positive"})
    return ExperimentConfig(
        model=cleaned_model,
        prompt_version=cleaned_prompt,
        retrieval_strategy=strategy,
        temperature=temp,
        max_tokens=tokens,
        case_set_version=CASE_SET_VERSION,
        random_seed=EXPERIMENT_RANDOM_SEED,
    )


def _require_prompt_version(prompt_version: str) -> str:
    cleaned = prompt_version.strip()
    if not cleaned:
        raise ExperimentServiceError(422, {"error": "prompt_version_required"})
    return cleaned


def _require_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ExperimentServiceError(422, {"error": "name_required"})
    return cleaned


def _require_actor(actor: Actor) -> Actor:
    if not actor.actor_type:
        raise ExperimentServiceError(
            400,
            {
                "error": "actor_required",
                "message": "X-Actor-Type is required (use human_editor).",
            },
        )
    return actor


def _actor_id(actor: Actor) -> str:
    return actor.actor_id or actor.actor_type or "unknown"


def _utc_now_z() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
