"""Job queue repository. Tests use in-memory. No Postgres."""

from __future__ import annotations

from typing import Protocol

from slove_context.jobs.models import Job, JobLock, JobPayload


class JobRepository(Protocol):
    def add_job(self, job: Job) -> None: ...

    def get_job(self, job_id: str) -> Job | None: ...

    def save_job(self, job: Job) -> None: ...

    def list_jobs(
        self,
        project_id: str,
        *,
        status: str | None = None,
        job_type: str | None = None,
        scene_id: str | None = None,
    ) -> list[Job]: ...

    def list_by_status(self, status: str) -> list[Job]: ...

    def find_by_idempotency_key(
        self, project_id: str, job_type: str, idempotency_key: str
    ) -> Job | None: ...

    def add_payload(self, payload: JobPayload) -> None: ...

    def get_payload(self, payload_id: str) -> JobPayload | None: ...

    def get_lock(self, scene_id: str) -> JobLock | None: ...

    def save_lock(self, lock: JobLock) -> None: ...

    def delete_lock(self, scene_id: str, job_id: str) -> None: ...


class InMemoryJobRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.payloads: dict[str, JobPayload] = {}
        self.locks: dict[str, JobLock] = {}

    def add_job(self, job: Job) -> None:
        self.jobs[job.id] = job

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def save_job(self, job: Job) -> None:
        self.jobs[job.id] = job

    def list_jobs(
        self,
        project_id: str,
        *,
        status: str | None = None,
        job_type: str | None = None,
        scene_id: str | None = None,
    ) -> list[Job]:
        items = [job for job in self.jobs.values() if job.project_id == project_id]
        if status is not None:
            items = [job for job in items if job.status == status]
        if job_type is not None:
            items = [job for job in items if job.job_type == job_type]
        if scene_id is not None:
            items = [job for job in items if job.scene_id == scene_id]
        items.sort(key=lambda job: (job.created_at, job.id))
        return items

    def list_by_status(self, status: str) -> list[Job]:
        items = [job for job in self.jobs.values() if job.status == status]
        items.sort(key=lambda job: (job.scheduled_at, job.id))
        return items

    def find_by_idempotency_key(
        self, project_id: str, job_type: str, idempotency_key: str
    ) -> Job | None:
        matches = [
            job
            for job in self.jobs.values()
            if job.project_id == project_id
            and job.job_type == job_type
            and job.idempotency_key == idempotency_key
        ]
        if not matches:
            return None
        matches.sort(key=lambda job: job.created_at)
        return matches[-1]

    def add_payload(self, payload: JobPayload) -> None:
        self.payloads[payload.id] = payload

    def get_payload(self, payload_id: str) -> JobPayload | None:
        return self.payloads.get(payload_id)

    def get_lock(self, scene_id: str) -> JobLock | None:
        return self.locks.get(scene_id)

    def save_lock(self, lock: JobLock) -> None:
        self.locks[lock.scene_id] = lock

    def delete_lock(self, scene_id: str, job_id: str) -> None:
        existing = self.locks.get(scene_id)
        if existing is not None and existing.job_id == job_id:
            del self.locks[scene_id]
