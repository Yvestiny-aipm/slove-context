"""Agent Run write path (node 8.2).

PermissionGuard re-checks every tool. Unauthorized calls are 403 and
keep a failed record. Allowed runs archive input_ref, output_ref,
tool_calls, cost, duration, and error so they are replayable.

Human Approver approve reuses 4.2 approve (verdict only) when a
candidate_id is supplied. No run writes Canon. Submit stays on the
existing 4.2 path. Failure / cancel keep the row. Fake Provider only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.agents.models import (
    ACTION_APPROVE,
    ACTION_APPROVE_CANON,
    AGENT_HUMAN_APPROVER,
    CANON_WRITE_ACTIONS,
    OUTPUT_TYPE_FOR_ACTION,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    Agent,
    AgentRun,
    normalize_action,
    normalize_agent_id,
)
from slove_context.agents.permissions import (
    PermissionDenied,
    PermissionGuard,
    canon_write_denied_detail,
    default_tool_for,
)
from slove_context.agents.repository import AgentRepository
from slove_context.audit import AuditWriter
from slove_context.candidate_change.approval_service import ApprovalService
from slove_context.candidate_change.service import CandidateChangeServiceError
from slove_context.logging import get_request_id
from slove_context.story.actors import HUMAN_EDITOR, Actor
from slove_context.story.repository import StoryRepository

ACTIVE_CANCEL = frozenset({STATUS_QUEUED, STATUS_RUNNING})


class AgentServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class AgentService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        agent_repository: AgentRepository,
        audit_writer: AuditWriter,
        approval_service: ApprovalService | None = None,
        guard: PermissionGuard | None = None,
        auto_run: bool = True,
    ) -> None:
        self._story = story_repository
        self._repo = agent_repository
        self._audit = audit_writer
        self._approval = approval_service
        self._guard = guard or PermissionGuard(agent_repository)
        self._auto_run = auto_run

    def list_agents(self) -> list[Agent]:
        return self._repo.list_agents()

    def get_agent(self, agent_id: str) -> Agent:
        mapped = normalize_agent_id(agent_id) or agent_id
        agent = self._repo.get_agent(mapped)
        if agent is None:
            raise AgentServiceError(404, {"error": "agent_not_found"})
        return agent

    def start_run(
        self,
        *,
        project_id: str,
        agent_id: str,
        actor: Actor,
        input_ref: str,
        tool: str | None = None,
        correlation_id: str | None = None,
    ) -> AgentRun:
        self._require_project(project_id)
        agent = self.get_agent(agent_id)
        ref = _require_input_ref(input_ref)
        now = _utc_now_z()
        run = AgentRun(
            id=str(uuid4()),
            project_id=project_id,
            agent_id=agent.id,
            input_ref=ref,
            status=STATUS_QUEUED,
            tool=normalize_action(tool) if tool else None,
            created_at=now,
            updated_at=now,
            created_by=actor.actor_id or "agent-run",
            actor_type=actor.actor_type or "",
            correlation_id=correlation_id or get_request_id() or str(uuid4()),
            cost=_empty_cost(agent),
        )
        self._repo.add_run(run)
        self._write_audit(
            actor=actor,
            action="agent_run.create",
            resource_type="agent_run",
            resource_id=run.id,
            before_json=None,
            after_json=run.to_audit_dict(),
        )
        try:
            self._guard.assert_actor_may_run_agent(actor, agent)
            requested = run.tool or default_tool_for(agent)
            run.tool = requested
            if requested in CANON_WRITE_ACTIONS:
                raise PermissionDenied(canon_write_denied_detail(agent.id, requested))
            self._guard.assert_allowed(agent, requested)
        except PermissionDenied as exc:
            self._fail_run(run, actor=actor, detail=exc.detail)
            raise AgentServiceError(exc.status_code, exc.detail) from exc

        if self._auto_run:
            return self.execute_run(project_id, run.id, actor=actor)
        return run

    def execute_run(self, project_id: str, run_id: str, *, actor: Actor) -> AgentRun:
        run = self.get_run(project_id, run_id)
        agent = self.get_agent(run.agent_id)
        tool = run.tool or default_tool_for(agent)
        started = datetime.now(UTC)
        before = run.to_audit_dict()
        run.status = STATUS_RUNNING
        run.updated_at = _utc_now_z()
        self._repo.save_run(run)
        self._write_audit(
            actor=actor,
            action="agent_run.start",
            resource_type="agent_run",
            resource_id=run.id,
            before_json=before,
            after_json=run.to_audit_dict(),
        )
        try:
            self._guard.assert_allowed(agent, tool)
            output_type, output_ref, tool_calls, extra = self._dispatch_tool(
                agent=agent,
                run=run,
                tool=tool,
                actor=actor,
            )
        except PermissionDenied as exc:
            self._fail_run(run, actor=actor, detail=exc.detail)
            raise AgentServiceError(exc.status_code, exc.detail) from exc
        except AgentServiceError as exc:
            self._fail_run(
                run,
                actor=actor,
                detail=exc.detail
                if isinstance(exc.detail, dict)
                else {"error": str(exc)},
            )
            raise
        except CandidateChangeServiceError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc)}
            self._fail_run(run, actor=actor, detail=detail)
            raise AgentServiceError(exc.status_code, detail) from exc

        finished = datetime.now(UTC)
        duration_ms = max(int((finished - started).total_seconds() * 1000), 0)
        before = run.to_audit_dict()
        run.status = STATUS_SUCCEEDED
        run.output_type = output_type
        run.output_ref = output_ref
        run.tool_calls = tool_calls
        run.cost = _capped_cost(agent, extra.get("cost"))
        run.duration_ms = duration_ms
        run.error = None
        run.finished_at = _utc_now_z()
        run.updated_at = run.finished_at
        self._repo.save_run(run)
        self._write_audit(
            actor=actor,
            action="agent_run.succeed",
            resource_type="agent_run",
            resource_id=run.id,
            before_json=before,
            after_json=run.to_audit_dict(),
        )
        return run

    def get_run(self, project_id: str, run_id: str) -> AgentRun:
        self._require_project(project_id)
        run = self._repo.get_run(run_id)
        if run is None or run.project_id != project_id:
            raise AgentServiceError(404, {"error": "agent_run_not_found"})
        return run

    def replay_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        run = self.get_run(project_id, run_id)
        return run.replay_refs()

    def cancel_run(self, project_id: str, run_id: str, *, actor: Actor) -> AgentRun:
        run = self.get_run(project_id, run_id)
        if run.status not in ACTIVE_CANCEL:
            raise AgentServiceError(
                409,
                {
                    "error": "agent_run_not_cancellable",
                    "message": (
                        "Only queued / running runs can be cancelled. "
                        "Failure and cancel keep the record."
                    ),
                    "status": run.status,
                    "kept": True,
                },
            )
        before = run.to_audit_dict()
        now = _utc_now_z()
        run.status = STATUS_CANCELLED
        run.finished_at = now
        run.updated_at = now
        run.error = {
            "error": "cancelled",
            "message": "Run cancelled. Record is kept.",
        }
        self._repo.save_run(run)
        self._write_audit(
            actor=actor,
            action="agent_run.cancel",
            resource_type="agent_run",
            resource_id=run.id,
            before_json=before,
            after_json=run.to_audit_dict(),
        )
        return run

    def list_runs(self, project_id: str) -> list[AgentRun]:
        self._require_project(project_id)
        return self._repo.list_runs(project_id)

    def _dispatch_tool(
        self,
        *,
        agent: Agent,
        run: AgentRun,
        tool: str,
        actor: Actor,
    ) -> tuple[str, str, list[dict[str, Any]], dict[str, Any]]:
        output_type = OUTPUT_TYPE_FOR_ACTION.get(tool)
        if output_type is None or output_type not in agent.allowed_output_types:
            raise PermissionDenied(
                {
                    "error": "agent_output_type_denied",
                    "message": (
                        f"Agent '{agent.id}' may only produce "
                        f"{sorted(agent.allowed_output_types)}."
                    ),
                    "agent_id": agent.id,
                    "action": tool,
                }
            )
        extra: dict[str, Any] = {}
        if agent.id == AGENT_HUMAN_APPROVER and tool in {
            ACTION_APPROVE_CANON,
            ACTION_APPROVE,
        }:
            extra = self._human_approve_only(run, actor)
        output_ref = extra.get("output_ref") or f"agent-run:{run.id}:{output_type}"
        tool_calls = [
            {
                "tool": tool,
                "input_ref": run.input_ref,
                "output_ref": output_ref,
                "output_type": output_type,
                "allowed": True,
                "writes_canon": False,
            }
        ]
        return output_type, str(output_ref), tool_calls, extra

    def _human_approve_only(self, run: AgentRun, actor: Actor) -> dict[str, Any]:
        """Reuse 4.2 approve when a candidate_id is present. Never submit."""
        self._guard.assert_actor_may_approve_canon(actor)
        candidate_id = _candidate_id_from_ref(run.input_ref)
        if candidate_id is None or self._approval is None:
            return {
                "output_ref": f"agent-run:{run.id}:approval_decision",
                "cost": _empty_cost(self.get_agent(AGENT_HUMAN_APPROVER)),
            }
        _candidate, decision = self._approval.approve(
            project_id=run.project_id,
            candidate_id=candidate_id,
            actor=actor,
            body={"created_by": actor.actor_id or HUMAN_EDITOR},
        )
        return {
            "output_ref": f"approval_decision:{decision['id']}",
            "cost": _empty_cost(self.get_agent(AGENT_HUMAN_APPROVER)),
        }

    def _fail_run(self, run: AgentRun, *, actor: Actor, detail: dict[str, Any]) -> None:
        before = run.to_audit_dict()
        now = _utc_now_z()
        run.status = STATUS_FAILED
        run.error = {
            key: value
            for key, value in detail.items()
            if key
            not in {
                "prompt",
                "system_prompt",
                "user_prompt",
                "body",
                "prose",
                "text_evidence",
            }
        }
        run.finished_at = now
        run.updated_at = now
        self._repo.save_run(run)
        self._write_audit(
            actor=actor,
            action="agent_run.fail",
            resource_type="agent_run",
            resource_id=run.id,
            before_json=before,
            after_json=run.to_audit_dict(),
        )

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise AgentServiceError(404, {"error": "project_not_found"})

    def _write_audit(
        self,
        *,
        actor: Actor,
        action: str,
        resource_type: str,
        resource_id: str,
        before_json: dict[str, Any] | None,
        after_json: dict[str, Any] | None,
    ) -> None:
        self._audit.write(
            actor_type=actor.actor_type or "system",
            actor_id=actor.actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            correlation_id=get_request_id(),
        )


def _require_input_ref(value: str | None) -> str:
    if value is None or not str(value).strip():
        raise AgentServiceError(
            422,
            {
                "error": "input_ref_required",
                "message": "Agent Run requires a stored input_ref for replay.",
            },
        )
    return str(value).strip()


def _candidate_id_from_ref(input_ref: str) -> str | None:
    cleaned = input_ref.strip()
    prefixes = (
        "candidate:",
        "candidate_change:",
        "candidate-change:",
    )
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            return cleaned[len(prefix) :] or None
    return None


def _empty_cost(agent: Agent) -> dict[str, Any]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "provider": agent.model_config.get("provider") or "fake",
        "capped": True,
        "cap": dict(agent.cost_cap),
    }


def _capped_cost(agent: Agent, incoming: dict[str, Any] | None) -> dict[str, Any]:
    base = _empty_cost(agent)
    if incoming:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cost_usd"):
            if key in incoming:
                base[key] = incoming[key]
    max_tokens = agent.cost_cap.get("max_tokens")
    if isinstance(max_tokens, int | float) and float(base["total_tokens"]) > float(
        max_tokens
    ):
        base["total_tokens"] = max_tokens
        base["capped"] = True
    return base


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
