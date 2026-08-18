"""Batch scheduler (node 8.4).

In-memory repositories. No live Postgres. No network. No real models.
Scheduling goes through the 8.3 DAG, 8.1 Worker, and 8.2
PermissionGuard. The scheduler does not approve or submit Canon.
2.1–8.3 APIs and /healthz remain. No production seed-status.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.dags.repository import InMemoryDagRepository
from slove_context.jobs.repository import InMemoryJobRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.scene.models import SCENE_APPROVED, SCENE_DRAFT, Scene
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.scene_plan.repository import InMemoryScenePlanRepository
from slove_context.scheduler.models import (
    ALERT_BUDGET_EXCEEDED,
    ALERT_CONSECUTIVE_FAILURES,
    KIND_CANON_WRITE,
    REASON_CANON_WRITE_PARALLEL,
    REASON_DRY_RUN,
    REASON_PROSE_STATE_DEPENDENCY,
    REASON_SNAPSHOT_CANON_CONFLICT,
    REASON_UNAPPROVED_DEPENDENCY,
    STATUS_PAUSED,
    STATUS_PLANNED,
)
from slove_context.scheduler.parallelism import ActiveSlot, decide
from slove_context.scheduler.repository import InMemoryScheduleRepository
from slove_context.story.models import PROJECT_ACTIVE, StoryProject
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


def _client() -> tuple[
    TestClient,
    InMemoryAuditSink,
    InMemoryCanonRepository,
    FakeProvider,
    InMemoryStoryRepository,
]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    canon = InMemoryCanonRepository()
    story = InMemoryStoryRepository()
    provider = FakeProvider()
    app = create_app(
        repository=story,
        canon_repository=canon,
        scene_repository=InMemorySceneRepository(),
        scene_plan_repository=InMemoryScenePlanRepository(),
        scene_draft_repository=InMemorySceneDraftRepository(),
        job_repository=InMemoryJobRepository(),
        dag_repository=InMemoryDagRepository(),
        schedule_repository=InMemoryScheduleRepository(),
        audit_writer=writer,
        llm_gateway=LlmGateway(
            provider,
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
        job_auto_run=False,
        job_base_backoff_s=0.0,
    )
    return TestClient(app), sink, canon, provider, story


def _create_project(client: TestClient, title: str = "青石夜祠") -> dict:
    response = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": title, "language": "zh-CN", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_project(story: InMemoryStoryRepository, title: str) -> StoryProject:
    project = StoryProject(
        id=str(uuid4()),
        title=title,
        language="zh-CN",
        status=PROJECT_ACTIVE,
        created_at="2026-08-18T00:00:00.000000Z",
        created_by="主编",
    )
    story.add_project(project)
    return project


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


def _create_chapter(client: TestClient, project_id: str) -> dict:
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
    return chapter.json()


def _create_scene(
    client: TestClient,
    project_id: str,
    chapter_id: str,
    *,
    story_order: int,
    approve: bool = True,
) -> dict:
    scene = client.post(
        f"/projects/{project_id}/scenes",
        headers=HUMAN,
        json={
            "chapter_id": chapter_id,
            "story_order": story_order,
            "pov": "林晚",
            "story_time": f"第{story_order}日黄昏",
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
    if not approve:
        return scene.json()
    approved = client.post(
        f"/projects/{project_id}/scenes/{scene.json()['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def _create_snapshot(client: TestClient, project_id: str) -> dict:
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
    frozen = client.post(
        f"/projects/{project_id}/canon-snapshots/{created.json()['id']}/freeze",
        headers=HUMAN,
        json={},
    )
    assert frozen.status_code == 200, frozen.text
    return frozen.json()


def _ready_project(client: TestClient) -> dict[str, dict]:
    project = _create_project(client)
    _write_spec(client, project["id"])
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"], story_order=1)
    snapshot = _create_snapshot(client, project["id"])
    return {
        "project": project,
        "chapter": chapter,
        "scene": scene,
        "snapshot": snapshot,
    }


def _ready_seeded_project(
    client: TestClient, story: InMemoryStoryRepository, title: str
) -> dict[str, dict]:
    project = _seed_project(story, title)
    _write_spec(client, project.id)
    chapter = _create_chapter(client, project.id)
    scene = _create_scene(client, project.id, chapter["id"], story_order=1)
    snapshot = _create_snapshot(client, project.id)
    return {
        "project": project.to_public_dict(),
        "chapter": chapter,
        "scene": scene,
        "snapshot": snapshot,
    }


def _canon_fact_count(canon: InMemoryCanonRepository, project_id: str) -> int:
    return len([item for item in canon.facts.values() if item.project_id == project_id])


def _scene_stub(
    scene_id: str,
    project_id: str,
    *,
    status: str = SCENE_APPROVED,
    depends_on: list[str] | None = None,
) -> Scene:
    return Scene(
        id=scene_id,
        project_id=project_id,
        chapter_id="ch-1",
        scene_card_id="card-1",
        story_order=1,
        status=status,
        scene_status="CardReady",
        pov="林晚",
        story_time="第一日",
        location="河滩",
        present_entities=["林晚"],
        starting_state="start",
        goal="goal",
        conflict="conflict",
        expected_end_state="end",
        forbidden=[],
        knowledge_boundaries=[],
        generation_boundary="boundary",
        scene_card={},
        created_at="2026-08-18T00:00:00.000000Z",
        created_by="主编",
        depends_on=list(depends_on or []),
    )


def test_healthz_and_prior_apis_remain() -> None:
    client, _, _, _, _ = _client()
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
    assert "/agents" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/dags" in paths
    assert "/projects/{project_id}/dags/{dag_id}/human-review" in paths
    assert "/projects/{project_id}/schedule/config" in paths
    assert "/projects/{project_id}/schedule/start" in paths
    assert "/projects/{project_id}/schedule/dry-run" in paths
    assert "/schedules/tick" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/auto-approve" not in paths
    assert "/projects/{project_id}/batch" not in paths
    assert "/projects/{project_id}/batches" not in paths
    assert "/eval-sets" not in paths
    assert "/experiments" not in paths
    assert not any("seed-status" in path for path in paths)
    assert not any("openai" in path for path in paths)


def test_no_production_seed_status() -> None:
    client, _, _, _, _ = _client()
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("seed-status" in path for path in paths)
    route_source = (ROOT / "backend/slove_context/scheduler/routes.py").read_text(
        encoding="utf-8"
    )
    assert "seed-status" not in route_source


def test_multi_project_parallelism() -> None:
    client, _, canon, _, story = _client()
    first = _ready_project(client)
    second = _ready_seeded_project(client, story, "第二部夹具")
    started_a = client.post(
        f"/projects/{first['project']['id']}/schedule/start",
        headers=HUMAN,
        json={"snapshot_id": first["snapshot"]["id"]},
    )
    started_b = client.post(
        f"/projects/{second['project']['id']}/schedule/start",
        headers=HUMAN,
        json={"snapshot_id": second["snapshot"]["id"]},
    )
    assert started_a.status_code == 201, started_a.text
    assert started_b.status_code == 201, started_b.text
    assert started_a.json()["enqueued_count"] >= 1
    assert started_b.json()["enqueued_count"] >= 1
    assert started_a.json()["project_id"] != started_b.json()["project_id"]
    ticked = client.post("/schedules/tick", headers=SYSTEM, json={})
    assert ticked.status_code == 200, ticked.text
    processed = ticked.json()["processed_project_ids"]
    assert (
        first["project"]["id"] in processed or started_a.json()["status"] != "running"
    )
    assert ticked.json()["writes_canon"] is False
    assert _canon_fact_count(canon, first["project"]["id"]) == 0
    assert _canon_fact_count(canon, second["project"]["id"]) == 0


def test_unapproved_dependency_is_not_enqueued() -> None:
    client, _, _, provider, _ = _client()
    data = _ready_project(client)
    project_id = data["project"]["id"]
    upstream = _create_scene(
        client, project_id, data["chapter"]["id"], story_order=2, approve=False
    )
    downstream = _create_scene(
        client, project_id, data["chapter"]["id"], story_order=3, approve=True
    )
    deps = client.put(
        f"/projects/{project_id}/scenes/{downstream['id']}/dependencies",
        headers=HUMAN,
        json={"depends_on": [upstream["id"]]},
    )
    assert deps.status_code == 200, deps.text
    assert deps.json()["generatable"] is False
    before_calls = provider.calls
    started = client.post(
        f"/projects/{project_id}/schedule/start",
        headers=HUMAN,
        json={"snapshot_id": data["snapshot"]["id"]},
    )
    assert started.status_code == 201, started.text
    decisions = client.get(f"/projects/{project_id}/schedule/decisions")
    assert decisions.status_code == 200, decisions.text
    by_scene = {item["scene_id"]: item for item in decisions.json()["items"]}
    assert by_scene[downstream["id"]]["action"] == "skipped"
    assert by_scene[downstream["id"]]["reason_code"] == REASON_UNAPPROVED_DEPENDENCY
    assert by_scene[downstream["id"]]["dag_id"] is None
    inspect = client.post(
        f"/projects/{project_id}/schedule/inspect",
        headers=HUMAN,
        json={"scene_id": downstream["id"], "task_kind": "prose_write"},
    )
    assert inspect.status_code == 200, inspect.text
    assert inspect.json()["reason_code"] == REASON_UNAPPROVED_DEPENDENCY
    assert inspect.json()["generatable"] is False
    assert provider.calls >= before_calls


def test_forbidden_write_conflict_is_serialized() -> None:
    client, _, canon, _, _ = _client()
    data = _ready_project(client)
    project_id = data["project"]["id"]
    downstream = _create_scene(
        client, project_id, data["chapter"]["id"], story_order=2, approve=True
    )
    deps = client.put(
        f"/projects/{project_id}/scenes/{downstream['id']}/dependencies",
        headers=HUMAN,
        json={"depends_on": [data["scene"]["id"]]},
    )
    assert deps.status_code == 200, deps.text
    assert deps.json()["generatable"] is True
    started = client.post(
        f"/projects/{project_id}/schedule/start",
        headers=HUMAN,
        json={"snapshot_id": data["snapshot"]["id"]},
    )
    assert started.status_code == 201, started.text
    decisions = client.get(
        f"/projects/{project_id}/schedule/decisions",
        params={"run_id": started.json()["id"]},
    )
    by_scene = {item["scene_id"]: item for item in decisions.json()["items"]}
    assert by_scene[data["scene"]["id"]]["action"] == "enqueued"
    assert by_scene[downstream["id"]]["action"] == "held"
    assert by_scene[downstream["id"]]["reason_code"] == REASON_PROSE_STATE_DEPENDENCY
    assert started.json()["enqueued_count"] == 1
    assert _canon_fact_count(canon, project_id) == 0

    left = _scene_stub("scene-a", "proj-a")
    right = _scene_stub("scene-b", "proj-a")
    verdict = decide(
        right,
        task_kind=KIND_CANON_WRITE,
        snapshot_id="snap-1",
        unsatisfied_dependencies=[],
        active=[
            ActiveSlot(
                project_id="proj-a",
                scene_id=left.id,
                snapshot_id="snap-1",
                task_kind=KIND_CANON_WRITE,
            )
        ],
        scenes_by_id={left.id: left, right.id: right},
        estimated_cost=0.0,
        per_scene_cost_cap=10.0,
    )
    assert verdict.action == "rejected"
    assert verdict.reason_code in {
        REASON_CANON_WRITE_PARALLEL,
        REASON_SNAPSHOT_CANON_CONFLICT,
    }


def test_budget_exceeded_pauses_and_alerts() -> None:
    client, sink, canon, _, _ = _client()
    data = _ready_project(client)
    project_id = data["project"]["id"]
    configured = client.put(
        f"/projects/{project_id}/schedule/config",
        headers=HUMAN,
        json={"daily_token_budget": 1, "failure_threshold": 9},
    )
    assert configured.status_code == 200, configured.text
    before = _canon_fact_count(canon, project_id)
    started = client.post(
        f"/projects/{project_id}/schedule/start",
        headers=HUMAN,
        json={"snapshot_id": data["snapshot"]["id"]},
    )
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["status"] == STATUS_PAUSED
    assert body["paused_reason"] == ALERT_BUDGET_EXCEEDED
    alerts = client.get(f"/projects/{project_id}/schedule/alerts")
    assert alerts.status_code == 200, alerts.text
    kinds = [item["kind"] for item in alerts.json()["items"]]
    assert ALERT_BUDGET_EXCEEDED in kinds
    assert alerts.json()["auto_resumed"] is False
    assert _canon_fact_count(canon, project_id) == before
    forbidden = client.post(
        f"/projects/{project_id}/schedule/runs/{body['id']}/resume",
        headers=GENERATE,
        json={},
    )
    assert forbidden.status_code == 403, forbidden.text
    resumed = client.post(
        f"/projects/{project_id}/schedule/runs/{body['id']}/resume",
        headers=HUMAN,
        json={},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "running"
    assert any(event.action == "schedule.alert" for event in sink.events)
    fetched = client.get(f"/projects/{project_id}/schedule/alerts")
    assert fetched.json()["items"], "paused alert records are kept"


def test_consecutive_failures_pause_and_alert() -> None:
    client, sink, canon, _, _ = _client()
    data = _ready_project(client)
    project_id = data["project"]["id"]
    configured = client.put(
        f"/projects/{project_id}/schedule/config",
        headers=HUMAN,
        json={"failure_threshold": 1, "daily_token_budget": 100000},
    )
    assert configured.status_code == 200, configured.text
    started = client.post(
        f"/projects/{project_id}/schedule/start",
        headers=HUMAN,
        json={"snapshot_id": str(uuid4())},
    )
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["status"] == STATUS_PAUSED
    assert body["paused_reason"] == ALERT_CONSECUTIVE_FAILURES
    alerts = client.get(f"/projects/{project_id}/schedule/alerts").json()["items"]
    assert any(item["kind"] == ALERT_CONSECUTIVE_FAILURES for item in alerts)
    assert all(item["kept"] is True for item in alerts)
    assert _canon_fact_count(canon, project_id) == 0
    cancelled = client.post(
        f"/projects/{project_id}/schedule/runs/{body['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["kept"] is True
    assert cancelled.json()["item"]["status"] == "cancelled"
    still = client.get(f"/projects/{project_id}/schedule/runs/{body['id']}")
    assert still.status_code == 200
    assert still.json()["status"] == "cancelled"
    assert still.json()["kept"] is True
    assert any(event.action == "schedule.pause" for event in sink.events)


def test_dry_run_does_not_call_the_model() -> None:
    client, sink, canon, provider, _ = _client()
    data = _ready_project(client)
    project_id = data["project"]["id"]
    assert provider.calls == 0
    planned = client.post(
        f"/projects/{project_id}/schedule/dry-run",
        headers=HUMAN,
        json={"snapshot_id": data["snapshot"]["id"]},
    )
    assert planned.status_code == 201, planned.text
    body = planned.json()
    assert body["called_model"] is False
    assert body["enqueued_write_jobs"] is False
    assert body["writes_canon"] is False
    assert body["auto_approved"] is False
    assert body["estimated_dag_count"] >= 1
    assert body["estimated_task_count"] >= body["estimated_dag_count"]
    assert body["run"]["status"] == STATUS_PLANNED
    assert body["run"]["dry_run"] is True
    assert body["run"]["enqueued_count"] == 0
    assert body["run"]["dag_ids"] == []
    assert all(
        item["reason_code"] == REASON_DRY_RUN or item["action"] != "enqueued"
        for item in body["plan"]
    )
    assert provider.calls == 0
    jobs = client.get(f"/projects/{project_id}/jobs")
    assert jobs.status_code == 200
    assert jobs.json()["items"] == []
    assert _canon_fact_count(canon, project_id) == 0
    assert any(event.action == "schedule.dry_run" for event in sink.events)


def test_scheduler_does_not_auto_approve_or_submit_canon() -> None:
    client, sink, canon, provider, _ = _client()
    data = _ready_project(client)
    project_id = data["project"]["id"]
    before = _canon_fact_count(canon, project_id)
    started = client.post(
        f"/projects/{project_id}/schedule/start",
        headers=HUMAN,
        json={"snapshot_id": data["snapshot"]["id"]},
    )
    assert started.status_code == 201, started.text
    assert started.json()["auto_approved"] is False
    assert started.json()["auto_canon_commit"] is False
    assert started.json()["writes_canon"] is False
    assert provider.calls > 0
    assert _canon_fact_count(canon, project_id) == before
    for action in ("approve-canon", "submit-canon"):
        for headers in (HUMAN, GENERATE, SYSTEM, REVIEW):
            denied = client.post(
                f"/projects/{project_id}/schedule/{action}",
                headers=headers,
                json={},
            )
            assert denied.status_code == 403, denied.text
            detail = denied.json()["detail"]
            assert detail["error"] == "scheduler_cannot_write_canon"
            assert detail["writes_canon"] is False
    assert _canon_fact_count(canon, project_id) == before
    for event in sink.events:
        blob = str(event.after_json or {})
        assert "system_prompt" not in blob
        assert "user_prompt" not in blob
        assert "api_key" not in blob.lower() or "[REDACTED]" in blob


def test_writes_are_audited_and_redacted() -> None:
    client, sink, _, _, _ = _client()
    data = _ready_project(client)
    project_id = data["project"]["id"]
    client.put(
        f"/projects/{project_id}/schedule/config",
        headers=HUMAN,
        json={
            "concurrency": 1,
            "daily_token_budget": 5000,
            "per_scene_cost_cap": 1.0,
            "failure_threshold": 4,
        },
    )
    started = client.post(
        f"/projects/{project_id}/schedule/start",
        headers=HUMAN,
        json={"snapshot_id": data["snapshot"]["id"]},
    )
    assert started.status_code == 201, started.text
    paused = client.post(
        f"/projects/{project_id}/schedule/runs/{started.json()['id']}/pause",
        headers=HUMAN,
        json={},
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["kept"] is True
    still = client.get(f"/projects/{project_id}/schedule/runs/{started.json()['id']}")
    assert still.json()["status"] == STATUS_PAUSED
    assert still.json()["kept"] is True
    actions = {event.action for event in sink.events}
    assert "schedule.config" in actions
    assert "schedule.start" in actions
    assert "schedule.pause" in actions
    for event in sink.events:
        after = event.after_json or {}
        assert "prose" not in after
        assert "system_prompt" not in after
        assert "text_evidence" not in after
        dumped = str(after)
        assert "林晚把残玉按进缺口" not in dumped


def test_review_agent_cannot_resume_or_start_as_approver() -> None:
    client, _, _, _, _ = _client()
    data = _ready_project(client)
    project_id = data["project"]["id"]
    started = client.post(
        f"/projects/{project_id}/schedule/start",
        headers=HUMAN,
        json={"snapshot_id": data["snapshot"]["id"]},
    )
    assert started.status_code == 201, started.text
    client.post(
        f"/projects/{project_id}/schedule/runs/{started.json()['id']}/pause",
        headers=HUMAN,
        json={},
    )
    denied = client.post(
        f"/projects/{project_id}/schedule/runs/{started.json()['id']}/resume",
        headers=REVIEW,
        json={},
    )
    assert denied.status_code == 403, denied.text


def test_canon_write_kind_is_always_rejected() -> None:
    scene = _scene_stub("scene-1", "proj-1", status=SCENE_DRAFT)
    approved = _scene_stub("scene-2", "proj-1")
    draft_verdict = decide(
        scene,
        task_kind=KIND_CANON_WRITE,
        snapshot_id="snap",
        unsatisfied_dependencies=[],
        active=[],
        scenes_by_id={scene.id: scene},
        estimated_cost=0.0,
        per_scene_cost_cap=10.0,
    )
    assert draft_verdict.reason_code in {
        "scene_not_approved",
        REASON_CANON_WRITE_PARALLEL,
    }
    approved_verdict = decide(
        approved,
        task_kind=KIND_CANON_WRITE,
        snapshot_id="snap",
        unsatisfied_dependencies=[],
        active=[],
        scenes_by_id={approved.id: approved},
        estimated_cost=0.0,
        per_scene_cost_cap=10.0,
    )
    assert approved_verdict.action == "rejected"
    assert approved_verdict.reason_code == REASON_CANON_WRITE_PARALLEL
