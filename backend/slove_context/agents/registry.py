"""Built-in Agent Registry (node 8.2).

In-memory / fake. Seven agents are registered with frozen permission
boundaries. Code enum names may map; semantics stay. No chat. Agents
do not mutate each others' stores.
"""

from __future__ import annotations

from typing import Protocol

from slove_context.agents.models import (
    ACTION_APPROVE,
    ACTION_APPROVE_CANON,
    ACTION_BYPASS_APPROVAL,
    ACTION_CREATE_CANON_FACT,
    ACTION_ESCALATE,
    ACTION_GENERATE_DRAFT,
    ACTION_PRODUCE_DRAFT_REVISION,
    ACTION_PRODUCE_STYLE_REPORT,
    ACTION_PRODUCE_VALIDATION_REPORT,
    ACTION_PROPOSE_CANDIDATE_CHANGE,
    ACTION_PROPOSE_OUTLINE,
    ACTION_PROPOSE_SCENE_PLAN,
    ACTION_REJECT,
    ACTION_REQUEST_REVISION,
    ACTION_SUBMIT_CANON,
    ACTION_WRITE_CANON,
    ACTION_WRITE_DRAFT,
    AGENT_CONSISTENCY,
    AGENT_DRAFT,
    AGENT_EXTRACTOR,
    AGENT_HUMAN_APPROVER,
    AGENT_OUTLINE,
    AGENT_REPAIR,
    AGENT_STYLE,
    OUTPUT_APPROVAL_DECISION,
    OUTPUT_CANDIDATE_CHANGE,
    OUTPUT_DRAFT_REVISION,
    OUTPUT_OUTLINE,
    OUTPUT_SCENE_DRAFT,
    OUTPUT_SCENE_PLAN,
    OUTPUT_STYLE_REPORT,
    OUTPUT_VALIDATION_REPORT,
    Agent,
    normalize_agent_id,
)

_CREATED_AT = "2026-08-18T00:00:00.000000Z"

_SHARED_FORBIDDEN = frozenset(
    {
        ACTION_WRITE_CANON,
        ACTION_SUBMIT_CANON,
        ACTION_BYPASS_APPROVAL,
        ACTION_CREATE_CANON_FACT,
        ACTION_APPROVE,
        ACTION_APPROVE_CANON,
    }
)


def _schema(name: str, contract: str | None, fields: list[str]) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": name,
        "type": "object",
        "required": fields,
        "properties": {field: {"type": "string"} for field in fields},
    }
    if contract:
        payload["contract"] = contract
    return payload


def _fake_model(model: str) -> dict[str, object]:
    return {
        "provider": "fake",
        "model": model,
        "temperature": 0.0,
        "max_tokens": 1024,
        "real_http": False,
    }


def _cost_cap(
    *, max_tokens: int = 4096, max_cost_usd: float = 0.5
) -> dict[str, object]:
    return {"max_tokens": max_tokens, "max_cost_usd": max_cost_usd}


def builtin_agents() -> list[Agent]:
    return [
        Agent(
            id=AGENT_OUTLINE,
            name="Outline Agent",
            input_schema=_schema(
                "OutlineAgentInput",
                "contracts/scene-plan.schema.json",
                ["project_id", "input_ref"],
            ),
            output_schema=_schema(
                "OutlineAgentOutput",
                "contracts/scene-plan.schema.json",
                ["output_type", "output_ref"],
            ),
            allowed_tools=frozenset(
                {ACTION_PROPOSE_OUTLINE, ACTION_PROPOSE_SCENE_PLAN}
            ),
            forbidden_operations=_SHARED_FORBIDDEN
            | {ACTION_WRITE_DRAFT, ACTION_GENERATE_DRAFT},
            model_config=_fake_model("fake-outline-v1"),
            prompt_version="scene_plan.v1",
            timeout_s=30.0,
            cost_cap=_cost_cap(),
            allowed_output_types=frozenset({OUTPUT_OUTLINE, OUTPUT_SCENE_PLAN}),
            created_at=_CREATED_AT,
        ),
        Agent(
            id=AGENT_DRAFT,
            name="Draft Agent",
            input_schema=_schema(
                "DraftAgentInput",
                "contracts/scene-card.schema.json",
                ["project_id", "input_ref"],
            ),
            output_schema=_schema(
                "DraftAgentOutput",
                None,
                ["output_type", "output_ref"],
            ),
            allowed_tools=frozenset({ACTION_GENERATE_DRAFT}),
            forbidden_operations=_SHARED_FORBIDDEN
            | {
                ACTION_PROPOSE_OUTLINE,
                ACTION_PROPOSE_SCENE_PLAN,
                ACTION_PROPOSE_CANDIDATE_CHANGE,
                ACTION_WRITE_DRAFT,
            },
            model_config=_fake_model("fake-draft-v1"),
            prompt_version="scene_draft.v1",
            timeout_s=30.0,
            cost_cap=_cost_cap(),
            allowed_output_types=frozenset({OUTPUT_SCENE_DRAFT}),
            created_at=_CREATED_AT,
        ),
        Agent(
            id=AGENT_EXTRACTOR,
            name="Extractor Agent",
            input_schema=_schema(
                "ExtractorAgentInput",
                "contracts/candidate-change.schema.json",
                ["project_id", "input_ref"],
            ),
            output_schema=_schema(
                "ExtractorAgentOutput",
                "contracts/candidate-change.schema.json",
                ["output_type", "output_ref"],
            ),
            allowed_tools=frozenset({ACTION_PROPOSE_CANDIDATE_CHANGE}),
            forbidden_operations=_SHARED_FORBIDDEN
            | {
                ACTION_GENERATE_DRAFT,
                ACTION_PRODUCE_VALIDATION_REPORT,
            },
            model_config=_fake_model("fake-extract-v1"),
            prompt_version="extract_candidates.v1",
            timeout_s=30.0,
            cost_cap=_cost_cap(),
            allowed_output_types=frozenset({OUTPUT_CANDIDATE_CHANGE}),
            created_at=_CREATED_AT,
        ),
        Agent(
            id=AGENT_CONSISTENCY,
            name="Consistency Agent",
            input_schema=_schema(
                "ConsistencyAgentInput",
                "contracts/validation-report.schema.json",
                ["project_id", "input_ref"],
            ),
            output_schema=_schema(
                "ConsistencyAgentOutput",
                "contracts/validation-report.schema.json",
                ["output_type", "output_ref"],
            ),
            allowed_tools=frozenset({ACTION_PRODUCE_VALIDATION_REPORT}),
            forbidden_operations=_SHARED_FORBIDDEN
            | {ACTION_GENERATE_DRAFT, ACTION_PROPOSE_CANDIDATE_CHANGE},
            model_config=_fake_model("fake-validate-v1"),
            prompt_version=None,
            timeout_s=15.0,
            cost_cap=_cost_cap(max_tokens=0, max_cost_usd=0.0),
            allowed_output_types=frozenset({OUTPUT_VALIDATION_REPORT}),
            created_at=_CREATED_AT,
        ),
        Agent(
            id=AGENT_STYLE,
            name="Style Agent",
            input_schema=_schema(
                "StyleAgentInput",
                None,
                ["project_id", "input_ref"],
            ),
            output_schema=_schema(
                "StyleAgentOutput",
                None,
                ["output_type", "output_ref"],
            ),
            allowed_tools=frozenset({ACTION_PRODUCE_STYLE_REPORT}),
            forbidden_operations=_SHARED_FORBIDDEN
            | {ACTION_GENERATE_DRAFT, ACTION_PROPOSE_CANDIDATE_CHANGE},
            model_config=_fake_model("fake-style-v1"),
            prompt_version="style_validation.v1",
            timeout_s=20.0,
            cost_cap=_cost_cap(),
            allowed_output_types=frozenset({OUTPUT_STYLE_REPORT}),
            created_at=_CREATED_AT,
        ),
        Agent(
            id=AGENT_REPAIR,
            name="Repair Agent",
            input_schema=_schema(
                "RepairAgentInput",
                None,
                ["project_id", "input_ref"],
            ),
            output_schema=_schema(
                "RepairAgentOutput",
                None,
                ["output_type", "output_ref"],
            ),
            allowed_tools=frozenset({ACTION_PRODUCE_DRAFT_REVISION}),
            forbidden_operations=_SHARED_FORBIDDEN
            | {ACTION_PROPOSE_CANDIDATE_CHANGE, ACTION_WRITE_DRAFT},
            model_config=_fake_model("fake-repair-v1"),
            prompt_version="scene_draft.v1",
            timeout_s=30.0,
            cost_cap=_cost_cap(),
            allowed_output_types=frozenset({OUTPUT_DRAFT_REVISION}),
            created_at=_CREATED_AT,
        ),
        Agent(
            id=AGENT_HUMAN_APPROVER,
            name="Human Approver",
            input_schema=_schema(
                "HumanApproverInput",
                "contracts/approval-decision.schema.json",
                ["project_id", "input_ref"],
            ),
            output_schema=_schema(
                "HumanApproverOutput",
                "contracts/approval-decision.schema.json",
                ["output_type", "output_ref"],
            ),
            allowed_tools=frozenset(
                {
                    ACTION_APPROVE_CANON,
                    ACTION_APPROVE,
                    ACTION_REJECT,
                    ACTION_REQUEST_REVISION,
                    ACTION_ESCALATE,
                }
            ),
            forbidden_operations=frozenset(
                {
                    ACTION_WRITE_CANON,
                    ACTION_SUBMIT_CANON,
                    ACTION_BYPASS_APPROVAL,
                    ACTION_CREATE_CANON_FACT,
                    ACTION_GENERATE_DRAFT,
                    ACTION_WRITE_DRAFT,
                    ACTION_PROPOSE_OUTLINE,
                    ACTION_PROPOSE_SCENE_PLAN,
                    ACTION_PROPOSE_CANDIDATE_CHANGE,
                    ACTION_PRODUCE_VALIDATION_REPORT,
                    ACTION_PRODUCE_STYLE_REPORT,
                    ACTION_PRODUCE_DRAFT_REVISION,
                }
            ),
            model_config={
                "provider": None,
                "model": None,
                "temperature": None,
                "max_tokens": 0,
                "real_http": False,
                "note": "human_only_no_model",
            },
            prompt_version=None,
            timeout_s=0.0,
            cost_cap=_cost_cap(max_tokens=0, max_cost_usd=0.0),
            allowed_output_types=frozenset({OUTPUT_APPROVAL_DECISION}),
            created_at=_CREATED_AT,
        ),
    ]


class AgentRegistry(Protocol):
    def get_agent(self, agent_id: str) -> Agent | None: ...

    def list_agents(self) -> list[Agent]: ...

    def add_agent(self, agent: Agent) -> None: ...


class InMemoryAgentRepository:
    """Fake registry. Seeds the seven built-in agents. No Postgres."""

    def __init__(self, *, seed: bool = True) -> None:
        self.agents: dict[str, Agent] = {}
        if seed:
            self.seed_builtin()

    def seed_builtin(self) -> None:
        for agent in builtin_agents():
            self.agents[agent.id] = agent

    def add_agent(self, agent: Agent) -> None:
        self.agents[agent.id] = agent

    def get_agent(self, agent_id: str) -> Agent | None:
        mapped = normalize_agent_id(agent_id) or agent_id
        return self.agents.get(mapped)

    def list_agents(self) -> list[Agent]:
        items = list(self.agents.values())
        items.sort(key=lambda agent: agent.id)
        return items


_BUILTIN_SINGLETON: InMemoryAgentRepository | None = None


def builtin_registry() -> InMemoryAgentRepository:
    global _BUILTIN_SINGLETON
    if _BUILTIN_SINGLETON is None:
        _BUILTIN_SINGLETON = InMemoryAgentRepository(seed=True)
    return _BUILTIN_SINGLETON
