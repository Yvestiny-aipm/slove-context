"""Validation Run / Report repository. Tests use in-memory."""

from __future__ import annotations

from typing import Protocol

from slove_context.validation.models import ValidationReport, ValidationRun


class ValidationRepository(Protocol):
    def add_run(self, run: ValidationRun) -> None: ...

    def get_run(self, run_id: str) -> ValidationRun | None: ...

    def save_run(self, run: ValidationRun) -> None: ...

    def add_report(self, report: ValidationReport) -> None: ...

    def get_report(self, report_id: str) -> ValidationReport | None: ...

    def get_report_for_run(self, run_id: str) -> ValidationReport | None: ...

    def list_reports(self, project_id: str) -> list[ValidationReport]: ...

    def list_runs(self, project_id: str) -> list[ValidationRun]: ...


class InMemoryValidationRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.runs: dict[str, ValidationRun] = {}
        self.reports: dict[str, ValidationReport] = {}
        # Test-only: service treats a true flag as an in-run execution error.
        # Not an HTTP route. Not an approve / Canon write path.
        self.force_exec_fail: bool = False

    def add_run(self, run: ValidationRun) -> None:
        self.runs[run.id] = run

    def get_run(self, run_id: str) -> ValidationRun | None:
        return self.runs.get(run_id)

    def save_run(self, run: ValidationRun) -> None:
        self.runs[run.id] = run

    def add_report(self, report: ValidationReport) -> None:
        self.reports[report.id] = report

    def get_report(self, report_id: str) -> ValidationReport | None:
        return self.reports.get(report_id)

    def get_report_for_run(self, run_id: str) -> ValidationReport | None:
        matches = [item for item in self.reports.values() if item.run_id == run_id]
        if not matches:
            return None
        matches.sort(key=lambda item: item.created_at)
        return matches[-1]

    def list_reports(self, project_id: str) -> list[ValidationReport]:
        items = [
            item for item in self.reports.values() if item.project_id == project_id
        ]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def list_runs(self, project_id: str) -> list[ValidationRun]:
        items = [item for item in self.runs.values() if item.project_id == project_id]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items
