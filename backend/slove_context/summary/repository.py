"""Summary repository. Tests use the in-memory implementation."""

from __future__ import annotations

from typing import Protocol

from slove_context.summary.models import (
    SUMMARY_GENERATED,
    ChapterSummary,
    SceneSummary,
    SummaryJob,
)


class SummaryRepository(Protocol):
    def add_job(self, job: SummaryJob) -> None: ...

    def get_job(self, job_id: str) -> SummaryJob | None: ...

    def save_job(self, job: SummaryJob) -> None: ...

    def find_job_by_idempotency_key(
        self,
        project_id: str,
        kind: str,
        target_id: str,
        idempotency_key: str,
    ) -> SummaryJob | None: ...

    def add_scene_summary(self, summary: SceneSummary) -> None: ...

    def get_scene_summary(self, summary_id: str) -> SceneSummary | None: ...

    def save_scene_summary(self, summary: SceneSummary) -> None: ...

    def list_scene_summaries(
        self, project_id: str, scene_id: str
    ) -> list[SceneSummary]: ...

    def next_scene_revision(self, project_id: str, scene_id: str) -> int: ...

    def current_scene_summary(
        self, project_id: str, scene_id: str
    ) -> SceneSummary | None: ...

    def add_chapter_summary(self, summary: ChapterSummary) -> None: ...

    def get_chapter_summary(self, summary_id: str) -> ChapterSummary | None: ...

    def save_chapter_summary(self, summary: ChapterSummary) -> None: ...

    def list_chapter_summaries(
        self, project_id: str, chapter_id: str
    ) -> list[ChapterSummary]: ...

    def next_chapter_revision(self, project_id: str, chapter_id: str) -> int: ...

    def current_chapter_summary(
        self, project_id: str, chapter_id: str
    ) -> ChapterSummary | None: ...


class InMemorySummaryRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.jobs: dict[str, SummaryJob] = {}
        self.scene_summaries: dict[str, SceneSummary] = {}
        self.chapter_summaries: dict[str, ChapterSummary] = {}

    def add_job(self, job: SummaryJob) -> None:
        self.jobs[job.id] = job

    def get_job(self, job_id: str) -> SummaryJob | None:
        return self.jobs.get(job_id)

    def save_job(self, job: SummaryJob) -> None:
        self.jobs[job.id] = job

    def find_job_by_idempotency_key(
        self,
        project_id: str,
        kind: str,
        target_id: str,
        idempotency_key: str,
    ) -> SummaryJob | None:
        matches = [
            job
            for job in self.jobs.values()
            if job.project_id == project_id
            and job.kind == kind
            and job.idempotency_key == idempotency_key
            and (
                (kind == "scene" and job.scene_id == target_id)
                or (kind == "chapter" and job.chapter_id == target_id)
            )
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: item.created_at)
        return matches[-1]

    def add_scene_summary(self, summary: SceneSummary) -> None:
        self.scene_summaries[summary.id] = summary

    def get_scene_summary(self, summary_id: str) -> SceneSummary | None:
        return self.scene_summaries.get(summary_id)

    def save_scene_summary(self, summary: SceneSummary) -> None:
        self.scene_summaries[summary.id] = summary

    def list_scene_summaries(
        self, project_id: str, scene_id: str
    ) -> list[SceneSummary]:
        items = [
            item
            for item in self.scene_summaries.values()
            if item.project_id == project_id and item.scene_id == scene_id
        ]
        items.sort(key=lambda item: item.revision, reverse=True)
        return items

    def next_scene_revision(self, project_id: str, scene_id: str) -> int:
        existing = self.list_scene_summaries(project_id, scene_id)
        if not existing:
            return 1
        return max(item.revision for item in existing) + 1

    def current_scene_summary(
        self, project_id: str, scene_id: str
    ) -> SceneSummary | None:
        for item in self.list_scene_summaries(project_id, scene_id):
            if item.status == SUMMARY_GENERATED:
                return item
        return None

    def add_chapter_summary(self, summary: ChapterSummary) -> None:
        self.chapter_summaries[summary.id] = summary

    def get_chapter_summary(self, summary_id: str) -> ChapterSummary | None:
        return self.chapter_summaries.get(summary_id)

    def save_chapter_summary(self, summary: ChapterSummary) -> None:
        self.chapter_summaries[summary.id] = summary

    def list_chapter_summaries(
        self, project_id: str, chapter_id: str
    ) -> list[ChapterSummary]:
        items = [
            item
            for item in self.chapter_summaries.values()
            if item.project_id == project_id and item.chapter_id == chapter_id
        ]
        items.sort(key=lambda item: item.revision, reverse=True)
        return items

    def next_chapter_revision(self, project_id: str, chapter_id: str) -> int:
        existing = self.list_chapter_summaries(project_id, chapter_id)
        if not existing:
            return 1
        return max(item.revision for item in existing) + 1

    def current_chapter_summary(
        self, project_id: str, chapter_id: str
    ) -> ChapterSummary | None:
        for item in self.list_chapter_summaries(project_id, chapter_id):
            if item.status == SUMMARY_GENERATED:
                return item
        return None
