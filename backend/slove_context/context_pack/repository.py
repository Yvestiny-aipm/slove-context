"""Context Pack repository. Tests use in-memory. No Postgres."""

from __future__ import annotations

from typing import Protocol

from slove_context.context_pack.models import ContextPack


class ContextPackRepository(Protocol):
    def add(self, pack: ContextPack) -> None: ...

    def get(self, pack_id: str) -> ContextPack | None: ...

    def save(self, pack: ContextPack) -> None: ...

    def list_for_scene(self, project_id: str, scene_id: str) -> list[ContextPack]: ...

    def next_revision(self, project_id: str, scene_id: str) -> int: ...


class InMemoryContextPackRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.packs: dict[str, ContextPack] = {}
        # Test-only: service treats a true flag as an assemble execution error.
        # Not an HTTP route. Not an approve / Canon write path.
        self.force_fail: bool = False

    def add(self, pack: ContextPack) -> None:
        self.packs[pack.id] = pack

    def get(self, pack_id: str) -> ContextPack | None:
        return self.packs.get(pack_id)

    def save(self, pack: ContextPack) -> None:
        self.packs[pack.id] = pack

    def list_for_scene(self, project_id: str, scene_id: str) -> list[ContextPack]:
        items = [
            pack
            for pack in self.packs.values()
            if pack.project_id == project_id and pack.scene_id == scene_id
        ]
        items.sort(key=lambda item: (item.revision, item.created_at, item.id))
        return items

    def next_revision(self, project_id: str, scene_id: str) -> int:
        existing = self.list_for_scene(project_id, scene_id)
        if not existing:
            return 1
        return max(item.revision for item in existing) + 1
