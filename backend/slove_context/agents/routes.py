"""HTTP routes for Agent Registry and Agent Runs (node 8.2).

GET  /agents
GET  /agents/{agent_id}
POST /projects/{project_id}/agent-runs
GET  /projects/{project_id}/agent-runs/{run_id}
GET  /projects/{project_id}/agent-runs/{run_id}/replay
POST /projects/{project_id}/agent-runs/{run_id}/cancel

Unauthorized tools are 403. No production seed-status. No DAG.
No real model. Agent runs do not write Canon.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from slove_context.agents.repository import (
    AgentRepository,
    InMemoryAgentRunRepository,
)
from slove_context.agents.service import AgentService, AgentServiceError
from slove_context.candidate_change.approval_service import ApprovalService
from slove_context.canon.service import CanonService
from slove_context.logging import get_request_id
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)

router = APIRouter(tags=["agents"])


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class StartRunBody(ActorBody):
    agent_id: str
    input_ref: str
    tool: str | None = None


def _service(request: Request) -> AgentService:
    agents: AgentRepository = (
        getattr(request.app.state, "agent_repository", None)
        or InMemoryAgentRunRepository()
    )
    approval = ApprovalService(
        story_repository=request.app.state.repository,
        extract_repository=request.app.state.candidate_change_repository,
        canon_service=CanonService(
            story_repository=request.app.state.repository,
            canon_repository=request.app.state.canon_repository,
            audit_writer=request.app.state.audit_writer,
        ),
        audit_writer=request.app.state.audit_writer,
    )
    return AgentService(
        story_repository=request.app.state.repository,
        agent_repository=agents,
        audit_writer=request.app.state.audit_writer,
        approval_service=approval,
        auto_run=bool(getattr(request.app.state, "agent_run_auto_run", True)),
    )


def _actor(request: Request, body: ActorBody | None = None) -> Actor:
    body_type = body.actor_type if body is not None else None
    body_id = None
    if body is not None:
        body_id = body.actor_id or body.created_by
    return resolve_actor(
        header_type=request.headers.get(ACTOR_TYPE_HEADER),
        header_id=request.headers.get(ACTOR_ID_HEADER),
        body_type=body_type,
        body_id=body_id,
    )


def _raise(exc: AgentServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/agents")
def list_agents(request: Request) -> dict[str, Any]:
    items = _service(request).list_agents()
    return {
        "items": [item.to_public_dict() for item in items],
        "count": len(items),
        "writes_canon": False,
        "auto_approved": False,
    }


@router.get("/agents/{agent_id}")
def get_agent(request: Request, agent_id: str) -> dict[str, Any]:
    try:
        agent = _service(request).get_agent(agent_id)
    except AgentServiceError as exc:
        _raise(exc)
    return agent.to_public_dict()


@router.post("/projects/{project_id}/agent-runs", status_code=201)
def start_agent_run(
    request: Request, project_id: str, body: StartRunBody
) -> dict[str, Any]:
    try:
        run = _service(request).start_run(
            project_id=project_id,
            agent_id=body.agent_id,
            actor=_actor(request, body),
            input_ref=body.input_ref,
            tool=body.tool,
            correlation_id=get_request_id(),
        )
    except AgentServiceError as exc:
        _raise(exc)
    return run.to_public_dict()


@router.get("/projects/{project_id}/agent-runs/{run_id}")
def get_agent_run(request: Request, project_id: str, run_id: str) -> dict[str, Any]:
    try:
        run = _service(request).get_run(project_id, run_id)
    except AgentServiceError as exc:
        _raise(exc)
    return run.to_public_dict()


@router.get("/projects/{project_id}/agent-runs/{run_id}/replay")
def replay_agent_run(request: Request, project_id: str, run_id: str) -> dict[str, Any]:
    try:
        payload = _service(request).replay_run(project_id, run_id)
    except AgentServiceError as exc:
        _raise(exc)
    return payload


@router.post("/projects/{project_id}/agent-runs/{run_id}/cancel")
def cancel_agent_run(
    request: Request,
    project_id: str,
    run_id: str,
    body: ActorBody | None = None,
) -> dict[str, Any]:
    try:
        run = _service(request).cancel_run(
            project_id, run_id, actor=_actor(request, body)
        )
    except AgentServiceError as exc:
        _raise(exc)
    return {"item": run.to_public_dict(), "kept": True, "writes_canon": False}
