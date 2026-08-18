"""Scene Plan repository. Tests use the in-memory implementation."""

from __future__ import annotations

from typing import Protocol

from slove_context.scene_plan.models import ScenePlan, ScenePlanJob


class ScenePlanRepository(Protocol):
    def add_job(self, job: ScenePlanJob) -> None: ...

    def get_job(self, job_id: str) -> ScenePlanJob | None: ...

    def save_job(self, job: ScenePlanJob) -> None: ...

    def add_plan(self, plan: ScenePlan) -> None: ...

    def get_plan(self, plan_id: str) -> ScenePlan | None: ...

    def current_plan(self, project_id: str, scene_id: str) -> ScenePlan | None: ...


class InMemoryScenePlanRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.jobs: dict[str, ScenePlanJob] = {}
        self.plans: dict[str, ScenePlan] = {}
        self._current: dict[tuple[str, str], str] = {}

    def add_job(self, job: ScenePlanJob) -> None:
        self.jobs[job.id] = job

    def get_job(self, job_id: str) -> ScenePlanJob | None:
        return self.jobs.get(job_id)

    def save_job(self, job: ScenePlanJob) -> None:
        self.jobs[job.id] = job

    def add_plan(self, plan: ScenePlan) -> None:
        self.plans[plan.id] = plan
        self._current[(plan.project_id, plan.scene_id)] = plan.id

    def get_plan(self, plan_id: str) -> ScenePlan | None:
        return self.plans.get(plan_id)

    def current_plan(self, project_id: str, scene_id: str) -> ScenePlan | None:
        plan_id = self._current.get((project_id, scene_id))
        if plan_id is None:
            return None
        return self.plans.get(plan_id)
