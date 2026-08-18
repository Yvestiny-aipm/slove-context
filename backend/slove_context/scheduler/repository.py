"""Batch schedule repository. Tests use in-memory. No Postgres."""

from __future__ import annotations

from typing import Protocol

from slove_context.scheduler.models import (
    BudgetCounter,
    ScheduleAlert,
    ScheduleConfig,
    ScheduleDecision,
    ScheduleRun,
)


class ScheduleRepository(Protocol):
    def get_config(self, project_id: str) -> ScheduleConfig | None: ...

    def save_config(self, config: ScheduleConfig) -> None: ...

    def add_run(self, run: ScheduleRun) -> None: ...

    def get_run(self, run_id: str) -> ScheduleRun | None: ...

    def save_run(self, run: ScheduleRun) -> None: ...

    def list_runs(self, project_id: str) -> list[ScheduleRun]: ...

    def list_running_runs(self) -> list[ScheduleRun]: ...

    def add_decision(self, decision: ScheduleDecision) -> None: ...

    def list_decisions(
        self, project_id: str, *, run_id: str | None = None
    ) -> list[ScheduleDecision]: ...

    def add_alert(self, alert: ScheduleAlert) -> None: ...

    def list_alerts(self, project_id: str) -> list[ScheduleAlert]: ...

    def get_budget(self, project_id: str, day: str) -> BudgetCounter | None: ...

    def save_budget(self, counter: BudgetCounter) -> None: ...


class InMemoryScheduleRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.configs: dict[str, ScheduleConfig] = {}
        self.runs: dict[str, ScheduleRun] = {}
        self.decisions: dict[str, ScheduleDecision] = {}
        self.alerts: dict[str, ScheduleAlert] = {}
        self.budgets: dict[tuple[str, str], BudgetCounter] = {}

    def get_config(self, project_id: str) -> ScheduleConfig | None:
        return self.configs.get(project_id)

    def save_config(self, config: ScheduleConfig) -> None:
        self.configs[config.project_id] = config

    def add_run(self, run: ScheduleRun) -> None:
        self.runs[run.id] = run

    def get_run(self, run_id: str) -> ScheduleRun | None:
        return self.runs.get(run_id)

    def save_run(self, run: ScheduleRun) -> None:
        self.runs[run.id] = run

    def list_runs(self, project_id: str) -> list[ScheduleRun]:
        items = [item for item in self.runs.values() if item.project_id == project_id]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def list_running_runs(self) -> list[ScheduleRun]:
        from slove_context.scheduler.models import STATUS_RUNNING

        items = [item for item in self.runs.values() if item.status == STATUS_RUNNING]
        items.sort(key=lambda item: (item.project_id, item.created_at, item.id))
        return items

    def add_decision(self, decision: ScheduleDecision) -> None:
        self.decisions[decision.id] = decision

    def list_decisions(
        self, project_id: str, *, run_id: str | None = None
    ) -> list[ScheduleDecision]:
        items = [
            item
            for item in self.decisions.values()
            if item.project_id == project_id
            and (run_id is None or item.run_id == run_id)
        ]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def add_alert(self, alert: ScheduleAlert) -> None:
        self.alerts[alert.id] = alert

    def list_alerts(self, project_id: str) -> list[ScheduleAlert]:
        items = [item for item in self.alerts.values() if item.project_id == project_id]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def get_budget(self, project_id: str, day: str) -> BudgetCounter | None:
        return self.budgets.get((project_id, day))

    def save_budget(self, counter: BudgetCounter) -> None:
        self.budgets[(counter.project_id, counter.day)] = counter
