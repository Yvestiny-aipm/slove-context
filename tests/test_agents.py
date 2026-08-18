"""Agent Registry and permission boundaries (node 8.2).

In-memory repositories. No live Postgres. No network. No real models.
Service layer re-checks permissions. Unauthorized tools are 403.
Agent Runs are replayable from stored refs. No Agent (including
Worker / system) may bypass Approval to write Canon. Human Approver
is the only Canon-approve actor. 2.1–8.1 APIs and /healthz remain.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from slove_context.agents.models import (
    ACTION_APPROVE_CANON,
    ACTION_GENERATE_DRAFT,
    ACTION_PRODUCE_DRAFT_REVISION,
    ACTION_PRODUCE_STYLE_REPORT,
    ACTION_PRODUCE_VALIDATION_REPORT,
    ACTION_PROPOSE_CANDIDATE_CHANGE,
    ACTION_PROPOSE_OUTLINE,
    ACTION_PROPOSE_SCENE_PLAN,
    ACTION_SUBMIT_CANON,
    ACTION_WRITE_CANON,
    ACTION_WRITE_DRAFT,
    AGENT_CONSISTENCY,
    AGENT_DRAFT,
    AGENT_EXTRACTOR,
    AGENT_HUMAN_APPROVER,
    AGENT_IDS,
    AGENT_OUTLINE,
    AGENT_REPAIR,
    AGENT_STYLE,
    JOB_TYPE_TO_AGENT,
)
from slove_context.agents.permissions import PermissionDenied, PermissionGuard
from slove_context.app import create_app
from slove_context.audit import REDACTED, AuditWriter, InMemoryAuditSink
from slove_context.jobs.models import Job
from slove_context.jobs.worker import WorkerDispatchError, dispatch_existing
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.story.actors import Actor
from slove_context.story.repository import InMemoryStoryRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}
SYSTEM = {"X-Actor-Type": "system", "X-Actor-Id": "sys-1"}
REVIEW = {"X-Actor-Type": "review_agent", "X-Actor-Id": "rev-1"}
WORKER = {"X-Actor-Type": "system", "X-Actor-Id": "worker"}

EXPECTED_OUTPUT = {
    AGENT_OUTLINE: {"outline", "scene_plan"},
    AGENT_DRAFT: {"scene_draft"},
    AGENT_EXTRACTOR: {"candidate_change"},
    AGENT_CONSISTENCY: {"validation_report"},
    AGENT_STYLE: {"style_report"},
    AGENT_REPAIR: {"scene_draft_revision"},
    AGENT_HUMAN_APPROVER: {"approval_decision"},
}

ALLOWED_TOOL = {
    AGENT_OUTLINE: ACTION_PROPOSE_OUTLINE,
    AGENT_DRAFT: ACTION_GENERATE_DRAFT,
    AGENT_EXTRACTOR: ACTION_PROPOSE_CANDIDATE_CHANGE,
    AGENT_CONSISTENCY: ACTION_PRODUCE_VALIDATION_REPORT,
    AGENT_STYLE: ACTION_PRODUCE_STYLE_REPORT,
    AGENT_REPAIR: ACTION_PRODUCE_DRAFT_REVISION,
    AGENT_HUMAN_APPROVER: ACTION_APPROVE_CANON,
}


def _client(*, agent_run_auto_run: bool = True) -> tuple[TestClient, InMemoryAuditSink]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    app = create_app(
        repository=InMemoryStoryRepository(),
        audit_writer=writer,
        llm_gateway=LlmGateway(
            FakeProvider(),
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
        agent_run_auto_run=agent_run_auto_run,
    )
    return TestClient(app), sink


def _create_project(client: TestClient) -> dict:
    response = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": "青石夜祠", "language": "zh-CN", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _start_run(
    client: TestClient,
    project_id: str,
    agent_id: str,
    *,
    tool: str | None = None,
    input_ref: str = "ref:scene:fixture",
    headers: dict[str, str] | None = None,
) -> object:
    body: dict[str, str] = {"agent_id": agent_id, "input_ref": input_ref}
    if tool is not None:
        body["tool"] = tool
    return client.post(
        f"/projects/{project_id}/agent-runs",
        headers=headers or GENERATE,
        json=body,
    )


def test_healthz_and_prior_apis_still_present() -> None:
    client, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/version").json().get("version")
    paths = client.get("/openapi.json").json()["paths"]
    assert "/healthz" in paths
    assert "/version" in paths
    assert "/projects/{project_id}/specs/{spec_id}/approve" in paths
    assert "/projects/{project_id}/canon-facts" in paths
    assert "/projects/{project_id}/canon-snapshots/{snapshot_id}/freeze" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/approve" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/plans/jobs" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/drafts/jobs" in paths
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/extract-jobs"
        in paths
    )
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/approve" in paths
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/submit" in paths
    assert "/projects/{project_id}/validation-runs" in paths
    assert "/projects/{project_id}/repair-tasks" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/context-packs" in paths
    assert "/projects/{project_id}/outline-revisions" in paths
    assert "/projects/{project_id}/style-guides" in paths
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}"
        "/style-validations" in paths
    )
    assert "/projects/{project_id}/review-queue/items" in paths
    assert "/projects/{project_id}/jobs" in paths
    assert "/projects/{project_id}/jobs/{job_id}/rerun" in paths
    assert "/agents" in paths
    assert "/agents/{agent_id}" in paths
    assert "/projects/{project_id}/agent-runs" in paths
    assert "/projects/{project_id}/agent-runs/{run_id}" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/auto-approve" not in paths
    assert "/projects/{project_id}/agent-registry" not in paths
    assert "/projects/{project_id}/dags" not in paths
    assert "/projects/{project_id}/batches" not in paths
    assert not any("seed-status" in path for path in paths)
    assert not any("openai" in path for path in paths)


def test_seven_agents_registered_with_permission_fields() -> None:
    client, _ = _client()
    listed = client.get("/agents")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert {item["id"] for item in items} == set(AGENT_IDS)
    assert listed.json()["writes_canon"] is False
    for item in items:
        fetched = client.get(f"/agents/{item['id']}")
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["input_schema"]
        assert body["output_schema"]
        assert body["allowed_tools"]
        assert body["forbidden_operations"]
        assert "model_config" in body
        assert "prompt_version" in body
        assert "timeout_s" in body
        assert body["cost_cap"]
        assert set(body["allowed_output_types"]) == EXPECTED_OUTPUT[item["id"]]
        assert body["writes_canon"] is False
        assert body["may_submit_canon"] is False
        assert body["may_approve_canon"] is (item["id"] == AGENT_HUMAN_APPROVER)
        assert ACTION_WRITE_CANON in body["forbidden_operations"]
        assert ACTION_SUBMIT_CANON in body["forbidden_operations"]


def test_each_agent_only_allowed_its_output_type() -> None:
    client, _ = _client()
    project_id = _create_project(client)["id"]
    for agent_id, tool in ALLOWED_TOOL.items():
        headers = HUMAN if agent_id == AGENT_HUMAN_APPROVER else GENERATE
        response = _start_run(client, project_id, agent_id, tool=tool, headers=headers)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "succeeded"
        assert body["output_type"] in EXPECTED_OUTPUT[agent_id]
        assert body["output_ref"]
        assert body["input_ref"]
        assert body["writes_canon"] is False
        assert body["replayable"] is True


def test_outline_cannot_write_draft() -> None:
    client, _ = _client()
    project_id = _create_project(client)["id"]
    for tool in (ACTION_WRITE_DRAFT, ACTION_GENERATE_DRAFT, "draft"):
        denied = _start_run(client, project_id, AGENT_OUTLINE, tool=tool)
        assert denied.status_code == 403, denied.text
        assert denied.json()["detail"]["error"] in {
            "agent_permission_denied",
            "agent_output_type_denied",
        }


def test_draft_cannot_approve() -> None:
    client, _ = _client()
    project_id = _create_project(client)["id"]
    for tool in ("approve", ACTION_APPROVE_CANON):
        denied = _start_run(client, project_id, AGENT_DRAFT, tool=tool)
        assert denied.status_code == 403, denied.text
        assert denied.json()["detail"]["error"] == "agent_cannot_approve"


def test_extractor_cannot_submit_canon() -> None:
    client, sink = _client()
    project_id = _create_project(client)["id"]
    denied = _start_run(client, project_id, AGENT_EXTRACTOR, tool=ACTION_SUBMIT_CANON)
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["error"] == "agent_cannot_write_canon"
    assert any(event.action == "agent_run.fail" for event in sink.events)


def test_style_cannot_write_canon() -> None:
    client, _ = _client()
    project_id = _create_project(client)["id"]
    denied = _start_run(client, project_id, AGENT_STYLE, tool=ACTION_WRITE_CANON)
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["error"] == "agent_cannot_write_canon"


def test_anyone_other_than_human_cannot_approve() -> None:
    client, _ = _client()
    project_id = _create_project(client)["id"]
    guard = PermissionGuard()
    non_human = [
        AGENT_OUTLINE,
        AGENT_DRAFT,
        AGENT_EXTRACTOR,
        AGENT_CONSISTENCY,
        AGENT_STYLE,
        AGENT_REPAIR,
    ]
    for agent_id in non_human:
        with pytest.raises(PermissionDenied) as exc:
            guard.assert_allowed(agent_id, ACTION_APPROVE_CANON)
        assert exc.value.status_code == 403
        denied = _start_run(client, project_id, agent_id, tool=ACTION_APPROVE_CANON)
        assert denied.status_code == 403
    impersonate = _start_run(
        client,
        project_id,
        AGENT_HUMAN_APPROVER,
        tool=ACTION_APPROVE_CANON,
        headers=GENERATE,
    )
    assert impersonate.status_code == 403
    assert impersonate.json()["detail"]["error"] == "human_editor_required"
    for headers in (GENERATE, SYSTEM, REVIEW, WORKER):
        blocked = client.post(
            f"/projects/{project_id}/candidate-changes/missing/approve",
            headers=headers,
            json={"created_by": "bot"},
        )
        assert blocked.status_code == 403


def test_unauthorized_tool_is_403_and_keeps_failed_record() -> None:
    client, _ = _client()
    project_id = _create_project(client)["id"]
    denied = _start_run(
        client, project_id, AGENT_OUTLINE, tool=ACTION_PROPOSE_CANDIDATE_CHANGE
    )
    assert denied.status_code == 403
    runs = client.app.state.agent_repository.list_runs(project_id)
    assert runs
    assert runs[-1].status == "failed"
    assert runs[-1].error is not None
    fetched = client.get(f"/projects/{project_id}/agent-runs/{runs[-1].id}")
    assert fetched.status_code == 200
    assert fetched.json()["kept"] is True
    assert fetched.json()["status"] == "failed"


def test_agent_run_archival_is_replayable() -> None:
    client, sink = _client()
    project_id = _create_project(client)["id"]
    created = _start_run(
        client,
        project_id,
        AGENT_DRAFT,
        tool=ACTION_GENERATE_DRAFT,
        input_ref="ref:plan:abc",
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["input_ref"] == "ref:plan:abc"
    assert body["output_ref"]
    assert body["tool_calls"]
    assert body["tool_calls"][0]["tool"] == ACTION_GENERATE_DRAFT
    assert "cost" in body
    assert body["duration_ms"] is not None
    assert body["error"] is None
    fetched = client.get(f"/projects/{project_id}/agent-runs/{body['id']}")
    assert fetched.status_code == 200
    replay = client.get(f"/projects/{project_id}/agent-runs/{body['id']}/replay")
    assert replay.status_code == 200
    refs = replay.json()
    assert refs["input_ref"] == body["input_ref"]
    assert refs["output_ref"] == body["output_ref"]
    assert refs["tool_calls"] == body["tool_calls"]
    assert refs["cost"] == body["cost"]
    assert refs["duration_ms"] == body["duration_ms"]
    assert refs["replayable"] is True
    assert any(event.action == "agent_run.succeed" for event in sink.events)


def test_cancel_keeps_record() -> None:
    client, sink = _client(agent_run_auto_run=False)
    project_id = _create_project(client)["id"]
    created = _start_run(
        client, project_id, AGENT_STYLE, tool=ACTION_PRODUCE_STYLE_REPORT
    )
    assert created.status_code == 201
    assert created.json()["status"] == "queued"
    cancelled = client.post(
        f"/projects/{project_id}/agent-runs/{created.json()['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["kept"] is True
    item = cancelled.json()["item"]
    assert item["status"] == "cancelled"
    fetched = client.get(f"/projects/{project_id}/agent-runs/{item['id']}")
    assert fetched.json()["status"] == "cancelled"
    assert fetched.json()["kept"] is True
    assert any(event.action == "agent_run.cancel" for event in sink.events)


def test_canon_bypass_fails_for_every_agent_including_worker() -> None:
    client, _ = _client()
    project_id = _create_project(client)["id"]
    guard = PermissionGuard()
    for agent_id in AGENT_IDS:
        for action in (ACTION_WRITE_CANON, ACTION_SUBMIT_CANON, "bypass_approval"):
            with pytest.raises(PermissionDenied) as exc:
                guard.assert_allowed(agent_id, action)
            assert exc.value.status_code == 403
            headers = HUMAN if agent_id == AGENT_HUMAN_APPROVER else GENERATE
            denied = _start_run(
                client, project_id, agent_id, tool=action, headers=headers
            )
            assert denied.status_code == 403
            assert denied.json()["detail"]["error"] == "agent_cannot_write_canon"
    with pytest.raises(PermissionDenied):
        guard.assert_job_dispatch_allowed("approve")
    with pytest.raises(PermissionDenied):
        guard.assert_job_dispatch_allowed("submit_canon")
    job = Job(
        id="job-approve",
        project_id=project_id,
        job_type="approve",
        payload_reference="payload-1",
        status="running",
        attempt_count=1,
        max_attempts=1,
        scheduled_at="2026-08-18T00:00:00.000000Z",
        created_at="2026-08-18T00:00:00.000000Z",
        updated_at="2026-08-18T00:00:00.000000Z",
        created_by="worker",
        actor_type="system",
        correlation_id="corr",
    )
    with pytest.raises(WorkerDispatchError) as exc:
        dispatch_existing(client.app.state.worker._services, job, {})
    assert "canon" in exc.value.error_code or "permission" in exc.value.error_code
    worker_submit = guard.assert_actor_may_submit_canon
    with pytest.raises(PermissionDenied):
        worker_submit(Actor(actor_type="system", actor_id="worker"))


def test_human_approver_approve_does_not_write_canon() -> None:
    client, _ = _client()
    project_id = _create_project(client)["id"]
    created = _start_run(
        client,
        project_id,
        AGENT_HUMAN_APPROVER,
        tool=ACTION_APPROVE_CANON,
        headers=HUMAN,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["output_type"] == "approval_decision"
    assert body["writes_canon"] is False
    assert body["auto_approved"] is False
    facts = client.get(f"/projects/{project_id}/canon-facts")
    assert facts.status_code == 200
    assert facts.json().get("facts") == []


def test_worker_job_types_map_to_agents_and_still_cannot_approve() -> None:
    assert JOB_TYPE_TO_AGENT["plan"] == AGENT_OUTLINE
    assert JOB_TYPE_TO_AGENT["draft"] == AGENT_DRAFT
    assert JOB_TYPE_TO_AGENT["extract"] == AGENT_EXTRACTOR
    assert JOB_TYPE_TO_AGENT["validate"] == AGENT_CONSISTENCY
    assert JOB_TYPE_TO_AGENT["repair"] == AGENT_REPAIR
    guard = PermissionGuard()
    assert guard.assert_job_dispatch_allowed("plan").id == AGENT_OUTLINE
    assert guard.assert_job_dispatch_allowed("draft").id == AGENT_DRAFT
    assert guard.assert_allowed(AGENT_OUTLINE, ACTION_PROPOSE_SCENE_PLAN)


def test_writes_are_audited_and_redacted() -> None:
    client, sink = _client()
    project_id = _create_project(client)["id"]
    created = _start_run(
        client,
        project_id,
        AGENT_EXTRACTOR,
        tool=ACTION_PROPOSE_CANDIDATE_CHANGE,
        input_ref="ref:draft:1",
    )
    assert created.status_code == 201
    events = [event for event in sink.events if event.action.startswith("agent_run.")]
    assert events
    blob = str([event.after_json for event in events])
    assert "sk-" not in blob
    denied = _start_run(
        client,
        project_id,
        AGENT_STYLE,
        tool=ACTION_WRITE_CANON,
        input_ref="ref:secret",
    )
    assert denied.status_code == 403
    fail_events = [event for event in sink.events if event.action == "agent_run.fail"]
    assert fail_events
    after = fail_events[-1].after_json or {}
    assert after.get("writes_canon") is False
    assert "prompt" not in (after.get("error") or {})
    assert REDACTED == "[REDACTED]"


def test_no_production_seed_status_or_real_model() -> None:
    package = ROOT / "backend" / "slove_context" / "agents"
    text = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
    assert "seed-status" not in text
    assert "openai" not in text.lower()
    assert "anthropic" not in text.lower()
    for name in ("openai", "anthropic", "langchain", "chromadb", "pgvector"):
        assert f"import {name}" not in text
        assert f"from {name}" not in text
    assert "PermissionGuard" in text
    assert "assert_allowed" in text
    routes = (package / "routes.py").read_text(encoding="utf-8")
    assert "seed-status" not in routes
    draft_service = (
        ROOT / "backend" / "slove_context" / "scene_draft" / "service.py"
    ).read_text(encoding="utf-8")
    assert "from slove_context.agents" not in draft_service
    validation_rules = (
        ROOT / "backend" / "slove_context" / "validation" / "rules.py"
    ).read_text(encoding="utf-8")
    assert "from slove_context.agents" not in validation_rules


def test_migration_adds_agents_without_rebuilding_prior() -> None:
    versions = ROOT / "backend" / "alembic" / "versions"
    create = (versions / "019_create_agents.py").read_text(encoding="utf-8")
    assert "CREATE TABLE agents" in create
    assert "CREATE TABLE agent_runs" in create
    assert "input_ref" in create
    assert "output_ref" in create
    assert "tool_calls" in create
    assert "duration_ms" in create
    assert "outline_agent" in create
    assert "human_approver" in create
    assert "CREATE TABLE jobs" not in create
    assert "CREATE TABLE review_queue_items" not in create
    assert "CREATE TABLE scene_drafts" not in create
    assert "CREATE TABLE validation_runs" not in create
    assert 'down_revision: str | None = "018_jobs"' in create
    upgrade = create.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    lowered = upgrade.lower()
    assert "vector(" not in lowered
    assert "embedding" not in lowered
    assert "openai" not in lowered
    assert "dag" not in lowered


def test_alias_lookup_and_missing_agent() -> None:
    client, _ = _client()
    listed = client.get("/agents/outline")
    assert listed.status_code == 200
    assert listed.json()["id"] == AGENT_OUTLINE
    missing = client.get("/agents/unknown-bot")
    assert missing.status_code == 404
    project_id = _create_project(client)["id"]
    denied = client.post(
        f"/projects/{project_id}/agent-runs",
        headers=GENERATE,
        json={"agent_id": "unknown-bot", "input_ref": "ref:1"},
    )
    assert denied.status_code == 404
