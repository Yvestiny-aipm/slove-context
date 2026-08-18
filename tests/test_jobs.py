"""Local job queue and Worker (node 8.1).

In-memory repositories. No live Postgres. No network. No real models.
Worker dispatches to existing services only. It does not approve
Candidate Changes, does not submit Canon, and does not take review-
queue decisions. 2.1–7.3 APIs and /healthz remain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import REDACTED, AuditWriter, InMemoryAuditSink
from slove_context.candidate_change.models import (
    CANDIDATE_APPROVED,
    CANDIDATE_SUBMITTED,
)
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.jobs.models import (
    STATUS_DEAD_LETTER,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    WRITE_JOB_TYPES,
)
from slove_context.jobs.repository import InMemoryJobRepository
from slove_context.jobs.worker import Worker, WorkerDispatchError
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_draft.context_pack import STATIC_CONTEXT_PACK_ID
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.scene_plan.repository import InMemoryScenePlanRepository
from slove_context.story.repository import InMemoryStoryRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}
SYSTEM = {"X-Actor-Type": "system", "X-Actor-Id": "sys-1"}
REVIEW = {"X-Actor-Type": "review_agent", "X-Actor-Id": "rev-1"}
SPEC = {
    "title": "青石夜祠",
    "language": "zh-CN",
    "must_write": ["只写林晚在青石镇的七日"],
    "must_not_write": ["禁止第二主角视角"],
    "notes": "规格是编辑约束，不是 Canon。",
    "created_by": "主编",
}


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 18, 8, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _client(
    *,
    job_auto_run: bool = False,
    job_timeout_s: float = 30.0,
    job_base_backoff_s: float = 0.0,
) -> tuple[TestClient, InMemoryAuditSink, InMemoryCanonRepository]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    canon = InMemoryCanonRepository()
    jobs = InMemoryJobRepository()
    app = create_app(
        repository=InMemoryStoryRepository(),
        canon_repository=canon,
        scene_repository=InMemorySceneRepository(),
        scene_plan_repository=InMemoryScenePlanRepository(),
        scene_draft_repository=InMemorySceneDraftRepository(),
        job_repository=jobs,
        audit_writer=writer,
        llm_gateway=LlmGateway(
            FakeProvider(),
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
        job_auto_run=job_auto_run,
        job_timeout_s=job_timeout_s,
        job_base_backoff_s=job_base_backoff_s,
    )
    return TestClient(app), sink, canon


def _create_project(client: TestClient) -> dict:
    response = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": "青石夜祠", "language": "zh-CN", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _write_spec(client: TestClient, project_id: str) -> dict:
    created = client.post(
        f"/projects/{project_id}/specs",
        headers=HUMAN,
        json=SPEC,
    )
    assert created.status_code == 201, created.text
    spec_id = created.json()["id"]
    submitted = client.post(
        f"/projects/{project_id}/specs/{spec_id}/submit",
        headers=HUMAN,
        json={},
    )
    assert submitted.status_code == 200, submitted.text
    approved = client.post(
        f"/projects/{project_id}/specs/{spec_id}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def _create_scene(client: TestClient, project_id: str) -> dict:
    arc = client.post(
        f"/projects/{project_id}/arcs",
        headers=HUMAN,
        json={"title": "七日寻祠", "sort_order": 1, "created_by": "主编"},
    )
    assert arc.status_code == 201, arc.text
    chapter = client.post(
        f"/projects/{project_id}/chapters",
        headers=HUMAN,
        json={
            "arc_id": arc.json()["id"],
            "title": "得玉",
            "sort_order": 1,
            "created_by": "主编",
        },
    )
    assert chapter.status_code == 201, chapter.text
    scene = client.post(
        f"/projects/{project_id}/scenes",
        headers=HUMAN,
        json={
            "chapter_id": chapter.json()["id"],
            "story_order": 1,
            "pov": "林晚",
            "story_time": "第一日黄昏",
            "starting_state": "林晚空手走在河滩",
            "goal": "拾得残玉",
            "conflict": "河风与夜色让她几乎错过",
            "expected_end_state": "林晚持有残玉",
            "location": "青石镇河滩",
            "present_entities": ["林晚", "残玉"],
            "generation_boundary": "只写林晚在河滩捡到残玉这一场，不写整章。",
            "forbidden": ["禁止写出残玉来历"],
            "knowledge_boundaries": ["林晚不知残玉能开门"],
            "created_by": "主编",
        },
    )
    assert scene.status_code == 201, scene.text
    approved = client.post(
        f"/projects/{project_id}/scenes/{scene.json()['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def _create_snapshot(client: TestClient, project_id: str, *, freeze: bool) -> dict:
    created = client.post(
        f"/projects/{project_id}/canon-snapshots",
        headers=HUMAN,
        json={
            "as_of_scene_seq": 1,
            "as_of_story_time": "day-01",
            "created_by": "主编",
        },
    )
    assert created.status_code == 201, created.text
    if not freeze:
        return created.json()
    frozen = client.post(
        f"/projects/{project_id}/canon-snapshots/{created.json()['id']}/freeze",
        headers=HUMAN,
        json={},
    )
    assert frozen.status_code == 200, frozen.text
    return frozen.json()


def _pipeline(client: TestClient) -> dict[str, dict]:
    project = _create_project(client)
    _write_spec(client, project["id"])
    scene = _create_scene(client, project["id"])
    snapshot = _create_snapshot(client, project["id"], freeze=True)
    plan_job = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot["id"]},
    )
    assert plan_job.status_code == 201, plan_job.text
    plan = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/plans/current")
    assert plan.status_code == 200, plan.text
    draft_job = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json={
            "snapshot_id": snapshot["id"],
            "plan_id": plan.json()["plan"]["id"],
            "context_pack_id": STATIC_CONTEXT_PACK_ID,
        },
    )
    assert draft_job.status_code == 201, draft_job.text
    draft_id = draft_job.json()["draft_id"]
    extracted = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft_id}/extract-jobs",
        headers=GENERATE,
        json={},
    )
    assert extracted.status_code == 201, extracted.text
    listed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/candidate-changes"
    )
    assert listed.status_code == 200, listed.text
    return {
        "project": project,
        "scene": scene,
        "snapshot": snapshot,
        "plan": plan.json()["plan"],
        "draft": {"id": draft_id},
        "candidate": listed.json()["items"][0],
    }


def _enqueue(
    client: TestClient,
    project_id: str,
    job_type: str,
    payload: dict,
    *,
    headers: dict[str, str] | None = None,
    **extra: object,
) -> dict:
    body: dict[str, object] = {"job_type": job_type, "payload": payload}
    body.update(extra)
    response = client.post(
        f"/projects/{project_id}/jobs",
        headers=headers or GENERATE,
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _canon_fact_count(canon: InMemoryCanonRepository, project_id: str) -> int:
    return len([item for item in canon.facts.values() if item.project_id == project_id])


def test_healthz_and_prior_apis_remain() -> None:
    client, _, _ = _client()
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
    assert "/projects/{project_id}/jobs/{job_id}" in paths
    assert "/projects/{project_id}/jobs/{job_id}/cancel" in paths
    assert "/projects/{project_id}/jobs/{job_id}/rerun" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/auto-approve" not in paths
    assert "/projects/{project_id}/agent-registry" not in paths
    assert "/projects/{project_id}/agents" not in paths
    assert not any("seed-status" in path for path in paths)
    assert not any("agent-registry" in path for path in paths)


def test_enqueue_get_list() -> None:
    client, sink, _ = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    scene_id = data["scene"]["id"]
    job = _enqueue(
        client,
        project_id,
        "plan",
        {"scene_id": scene_id, "snapshot_id": data["snapshot"]["id"]},
        idempotency_key="plan-1",
    )
    assert job["status"] == STATUS_QUEUED
    assert job["job_type"] == "plan"
    assert job["payload_reference"]
    assert job["writes_canon"] is False
    fetched = client.get(f"/projects/{project_id}/jobs/{job['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == job["id"]
    listed = client.get(
        f"/projects/{project_id}/jobs",
        params={"status": "queued", "job_type": "plan", "scene_id": scene_id},
    )
    assert listed.status_code == 200
    assert any(item["id"] == job["id"] for item in listed.json()["items"])
    assert any(event.action == "job.enqueue" for event in sink.events)


def test_idempotency_returns_same_active_job() -> None:
    client, _, _ = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    payload = {
        "scene_id": data["scene"]["id"],
        "snapshot_id": data["snapshot"]["id"],
    }
    first = _enqueue(client, project_id, "plan", payload, idempotency_key="same-key")
    second = _enqueue(client, project_id, "plan", payload, idempotency_key="same-key")
    assert first["id"] == second["id"]
    listed = client.get(f"/projects/{project_id}/jobs?job_type=plan")
    assert len(listed.json()["items"]) == 1


def test_mutex_lock_blocks_parallel_write_jobs() -> None:
    client, _, _ = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    scene_id = data["scene"]["id"]
    draft = _enqueue(
        client,
        project_id,
        "draft",
        {
            "scene_id": scene_id,
            "snapshot_id": data["snapshot"]["id"],
            "plan_id": data["plan"]["id"],
            "context_pack_id": STATIC_CONTEXT_PACK_ID,
        },
    )
    extract = _enqueue(
        client,
        project_id,
        "extract",
        {"scene_id": scene_id, "revision_id": data["draft"]["id"]},
    )
    assert draft["is_write_job"] is True
    assert extract["is_write_job"] is True
    assert WRITE_JOB_TYPES == {"plan", "draft", "extract", "repair"}
    worker: Worker = client.app.state.worker
    first = worker.claim_one()
    assert first is not None
    second = worker.claim_one()
    assert second is None
    held = client.app.state.job_repository.get_lock(scene_id)
    assert held is not None
    assert held.job_id == first.id
    other = client.get(f"/projects/{project_id}/jobs/{extract['id']}")
    running = client.get(f"/projects/{project_id}/jobs/{first.id}")
    assert running.json()["status"] == STATUS_RUNNING
    assert other.json()["status"] == STATUS_QUEUED
    worker.execute(first)
    claimed = worker.claim_one()
    assert claimed is not None
    assert claimed.id != first.id


def test_timeout_retry_and_dead_letter() -> None:
    client, sink, _ = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    job = _enqueue(
        client,
        project_id,
        "plan",
        {"scene_id": data["scene"]["id"], "snapshot_id": data["snapshot"]["id"]},
        max_attempts=2,
    )
    clock = _Clock()
    calls = {"n": 0}

    def fail(_job: object, _inputs: dict) -> dict:
        calls["n"] += 1
        raise WorkerDispatchError("forced_failure", "test_retry")

    worker = Worker(
        job_repository=client.app.state.job_repository,
        audit_writer=client.app.state.audit_writer,
        dispatch_fn=fail,
        now_fn=clock,
        timeout_s=1.0,
        base_backoff_s=0.0,
    )
    claimed = worker.claim_one()
    assert claimed is not None
    assert claimed.status == STATUS_RUNNING
    clock.advance(2)
    worker.reclaim_timed_out()
    retried = client.get(f"/projects/{project_id}/jobs/{job['id']}")
    assert retried.json()["status"] == STATUS_QUEUED
    assert retried.json()["error_code"] == "timeout"
    assert retried.json()["attempt_count"] == 1
    again = worker.run_once()
    assert again is not None
    dead = client.get(f"/projects/{project_id}/jobs/{job['id']}")
    assert dead.json()["status"] == STATUS_DEAD_LETTER
    assert dead.json()["error_code"] == "forced_failure"
    assert dead.json()["attempt_count"] == 2
    kept = client.get(f"/projects/{project_id}/jobs/{job['id']}")
    assert kept.status_code == 200
    assert any(event.action == "job.dead_letter" for event in sink.events)
    assert calls["n"] == 1


def test_manual_rerun_from_dead_letter() -> None:
    client, _, _ = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    job = _enqueue(
        client,
        project_id,
        "plan",
        {"scene_id": data["scene"]["id"], "snapshot_id": data["snapshot"]["id"]},
        max_attempts=1,
    )

    def fail(_job: object, _inputs: dict) -> dict:
        raise WorkerDispatchError("forced_failure", "test_rerun")

    worker = Worker(
        job_repository=client.app.state.job_repository,
        audit_writer=client.app.state.audit_writer,
        dispatch_fn=fail,
        timeout_s=30.0,
        base_backoff_s=0.0,
    )
    worker.run_once()
    dead = client.get(f"/projects/{project_id}/jobs/{job['id']}")
    assert dead.json()["status"] == STATUS_DEAD_LETTER
    forbidden = client.post(
        f"/projects/{project_id}/jobs/{job['id']}/rerun",
        headers=SYSTEM,
        json={},
    )
    assert forbidden.status_code == 403
    rerun = client.post(
        f"/projects/{project_id}/jobs/{job['id']}/rerun",
        headers=HUMAN,
        json={},
    )
    assert rerun.status_code == 200, rerun.text
    item = rerun.json()["item"]
    assert item["id"] != job["id"]
    assert item["payload_reference"] == job["payload_reference"]
    assert item["rerun_of_job_id"] == job["id"]
    assert item["status"] == STATUS_QUEUED
    original = client.get(f"/projects/{project_id}/jobs/{job['id']}")
    assert original.json()["status"] == STATUS_DEAD_LETTER


def test_replay_uses_stored_payload_reference() -> None:
    client, _, _ = _client(job_auto_run=True)
    data = _pipeline(client)
    project_id = data["project"]["id"]
    payload = {
        "scene_id": data["scene"]["id"],
        "snapshot_id": data["snapshot"]["id"],
    }
    first = _enqueue(client, project_id, "plan", payload)
    assert first["status"] == STATUS_SUCCEEDED
    assert first["payload_reference"]
    worker: Worker = client.app.state.worker
    assert (
        worker.last_dispatched_inputs[first["id"]]["snapshot_id"]
        == (data["snapshot"]["id"])
    )
    # Force a failed sibling so rerun is allowed on a failed row, then
    # replay the succeeded job's payload_reference via a new enqueue.
    replay = _enqueue(
        client,
        project_id,
        "plan",
        payload,
        payload_reference=first["payload_reference"],
        idempotency_key="replay-2",
    )
    assert replay["payload_reference"] == first["payload_reference"]
    assert replay["id"] != first["id"]
    assert replay["status"] == STATUS_SUCCEEDED
    assert (
        worker.last_dispatched_inputs[replay["id"]]
        == (worker.last_dispatched_inputs[first["id"]])
    )


def test_worker_dispatches_existing_services_without_canon() -> None:
    client, sink, canon = _client(job_auto_run=True)
    data = _pipeline(client)
    project_id = data["project"]["id"]
    scene_id = data["scene"]["id"]
    before = _canon_fact_count(canon, project_id)
    validate = _enqueue(
        client,
        project_id,
        "validate",
        {
            "scene_id": scene_id,
            "candidate_ids": [data["candidate"]["id"]],
            "snapshot_id": data["snapshot"]["id"],
        },
    )
    assert validate["status"] == STATUS_SUCCEEDED
    assert validate["writes_canon"] is False
    summarize = _enqueue(
        client,
        project_id,
        "summarize",
        {"scene_id": scene_id, "draft_revision_id": data["draft"]["id"]},
    )
    assert summarize["status"] == STATUS_SUCCEEDED
    pack = _enqueue(
        client,
        project_id,
        "context_pack",
        {
            "scene_id": scene_id,
            "snapshot_id": data["snapshot"]["id"],
            "purpose": "Generate",
        },
    )
    assert pack["status"] == STATUS_SUCCEEDED
    assert _canon_fact_count(canon, project_id) == before
    candidate = client.get(
        f"/projects/{project_id}/candidate-changes/{data['candidate']['id']}"
    )
    assert candidate.json()["status"] not in {CANDIDATE_APPROVED, CANDIDATE_SUBMITTED}
    system_submit = client.post(
        f"/projects/{project_id}/candidate-changes/{data['candidate']['id']}/submit",
        headers=SYSTEM,
        json={"created_by": "sys", "entity_type": "物品"},
    )
    assert system_submit.status_code == 403
    assert _canon_fact_count(canon, project_id) == before
    assert not any(
        "submit" in event.action
        for event in sink.events
        if event.action.startswith("job.")
    )
    assert not any(
        event.action.endswith(".approve") and event.actor_type == "system"
        for event in sink.events
        if event.resource_type == "job"
    )


def test_non_human_cannot_write_canon_via_worker() -> None:
    client, _, canon = _client(job_auto_run=True)
    data = _pipeline(client)
    project_id = data["project"]["id"]
    before = _canon_fact_count(canon, project_id)
    job = _enqueue(
        client,
        project_id,
        "extract",
        {"scene_id": data["scene"]["id"], "revision_id": data["draft"]["id"]},
        headers=SYSTEM,
        idempotency_key="extract-sys",
    )
    assert job["status"] == STATUS_SUCCEEDED
    assert job["actor_type"] == "system"
    assert _canon_fact_count(canon, project_id) == before
    review_queue = client.post(
        f"/projects/{project_id}/review-queue/items",
        headers=SYSTEM,
        json={
            "subject_type": "candidate_change",
            "subject_id": data["candidate"]["id"],
        },
    )
    assert review_queue.status_code in {201, 403}
    if review_queue.status_code == 201:
        decide = client.post(
            f"/projects/{project_id}/review-queue/{review_queue.json()['id']}/approve",
            headers=SYSTEM,
            json={"reason_code": "nope"},
        )
        assert decide.status_code == 403
    assert _canon_fact_count(canon, project_id) == before


def test_cancel_keeps_record() -> None:
    client, _, _ = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    job = _enqueue(
        client,
        project_id,
        "plan",
        {"scene_id": data["scene"]["id"], "snapshot_id": data["snapshot"]["id"]},
    )
    denied = client.post(
        f"/projects/{project_id}/jobs/{job['id']}/cancel",
        headers=REVIEW,
        json={},
    )
    assert denied.status_code == 403
    cancelled = client.post(
        f"/projects/{project_id}/jobs/{job['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["kept"] is True
    assert cancelled.json()["item"]["status"] == "cancelled"
    fetched = client.get(f"/projects/{project_id}/jobs/{job['id']}")
    assert fetched.status_code == 200
    listed = client.get(f"/projects/{project_id}/jobs?status=cancelled")
    assert any(item["id"] == job["id"] for item in listed.json()["items"])


def test_audit_redacts_prompt_and_body() -> None:
    client, sink, _ = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    _enqueue(
        client,
        project_id,
        "plan",
        {
            "scene_id": data["scene"]["id"],
            "snapshot_id": data["snapshot"]["id"],
            "prompt": "完整 Prompt 不得入审计",
            "body": "完整散文不得入审计",
            "api_key": "sk-test-not-real",
        },
    )
    payload_events = [
        event for event in sink.events if event.action == "job_payload.create"
    ]
    assert payload_events
    after = payload_events[0].after_json or {}
    refs = after.get("input_refs") or {}
    if "prompt" in refs:
        assert refs["prompt"] != "完整 Prompt 不得入审计"
        assert isinstance(refs["prompt"], dict)
        assert refs["prompt"].get("redacted") is True
    if "body" in refs:
        assert refs["body"] != "完整散文不得入审计"
    if "api_key" in refs:
        assert refs["api_key"] == REDACTED
    blob = str(after)
    assert "完整 Prompt 不得入审计" not in blob
    assert "完整散文不得入审计" not in blob
    assert "sk-test-not-real" not in blob


def test_worker_source_is_dispatcher_only() -> None:
    package = ROOT / "backend" / "slove_context" / "jobs"
    text = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
    assert "approve_candidate" not in text
    assert "submit_candidate" not in text
    assert "approval_service" not in text
    assert "review_queue" not in text
    assert "agent_registry" not in text
    assert "openai" not in text.lower()
    assert "anthropic" not in text.lower()
    for name in ("openai", "anthropic", "langchain", "chromadb", "pgvector"):
        assert f"import {name}" not in text
        assert f"from {name}" not in text
    assert "dispatch_existing" in text
    assert "WRITE_JOB_TYPES" in text


def test_migration_adds_jobs_without_rebuilding_prior() -> None:
    versions = ROOT / "backend" / "alembic" / "versions"
    create = (versions / "018_create_jobs.py").read_text(encoding="utf-8")
    assert "CREATE TABLE jobs" in create
    assert "CREATE TABLE job_payloads" in create
    assert "CREATE TABLE job_locks" in create
    assert "payload_reference" in create
    assert "idempotency_key" in create
    assert "attempt_count" in create
    assert "max_attempts" in create
    assert "scheduled_at" in create
    assert "started_at" in create
    assert "finished_at" in create
    assert "error_code" in create
    assert "error_detail" in create
    assert "correlation_id" in create
    assert "dead_letter" in create
    assert "CREATE TABLE review_queue_items" not in create
    assert "CREATE TABLE scene_drafts" not in create
    assert "CREATE TABLE validation_runs" not in create
    assert 'down_revision: str | None = "017_review_queue"' in create
    upgrade = create.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    lowered = upgrade.lower()
    assert "vector(" not in lowered
    assert "embedding" not in lowered
    assert "openai" not in lowered
    assert "agent_registry" not in lowered
    draft_service = (
        ROOT / "backend" / "slove_context" / "scene_draft" / "service.py"
    ).read_text(encoding="utf-8")
    assert "from slove_context.jobs" not in draft_service
    validation_rules = (
        ROOT / "backend" / "slove_context" / "validation" / "rules.py"
    ).read_text(encoding="utf-8")
    assert "from slove_context.jobs" not in validation_rules
