"""Story Project / Spec repository. Tests use the in-memory implementation."""

from __future__ import annotations

from typing import Protocol

from slove_context.story.models import StoryProject, StorySpec


class StoryRepository(Protocol):
    def list_projects(self) -> list[StoryProject]: ...

    def get_project(self, project_id: str) -> StoryProject | None: ...

    def add_project(self, project: StoryProject) -> None: ...

    def get_spec(self, spec_id: str) -> StorySpec | None: ...

    def get_spec_for_project(self, project_id: str) -> StorySpec | None: ...

    def add_spec(self, spec: StorySpec) -> None: ...

    def save_spec(self, spec: StorySpec) -> None: ...


class InMemoryStoryRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.projects: dict[str, StoryProject] = {}
        self.specs: dict[str, StorySpec] = {}

    def list_projects(self) -> list[StoryProject]:
        return list(self.projects.values())

    def get_project(self, project_id: str) -> StoryProject | None:
        return self.projects.get(project_id)

    def add_project(self, project: StoryProject) -> None:
        self.projects[project.id] = project

    def get_spec(self, spec_id: str) -> StorySpec | None:
        return self.specs.get(spec_id)

    def get_spec_for_project(self, project_id: str) -> StorySpec | None:
        for spec in self.specs.values():
            if spec.project_id == project_id:
                return spec
        return None

    def add_spec(self, spec: StorySpec) -> None:
        self.specs[spec.id] = spec

    def save_spec(self, spec: StorySpec) -> None:
        self.specs[spec.id] = spec
