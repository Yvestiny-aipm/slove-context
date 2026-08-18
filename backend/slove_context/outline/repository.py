"""Outline Revision repository. Tests use in-memory. No Postgres."""

from __future__ import annotations

from typing import Protocol

from slove_context.outline.models import OutlineRevision


class OutlineRepository(Protocol):
    def add(self, revision: OutlineRevision) -> None: ...

    def get(self, revision_id: str) -> OutlineRevision | None: ...

    def save(self, revision: OutlineRevision) -> None: ...

    def list_for_project(self, project_id: str) -> list[OutlineRevision]: ...

    def list_for_lineage(self, lineage_id: str) -> list[OutlineRevision]: ...

    def next_revision(self, lineage_id: str) -> int: ...


class InMemoryOutlineRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.revisions: dict[str, OutlineRevision] = {}
        # Test-only: service treats a true flag as a save/draft execution error.
        # Not an HTTP route. Not an approve / Canon write path.
        self.force_fail: bool = False

    def add(self, revision: OutlineRevision) -> None:
        self.revisions[revision.id] = revision

    def get(self, revision_id: str) -> OutlineRevision | None:
        return self.revisions.get(revision_id)

    def save(self, revision: OutlineRevision) -> None:
        self.revisions[revision.id] = revision

    def list_for_project(self, project_id: str) -> list[OutlineRevision]:
        items = [
            item for item in self.revisions.values() if item.project_id == project_id
        ]
        items.sort(key=lambda item: (-item.revision, item.created_at, item.id))
        return items

    def list_for_lineage(self, lineage_id: str) -> list[OutlineRevision]:
        items = [
            item for item in self.revisions.values() if item.lineage_id == lineage_id
        ]
        items.sort(key=lambda item: (item.revision, item.created_at, item.id))
        return items

    def next_revision(self, lineage_id: str) -> int:
        existing = self.list_for_lineage(lineage_id)
        if not existing:
            return 1
        return max(item.revision for item in existing) + 1
