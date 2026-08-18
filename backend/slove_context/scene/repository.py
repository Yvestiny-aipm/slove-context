"""Scene repository. Tests use the in-memory implementation."""

from __future__ import annotations

from typing import Protocol

from slove_context.scene.models import Arc, Chapter, Scene


class SceneRepository(Protocol):
    def add_arc(self, arc: Arc) -> None: ...

    def get_arc(self, arc_id: str) -> Arc | None: ...

    def list_arcs(self, project_id: str) -> list[Arc]: ...

    def add_chapter(self, chapter: Chapter) -> None: ...

    def get_chapter(self, chapter_id: str) -> Chapter | None: ...

    def add_scene(self, scene: Scene) -> None: ...

    def get_scene(self, scene_id: str) -> Scene | None: ...

    def save_scene(self, scene: Scene) -> None: ...

    def list_scenes(self, project_id: str) -> list[Scene]: ...

    def find_scene_by_order(
        self, project_id: str, story_order: int
    ) -> Scene | None: ...

    def scenes_depending_on(self, scene_id: str) -> list[Scene]: ...


class InMemorySceneRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.arcs: dict[str, Arc] = {}
        self.chapters: dict[str, Chapter] = {}
        self.scenes: dict[str, Scene] = {}

    def add_arc(self, arc: Arc) -> None:
        self.arcs[arc.id] = arc

    def get_arc(self, arc_id: str) -> Arc | None:
        return self.arcs.get(arc_id)

    def list_arcs(self, project_id: str) -> list[Arc]:
        return [item for item in self.arcs.values() if item.project_id == project_id]

    def add_chapter(self, chapter: Chapter) -> None:
        self.chapters[chapter.id] = chapter

    def get_chapter(self, chapter_id: str) -> Chapter | None:
        return self.chapters.get(chapter_id)

    def add_scene(self, scene: Scene) -> None:
        self.scenes[scene.id] = scene

    def get_scene(self, scene_id: str) -> Scene | None:
        return self.scenes.get(scene_id)

    def save_scene(self, scene: Scene) -> None:
        self.scenes[scene.id] = scene

    def list_scenes(self, project_id: str) -> list[Scene]:
        return [item for item in self.scenes.values() if item.project_id == project_id]

    def find_scene_by_order(self, project_id: str, story_order: int) -> Scene | None:
        for item in self.scenes.values():
            if item.project_id == project_id and item.story_order == story_order:
                return item
        return None

    def scenes_depending_on(self, scene_id: str) -> list[Scene]:
        return [item for item in self.scenes.values() if scene_id in item.depends_on]
