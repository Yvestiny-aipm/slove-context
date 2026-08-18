"""Scene Draft repository. Tests use the in-memory implementation."""

from __future__ import annotations

from typing import Protocol

from slove_context.scene_draft.models import DRAFT_GENERATED, SceneDraft, SceneDraftJob


class SceneDraftRepository(Protocol):
    def add_job(self, job: SceneDraftJob) -> None: ...

    def get_job(self, job_id: str) -> SceneDraftJob | None: ...

    def save_job(self, job: SceneDraftJob) -> None: ...

    def find_job_by_idempotency_key(
        self, project_id: str, scene_id: str, idempotency_key: str
    ) -> SceneDraftJob | None: ...

    def add_draft(self, draft: SceneDraft) -> None: ...

    def get_draft(self, draft_id: str) -> SceneDraft | None: ...

    def save_draft(self, draft: SceneDraft) -> None: ...

    def list_drafts(self, project_id: str, scene_id: str) -> list[SceneDraft]: ...

    def next_revision(self, project_id: str, scene_id: str) -> int: ...

    def current_generated_draft(
        self, project_id: str, scene_id: str
    ) -> SceneDraft | None: ...


class InMemorySceneDraftRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.jobs: dict[str, SceneDraftJob] = {}
        self.drafts: dict[str, SceneDraft] = {}

    def add_job(self, job: SceneDraftJob) -> None:
        self.jobs[job.id] = job

    def get_job(self, job_id: str) -> SceneDraftJob | None:
        return self.jobs.get(job_id)

    def save_job(self, job: SceneDraftJob) -> None:
        self.jobs[job.id] = job

    def find_job_by_idempotency_key(
        self, project_id: str, scene_id: str, idempotency_key: str
    ) -> SceneDraftJob | None:
        matches = [
            job
            for job in self.jobs.values()
            if job.project_id == project_id
            and job.scene_id == scene_id
            and job.idempotency_key == idempotency_key
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: item.created_at)
        return matches[-1]

    def add_draft(self, draft: SceneDraft) -> None:
        self.drafts[draft.id] = draft

    def get_draft(self, draft_id: str) -> SceneDraft | None:
        return self.drafts.get(draft_id)

    def save_draft(self, draft: SceneDraft) -> None:
        self.drafts[draft.id] = draft

    def list_drafts(self, project_id: str, scene_id: str) -> list[SceneDraft]:
        items = [
            draft
            for draft in self.drafts.values()
            if draft.project_id == project_id and draft.scene_id == scene_id
        ]
        items.sort(key=lambda item: item.revision, reverse=True)
        return items

    def next_revision(self, project_id: str, scene_id: str) -> int:
        existing = self.list_drafts(project_id, scene_id)
        if not existing:
            return 1
        return max(item.revision for item in existing) + 1

    def current_generated_draft(
        self, project_id: str, scene_id: str
    ) -> SceneDraft | None:
        for draft in self.list_drafts(project_id, scene_id):
            if draft.status == DRAFT_GENERATED:
                return draft
        return None
