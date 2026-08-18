"""Style Validation repository. Tests use in-memory. No Postgres."""

from __future__ import annotations

from typing import Protocol

from slove_context.style_validation.models import StyleValidation


class StyleValidationRepository(Protocol):
    def add(self, run: StyleValidation) -> None: ...

    def get(self, run_id: str) -> StyleValidation | None: ...

    def save(self, run: StyleValidation) -> None: ...

    def list_for_draft(
        self, project_id: str, scene_id: str, draft_revision_id: str
    ) -> list[StyleValidation]: ...

    def list_for_project(self, project_id: str) -> list[StyleValidation]: ...


class InMemoryStyleValidationRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.runs: dict[str, StyleValidation] = {}
        # Test-only: service treats a true flag as an in-run execution error.
        # Not an HTTP route. Not an approve / Canon write path.
        self.force_fail: bool = False

    def add(self, run: StyleValidation) -> None:
        self.runs[run.id] = run

    def get(self, run_id: str) -> StyleValidation | None:
        return self.runs.get(run_id)

    def save(self, run: StyleValidation) -> None:
        self.runs[run.id] = run

    def list_for_draft(
        self, project_id: str, scene_id: str, draft_revision_id: str
    ) -> list[StyleValidation]:
        items = [
            item
            for item in self.runs.values()
            if item.project_id == project_id
            and item.scene_id == scene_id
            and item.draft_revision_id == draft_revision_id
        ]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def list_for_project(self, project_id: str) -> list[StyleValidation]:
        items = [item for item in self.runs.values() if item.project_id == project_id]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items
