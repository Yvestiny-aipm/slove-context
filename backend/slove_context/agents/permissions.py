"""Service-layer permission re-check (node 8.2).

Do not trust Agent Prompt text. Worker dispatch and review / approval
paths call assert_allowed / assert_actor_may_*. Unauthorized work is
403. No Agent, Worker, or system actor may bypass Approval to write
Canon. Only Human Approver (human 主编) may approve Canon.
"""

from __future__ import annotations

from typing import Any

from slove_context.agents.models import (
    ACTION_APPROVE_CANON,
    ACTION_SUBMIT_CANON,
    AGENT_HUMAN_APPROVER,
    AGENT_IDS,
    APPROVE_ACTIONS,
    CANON_WRITE_ACTIONS,
    JOB_TYPE_TO_ACTION,
    JOB_TYPE_TO_AGENT,
    OUTPUT_TYPE_FOR_ACTION,
    Agent,
    normalize_action,
    normalize_agent_id,
)
from slove_context.agents.registry import AgentRegistry, builtin_registry
from slove_context.story.actors import (
    HUMAN_EDITOR,
    SYSTEM,
    Actor,
    ActorError,
    require_human_editor,
)


class PermissionDenied(Exception):
    """Unauthorized Agent action. Callers map this to HTTP 403."""

    def __init__(
        self,
        detail: dict[str, Any],
        *,
        status_code: int = 403,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class PermissionGuard:
    """Re-check Agent permissions. Prompt text is not an authority."""

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self._registry = registry or builtin_registry()

    def assert_allowed(self, agent: Agent | str, action: str) -> Agent:
        record = self._resolve_agent(agent)
        cleaned = normalize_action(action)
        if cleaned is None:
            raise PermissionDenied(
                {
                    "error": "agent_permission_denied",
                    "message": "An explicit tool / action is required.",
                    "agent_id": record.id,
                }
            )
        if cleaned in CANON_WRITE_ACTIONS:
            raise PermissionDenied(
                {
                    "error": "agent_cannot_write_canon",
                    "message": (
                        "No Agent (including Worker / system) may bypass "
                        "Approval to write Canon. Canon write remains "
                        "4.2 human submit only."
                    ),
                    "agent_id": record.id,
                    "action": cleaned,
                }
            )
        if cleaned in APPROVE_ACTIONS and record.id != AGENT_HUMAN_APPROVER:
            raise PermissionDenied(
                {
                    "error": "agent_cannot_approve",
                    "message": (
                        "Anyone other than Human Approver cannot approve. "
                        "Only the human 主编 may approve Canon."
                    ),
                    "agent_id": record.id,
                    "action": cleaned,
                }
            )
        if cleaned in record.forbidden_operations:
            raise PermissionDenied(
                {
                    "error": "agent_permission_denied",
                    "message": (
                        f"Agent '{record.id}' is forbidden from '{cleaned}'. "
                        "Service-layer permission re-check rejected this call."
                    ),
                    "agent_id": record.id,
                    "action": cleaned,
                    "forbidden_operations": sorted(record.forbidden_operations),
                }
            )
        if cleaned not in record.allowed_tools:
            raise PermissionDenied(
                {
                    "error": "agent_permission_denied",
                    "message": (
                        f"Agent '{record.id}' is not allowed to '{cleaned}'. "
                        "Do not trust Agent Prompt; the service re-checks."
                    ),
                    "agent_id": record.id,
                    "action": cleaned,
                    "allowed_tools": sorted(record.allowed_tools),
                    "allowed_output_types": sorted(record.allowed_output_types),
                }
            )
        output_type = OUTPUT_TYPE_FOR_ACTION.get(cleaned)
        if output_type is not None and output_type not in record.allowed_output_types:
            raise PermissionDenied(
                {
                    "error": "agent_output_type_denied",
                    "message": (
                        f"Agent '{record.id}' may only produce "
                        f"{sorted(record.allowed_output_types)}."
                    ),
                    "agent_id": record.id,
                    "action": cleaned,
                    "output_type": output_type,
                }
            )
        return record

    def assert_job_dispatch_allowed(self, job_type: str) -> Agent | None:
        """Worker maps job_type → agent and re-checks. No approve / submit."""
        lowered = job_type.strip().lower()
        if lowered in CANON_WRITE_ACTIONS or lowered in APPROVE_ACTIONS:
            raise PermissionDenied(
                {
                    "error": "worker_cannot_write_canon",
                    "message": (
                        "Worker must not approve Candidate Changes or "
                        "submit Canon. No Agent bypasses Approval."
                    ),
                    "job_type": job_type,
                }
            )
        agent_id = JOB_TYPE_TO_AGENT.get(lowered)
        action = JOB_TYPE_TO_ACTION.get(lowered)
        if agent_id is None or action is None:
            return None
        return self.assert_allowed(agent_id, action)

    def assert_actor_may_approve_canon(self, actor: Actor) -> Agent:
        try:
            require_human_editor(actor, action="approve", resource="Canon")
        except ActorError as exc:
            raise PermissionDenied(
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                    "actor_type": actor.actor_type or None,
                }
            ) from exc
        if actor.actor_type == SYSTEM:
            raise PermissionDenied(
                {
                    "error": "agent_cannot_approve",
                    "message": "Worker / system cannot approve Canon.",
                    "actor_type": actor.actor_type,
                }
            )
        return self.assert_allowed(AGENT_HUMAN_APPROVER, ACTION_APPROVE_CANON)

    def assert_actor_may_submit_canon(self, actor: Actor) -> None:
        """4.2 human submit only. Agents / Worker cannot submit."""
        try:
            require_human_editor(actor, action="submit", resource="Canon")
        except ActorError as exc:
            raise PermissionDenied(
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                    "actor_type": actor.actor_type or None,
                }
            ) from exc
        actor_id = (actor.actor_id or "").strip()
        mapped = normalize_agent_id(actor_id)
        if mapped in AGENT_IDS and mapped != AGENT_HUMAN_APPROVER:
            raise PermissionDenied(
                {
                    "error": "agent_cannot_write_canon",
                    "message": (
                        "No Agent may submit Canon. Submit remains "
                        "POST .../candidate-changes/{id}/submit for the "
                        "human 主编 only."
                    ),
                    "agent_id": mapped,
                    "action": ACTION_SUBMIT_CANON,
                }
            )
        if actor_id == "worker" or actor.actor_type == SYSTEM:
            raise PermissionDenied(
                {
                    "error": "worker_cannot_write_canon",
                    "message": "Worker / system cannot submit Canon.",
                    "actor_type": actor.actor_type,
                }
            )

    def assert_actor_may_run_agent(self, actor: Actor, agent: Agent) -> None:
        if agent.id != AGENT_HUMAN_APPROVER:
            return
        if actor.actor_type != HUMAN_EDITOR:
            raise PermissionDenied(
                {
                    "error": "human_editor_required",
                    "message": (
                        "Human Approver runs require X-Actor-Type: "
                        "human_editor. Agents cannot impersonate the 主编."
                    ),
                    "actor_type": actor.actor_type or None,
                    "agent_id": agent.id,
                }
            )

    def _resolve_agent(self, agent: Agent | str) -> Agent:
        if isinstance(agent, Agent):
            return agent
        agent_id = normalize_agent_id(agent) or agent
        record = self._registry.get_agent(agent_id)
        if record is None:
            raise PermissionDenied(
                {
                    "error": "agent_not_found",
                    "message": f"Agent '{agent}' is not registered.",
                    "agent_id": agent,
                },
                status_code=404,
            )
        return record


def action_for_job_type(job_type: str) -> str | None:
    return JOB_TYPE_TO_ACTION.get(job_type.strip().lower())


def agent_id_for_job_type(job_type: str) -> str | None:
    return JOB_TYPE_TO_AGENT.get(job_type.strip().lower())


def default_tool_for(agent: Agent) -> str:
    primary = {
        "outline_agent": "propose_outline",
        "draft_agent": "generate_draft",
        "extractor_agent": "propose_candidate_change",
        "consistency_agent": "produce_validation_report",
        "style_agent": "produce_style_report",
        "repair_agent": "produce_draft_revision",
        "human_approver": ACTION_APPROVE_CANON,
    }
    tool = primary.get(agent.id)
    if tool and tool in agent.allowed_tools:
        return tool
    return min(agent.allowed_tools)


def canon_write_denied_detail(agent_id: str, action: str) -> dict[str, Any]:
    return {
        "error": "agent_cannot_write_canon",
        "message": (
            "No Agent (including Worker / system) may bypass Approval "
            "to write Canon. Human Approver is the only Canon-approve "
            f"actor. Action '{action}' is forbidden."
        ),
        "agent_id": agent_id,
        "action": action,
        "writes_canon": False,
    }
