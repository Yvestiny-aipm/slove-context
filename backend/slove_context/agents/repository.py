"""Agent Registry / Agent Run repository. Tests use in-memory. No Postgres."""

from __future__ import annotations

from typing import Protocol

from slove_context.agents.models import Agent, AgentRun
from slove_context.agents.registry import InMemoryAgentRepository, builtin_agents


class AgentRepository(Protocol):
    def add_agent(self, agent: Agent) -> None: ...

    def get_agent(self, agent_id: str) -> Agent | None: ...

    def list_agents(self) -> list[Agent]: ...

    def add_run(self, run: AgentRun) -> None: ...

    def get_run(self, run_id: str) -> AgentRun | None: ...

    def save_run(self, run: AgentRun) -> None: ...

    def list_runs(self, project_id: str) -> list[AgentRun]: ...


class InMemoryAgentRunRepository(InMemoryAgentRepository):
    """Fake Agent + Run store. Does not open Postgres."""

    def __init__(self, *, seed: bool = True) -> None:
        super().__init__(seed=seed)
        self.runs: dict[str, AgentRun] = {}

    def add_run(self, run: AgentRun) -> None:
        self.runs[run.id] = run

    def get_run(self, run_id: str) -> AgentRun | None:
        return self.runs.get(run_id)

    def save_run(self, run: AgentRun) -> None:
        self.runs[run.id] = run

    def list_runs(self, project_id: str) -> list[AgentRun]:
        items = [run for run in self.runs.values() if run.project_id == project_id]
        items.sort(key=lambda run: (run.created_at, run.id))
        return items


def seeded_repository() -> InMemoryAgentRunRepository:
    repo = InMemoryAgentRunRepository(seed=False)
    for agent in builtin_agents():
        repo.add_agent(agent)
    return repo
