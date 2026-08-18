"""Experiment repository. Tests use in-memory. No Postgres."""

from __future__ import annotations

from typing import Protocol

from slove_context.experiments.models import (
    Experiment,
    ExperimentComparison,
    ExperimentRun,
)


class ExperimentRepository(Protocol):
    def add_experiment(self, experiment: Experiment) -> None: ...

    def get_experiment(self, experiment_id: str) -> Experiment | None: ...

    def save_experiment(self, experiment: Experiment) -> None: ...

    def list_experiments(self) -> list[Experiment]: ...

    def add_run(self, run: ExperimentRun) -> None: ...

    def get_run(self, run_id: str) -> ExperimentRun | None: ...

    def save_run(self, run: ExperimentRun) -> None: ...

    def list_runs(self, experiment_id: str) -> list[ExperimentRun]: ...

    def add_comparison(self, comparison: ExperimentComparison) -> None: ...

    def get_comparison(self, comparison_id: str) -> ExperimentComparison | None: ...

    def list_comparisons(self, experiment_id: str) -> list[ExperimentComparison]: ...


class InMemoryExperimentRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.experiments: dict[str, Experiment] = {}
        self.runs: dict[str, ExperimentRun] = {}
        self.comparisons: dict[str, ExperimentComparison] = {}

    def add_experiment(self, experiment: Experiment) -> None:
        self.experiments[experiment.id] = experiment

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        return self.experiments.get(experiment_id)

    def save_experiment(self, experiment: Experiment) -> None:
        self.experiments[experiment.id] = experiment

    def list_experiments(self) -> list[Experiment]:
        items = list(self.experiments.values())
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def add_run(self, run: ExperimentRun) -> None:
        self.runs[run.id] = run

    def get_run(self, run_id: str) -> ExperimentRun | None:
        return self.runs.get(run_id)

    def save_run(self, run: ExperimentRun) -> None:
        self.runs[run.id] = run

    def list_runs(self, experiment_id: str) -> list[ExperimentRun]:
        items = [
            item for item in self.runs.values() if item.experiment_id == experiment_id
        ]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def add_comparison(self, comparison: ExperimentComparison) -> None:
        self.comparisons[comparison.id] = comparison

    def get_comparison(self, comparison_id: str) -> ExperimentComparison | None:
        return self.comparisons.get(comparison_id)

    def list_comparisons(self, experiment_id: str) -> list[ExperimentComparison]:
        items = [
            item
            for item in self.comparisons.values()
            if item.experiment_id == experiment_id
        ]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items
