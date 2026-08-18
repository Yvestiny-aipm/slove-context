"""Style Guide / Style Sample repository. Tests use in-memory. No Postgres."""

from __future__ import annotations

from typing import Protocol

from slove_context.style.models import StyleGuide, StyleSample


class StyleRepository(Protocol):
    def add_guide(self, guide: StyleGuide) -> None: ...

    def get_guide(self, guide_id: str) -> StyleGuide | None: ...

    def save_guide(self, guide: StyleGuide) -> None: ...

    def list_guides(self, project_id: str) -> list[StyleGuide]: ...

    def list_guides_for_lineage(self, lineage_id: str) -> list[StyleGuide]: ...

    def next_guide_revision(self, lineage_id: str) -> int: ...

    def add_sample(self, sample: StyleSample) -> None: ...

    def get_sample(self, sample_id: str) -> StyleSample | None: ...

    def save_sample(self, sample: StyleSample) -> None: ...

    def list_samples(self, project_id: str) -> list[StyleSample]: ...

    def list_samples_for_lineage(self, lineage_id: str) -> list[StyleSample]: ...

    def next_sample_revision(self, lineage_id: str) -> int: ...


class InMemoryStyleRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.guides: dict[str, StyleGuide] = {}
        self.samples: dict[str, StyleSample] = {}
        # Test-only: service treats a true flag as a save/draft execution error.
        # Not an HTTP route. Not an approve / Canon write path.
        self.force_fail: bool = False

    def add_guide(self, guide: StyleGuide) -> None:
        self.guides[guide.id] = guide

    def get_guide(self, guide_id: str) -> StyleGuide | None:
        return self.guides.get(guide_id)

    def save_guide(self, guide: StyleGuide) -> None:
        self.guides[guide.id] = guide

    def list_guides(self, project_id: str) -> list[StyleGuide]:
        items = [item for item in self.guides.values() if item.project_id == project_id]
        items.sort(key=lambda item: (-item.revision, item.created_at, item.id))
        return items

    def list_guides_for_lineage(self, lineage_id: str) -> list[StyleGuide]:
        items = [item for item in self.guides.values() if item.lineage_id == lineage_id]
        items.sort(key=lambda item: (item.revision, item.created_at, item.id))
        return items

    def next_guide_revision(self, lineage_id: str) -> int:
        existing = self.list_guides_for_lineage(lineage_id)
        if not existing:
            return 1
        return max(item.revision for item in existing) + 1

    def add_sample(self, sample: StyleSample) -> None:
        self.samples[sample.id] = sample

    def get_sample(self, sample_id: str) -> StyleSample | None:
        return self.samples.get(sample_id)

    def save_sample(self, sample: StyleSample) -> None:
        self.samples[sample.id] = sample

    def list_samples(self, project_id: str) -> list[StyleSample]:
        items = [
            item for item in self.samples.values() if item.project_id == project_id
        ]
        items.sort(key=lambda item: (-item.revision, item.created_at, item.id))
        return items

    def list_samples_for_lineage(self, lineage_id: str) -> list[StyleSample]:
        items = [
            item for item in self.samples.values() if item.lineage_id == lineage_id
        ]
        items.sort(key=lambda item: (item.revision, item.created_at, item.id))
        return items

    def next_sample_revision(self, lineage_id: str) -> int:
        existing = self.list_samples_for_lineage(lineage_id)
        if not existing:
            return 1
        return max(item.revision for item in existing) + 1
