"""Candidate Change / extract-job repository. Tests use in-memory."""

from __future__ import annotations

from typing import Protocol

from slove_context.candidate_change.models import CandidateChange, ExtractJob


class CandidateChangeRepository(Protocol):
    def add_job(self, job: ExtractJob) -> None: ...

    def get_job(self, job_id: str) -> ExtractJob | None: ...

    def save_job(self, job: ExtractJob) -> None: ...

    def find_job_by_idempotency_key(
        self,
        project_id: str,
        scene_id: str,
        draft_id: str,
        idempotency_key: str,
    ) -> ExtractJob | None: ...

    def add_candidate(self, candidate: CandidateChange) -> None: ...

    def get_candidate(self, candidate_id: str) -> CandidateChange | None: ...

    def save_candidate(self, candidate: CandidateChange) -> None: ...

    def list_candidates(
        self, project_id: str, scene_id: str
    ) -> list[CandidateChange]: ...

    def next_extract_batch(
        self, project_id: str, scene_id: str, draft_id: str
    ) -> int: ...


class InMemoryCandidateChangeRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.jobs: dict[str, ExtractJob] = {}
        self.candidates: dict[str, CandidateChange] = {}

    def add_job(self, job: ExtractJob) -> None:
        self.jobs[job.id] = job

    def get_job(self, job_id: str) -> ExtractJob | None:
        return self.jobs.get(job_id)

    def save_job(self, job: ExtractJob) -> None:
        self.jobs[job.id] = job

    def find_job_by_idempotency_key(
        self,
        project_id: str,
        scene_id: str,
        draft_id: str,
        idempotency_key: str,
    ) -> ExtractJob | None:
        matches = [
            job
            for job in self.jobs.values()
            if job.project_id == project_id
            and job.scene_id == scene_id
            and job.draft_id == draft_id
            and job.idempotency_key == idempotency_key
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: item.created_at)
        return matches[-1]

    def add_candidate(self, candidate: CandidateChange) -> None:
        self.candidates[candidate.id] = candidate

    def get_candidate(self, candidate_id: str) -> CandidateChange | None:
        return self.candidates.get(candidate_id)

    def save_candidate(self, candidate: CandidateChange) -> None:
        self.candidates[candidate.id] = candidate

    def list_candidates(self, project_id: str, scene_id: str) -> list[CandidateChange]:
        items = [
            item
            for item in self.candidates.values()
            if item.project_id == project_id and item.scene_id == scene_id
        ]
        items.sort(key=lambda item: (item.extract_batch, item.created_at, item.id))
        return items

    def next_extract_batch(self, project_id: str, scene_id: str, draft_id: str) -> int:
        existing = [
            item.extract_batch
            for item in self.candidates.values()
            if item.project_id == project_id
            and item.scene_id == scene_id
            and item.draft_id == draft_id
        ]
        jobs = [
            job.extract_batch
            for job in self.jobs.values()
            if job.project_id == project_id
            and job.scene_id == scene_id
            and job.draft_id == draft_id
            and job.extract_batch is not None
        ]
        values = existing + [batch for batch in jobs if batch is not None]
        if not values:
            return 1
        return max(values) + 1
