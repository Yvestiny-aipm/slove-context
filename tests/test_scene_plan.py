"""Scene Plan generation jobs (node 3.3).

Fake Provider fixtures only. In-memory repositories. No live Postgres.
No network. No Scene Draft generation. Jobs do not write Canon.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_plan.prompt import load_prompt_template, prompt_version
from slove_context.scene_plan.repository import InMemoryScenePlanRepository
from slove_context.scene_plan.validate import validate_scene_plan
from slove_context.story.repository import InMemoryStoryRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}


def _client(
    *,
    task_type: str = "scene_plan",
    repair_task_type: str = "scene_plan_repair",
    provider: FakeProvider | None = None,
) -> tuple[TestClient, InMemoryAuditSink, FakeProvider]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    fake = provider or FakeProvider()
    app = create_app(
        repository=InMemoryStoryRepository(),
        canon_repository=InMemoryCanonRepository(),
        scene_repository=InMemorySceneRepository(),
        scene_plan_repository=InMemoryScenePlanRepository(),
        audit_writer=writer,
        llm_gateway=LlmGateway(
            fake,
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
        scene_plan_task_type=task_type,
        scene_plan_repair_task_type=repair_task_type,
    )
    return TestClient(app), sink, fake


def _create_project(client: TestClient) -> dict:
    response = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": "青石夜祠", "language": "zh-CN", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


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


def _scene_payload(chapter_id: str, story_order: int, **overrides: object) -> dict:
    payload: dict = {
        "chapter_id": chapter_id,
        "story_order": story_order,
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
    }
    payload.update(overrides)
    return payload


def _create_scene(
    client: TestClient,
    project_id: str,
    chapter_id: str,
    story_order: int,
    **overrides: object,
) -> dict:
    response = client.post(
        f"/projects/{project_id}/scenes",
        headers=HUMAN,
        json=_scene_payload(chapter_id, story_order, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _approve(client: TestClient, project_id: str, scene_id: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/approve",
        headers=HUMAN,
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_snapshot(client: TestClient, project_id: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/canon-snapshots",
        headers=HUMAN,
        json={
            "as_of_scene_seq": 1,
            "as_of_story_time": "day-01",
            "created_by": "主编",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _ready_scene_and_snapshot(
    client: TestClient,
) -> tuple[dict, dict, dict]:
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"], 1)
    approved = _approve(client, project["id"], scene["id"])
    assert approved["generatable"] is True
    snapshot = _create_snapshot(client, project["id"])
    return project, approved, snapshot


def test_healthz_and_prior_apis_still_present() -> None:
    client, _, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/version").json().get("version")
    paths = client.get("/openapi.json").json()["paths"]
    assert "/healthz" in paths
    assert "/version" in paths
    assert "/projects" in paths
    assert "/projects/{project_id}/specs/{spec_id}/approve" in paths
    assert "/projects/{project_id}/entities" in paths
    assert "/projects/{project_id}/canon-facts" in paths
    assert "/projects/{project_id}/canon-snapshots" in paths
    assert "/projects/{project_id}/scenes" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/plans/jobs" in paths
    assert "/projects/{project_id}/scene-plan-jobs/{job_id}" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/plans/current" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths


def test_prompt_template_has_version_requires_json_forbids_prose() -> None:
    text = load_prompt_template()
    assert prompt_version() == "scene_plan.v1"
    assert "scene_plan.v1" in text
    assert "JSON" in text
    assert "正文" in text
    assert "Scene Draft" in text
    assert "禁止" in text
    path = ROOT / "prompts" / "scene_plan.v1.md"
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == text


def test_success_job_persists_valid_plan_and_audit() -> None:
    client, sink, provider = _client()
    project, scene, snapshot = _ready_scene_and_snapshot(client)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot["id"]},
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "succeeded"
    assert job["plan_id"]
    assert job["scene_id"] == scene["id"]
    assert job["scene_card_id"] == scene["scene_card_id"]
    assert job["snapshot_id"] == snapshot["id"]
    assert job["prompt_version"] == "scene_plan.v1"
    assert job["is_canon"] is False
    assert job["is_scene_draft"] is False
    assert job["writes_canon"] is False
    assert job["repair_count"] == 0
    assert job["validation_result"]["ok"] is True
    assert job["request_refs"]
    assert job["request_refs"][0]["raw_response_reference"]
    assert [item["to"] for item in job["transitions"]] == ["running", "succeeded"]
    assert provider.calls == 1

    queried = client.get(f"/projects/{project['id']}/scene-plan-jobs/{job['id']}")
    assert queried.status_code == 200
    assert queried.json()["state"] == "succeeded"

    current = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/current"
    )
    assert current.status_code == 200, current.text
    body = current.json()
    assert body["is_canon"] is False
    assert body["is_scene_draft"] is False
    assert body["job_id"] == job["id"]
    assert body["snapshot_id"] == snapshot["id"]
    plan = body["plan"]
    validate_scene_plan(plan)
    assert plan["scene_id"] == scene["id"]
    assert plan["project_id"] == project["id"]
    assert plan["intent"]
    assert plan["beats"]
    assert plan["status"] == "Drafted"

    actions = {event.action for event in sink.events}
    assert "scene_plan_job.create" in actions
    assert "scene_plan_job.transition" in actions
    assert "scene_plan.create" in actions
    assert not any(
        event.resource_type.startswith("canon_fact") for event in sink.events
    )
    assert not any(event.action.startswith("canon_fact") for event in sink.events)
    dumped = "".join(
        str(event.after_json) + str(event.before_json) for event in sink.events
    )
    assert "system_prompt" not in dumped or "redacted" in dumped


def test_invalid_json_is_not_persisted_and_repairs_once() -> None:
    client, sink, provider = _client(
        task_type="scene_plan_invalid_json",
        repair_task_type="scene_plan_invalid_json",
    )
    project, scene, snapshot = _ready_scene_and_snapshot(client)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot["id"]},
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "failed"
    assert job["plan_id"] is None
    assert job["repair_count"] == 1
    assert job["evidence"] is not None
    assert job["evidence"]["repair_attempted"] is True
    assert job["evidence"]["validation_errors"]
    assert job["evidence"]["request_refs"]
    assert len(job["request_refs"]) == 2
    assert provider.calls == 2
    assert "repair" in {item["to"] for item in job["transitions"]}
    current = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/current"
    )
    assert current.status_code == 404
    assert current.json()["detail"]["error"] == "scene_plan_not_found"
    assert not any(event.action == "scene_plan.create" for event in sink.events)


def test_deps_not_complete_is_rejected() -> None:
    client, sink, provider = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    first = _create_scene(client, project["id"], chapter["id"], 1)
    second = _create_scene(
        client,
        project["id"],
        chapter["id"],
        2,
        story_time="第二日清晨",
        starting_state="林晚已持有残玉",
        goal="试祠门",
        location="青石镇祠堂",
        generation_boundary="只写林晚试门这一场，不写整章。",
    )
    deps = client.put(
        f"/projects/{project['id']}/scenes/{second['id']}/dependencies",
        headers=HUMAN,
        json={"depends_on": [first["id"]]},
    )
    assert deps.status_code == 200
    approved_second = _approve(client, project["id"], second["id"])
    assert approved_second["generatable"] is False
    snapshot = _create_snapshot(client, project["id"])
    created = client.post(
        f"/projects/{project['id']}/scenes/{second['id']}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot["id"]},
    )
    assert created.status_code == 409, created.text
    detail = created.json()["detail"]
    assert detail["error"] == "scene_not_generatable"
    assert first["id"] in detail["unsatisfied_dependencies"]
    assert provider.calls == 0
    current = client.get(
        f"/projects/{project['id']}/scenes/{second['id']}/plans/current"
    )
    assert current.status_code == 404
    assert not any(event.action == "scene_plan.create" for event in sink.events)

    draft = _create_scene(client, project["id"], chapter["id"], 3, story_time="第三日")
    rejected_draft = client.post(
        f"/projects/{project['id']}/scenes/{draft['id']}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot["id"]},
    )
    assert rejected_draft.status_code == 409
    assert rejected_draft.json()["detail"]["error"] == "scene_not_generatable"


def test_schema_fail_then_repair_fail_keeps_evidence() -> None:
    client, sink, provider = _client(
        task_type="scene_plan_invalid_schema",
        repair_task_type="scene_plan_repair_fail",
    )
    project, scene, snapshot = _ready_scene_and_snapshot(client)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/jobs",
        headers=HUMAN,
        json={"snapshot_id": snapshot["id"]},
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "failed"
    assert job["plan_id"] is None
    assert job["repair_count"] == 1
    assert provider.calls == 2
    evidence = job["evidence"]
    assert evidence is not None
    assert evidence["repair_attempted"] is True
    assert evidence["repair_count"] == 1
    assert evidence["validation_errors"]
    assert evidence["raw_response_references"]
    assert len(evidence["request_refs"]) == 2
    assert job["validation_result"]["ok"] is False
    assert job["failure_reason"] == "schema_validation_failed"
    states = [item["to"] for item in job["transitions"]]
    assert states == ["running", "repair", "failed"]
    current = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/current"
    )
    assert current.status_code == 404
    assert not any(event.action == "scene_plan.create" for event in sink.events)
    queried = client.get(f"/projects/{project['id']}/scene-plan-jobs/{job['id']}")
    assert queried.status_code == 200
    assert queried.json()["evidence"]["validation_errors"]


def test_missing_snapshot_and_unknown_job() -> None:
    client, _, _ = _client()
    project, scene, _snapshot = _ready_scene_and_snapshot(client)
    missing = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": "99999999-9999-4999-8999-999999999999"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["error"] == "canon_snapshot_not_found"
    unknown = client.get(
        f"/projects/{project['id']}/scene-plan-jobs/"
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    )
    assert unknown.status_code == 404


def test_review_agent_cannot_trigger_and_no_chapter_draft() -> None:
    client, _, _ = _client()
    project, scene, snapshot = _ready_scene_and_snapshot(client)
    blocked = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/jobs",
        headers={"X-Actor-Type": "review_agent", "X-Actor-Id": "rev-1"},
        json={"snapshot_id": snapshot["id"]},
    )
    assert blocked.status_code == 403
    assert (
        client.post(f"/projects/{project['id']}/chapters/generate", json={}).status_code
        == 404
    )


def test_scene_plan_migration_is_incremental() -> None:
    path = ROOT / "backend" / "alembic" / "versions" / "006_create_scene_plan_tables.py"
    text = path.read_text(encoding="utf-8")
    assert "CREATE TABLE scene_plan_jobs" in text
    assert "CREATE TABLE scene_plans" in text
    assert "CREATE TABLE scene_drafts" not in text
    assert "CREATE TABLE story_projects" not in text
    assert "CREATE TABLE canon_facts" not in text
    assert "CREATE TABLE scenes" not in text
    assert "down_revision" in text
    assert "005_scene_tables" in text


def test_scene_plan_package_has_no_vendor_http_or_draft_generator() -> None:
    plan_dir = ROOT / "backend" / "slove_context" / "scene_plan"
    forbidden = (
        "openai",
        "anthropic",
        "langchain",
        "chromadb",
        "pgvector",
        "faiss",
        "requests",
        "aiohttp",
    )
    for path in plan_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in text
            assert f"from {name}" not in text
        assert "scene_draft" not in text or "forbid" in text.lower() or "not" in text
        assert "generate_scene_draft" not in text
