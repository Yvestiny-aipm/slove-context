"""Repair Task repository. Tests use in-memory."""

from __future__ import annotations

from typing import Protocol

from slove_context.repair.models import RepairTask


class RepairRepository(Protocol):
    def add_task(self, task: RepairTask) -> None: ...

    def get_task(self, task_id: str) -> RepairTask | None: ...

    def save_task(self, task: RepairTask) -> None: ...

    def list_tasks(
        self, project_id: str, *, validation_run_id: str | None = None
    ) -> list[RepairTask]: ...


class InMemoryRepairRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.tasks: dict[str, RepairTask] = {}

    def add_task(self, task: RepairTask) -> None:
        self.tasks[task.id] = task

    def get_task(self, task_id: str) -> RepairTask | None:
        return self.tasks.get(task_id)

    def save_task(self, task: RepairTask) -> None:
        self.tasks[task.id] = task

    def list_tasks(
        self, project_id: str, *, validation_run_id: str | None = None
    ) -> list[RepairTask]:
        items = [item for item in self.tasks.values() if item.project_id == project_id]
        if validation_run_id is not None:
            items = [
                item for item in items if item.validation_run_id == validation_run_id
            ]
        items.sort(key=lambda item: item.created_at)
        return items
