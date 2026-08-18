"""Scene Draft generation jobs (node 3.4).

Fake Provider fixtures only. In-memory repositories. No live Postgres.
No network. No automatic fact extraction. Jobs do not write Canon.
Drafts are immutable revisions and never auto-approved.
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
from slove_context.scene_draft.context_pack import STATIC_CONTEXT_PACK_ID
from slove_context.scene_draft.metrics import content_hash, word_count_estimate
from slove_context.scene_draft.prompt import load_prompt_template, prompt_version
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.scene_plan.repository import InMemoryScenePlanRepository
from slove_context.story.repository import InMemoryStoryRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}
FIXTURE_PROSE = "FAKE_SCENE_DRAFT_PROSE：河滩风冷，林晚看见一点光，伸手拾起残玉。"


def _client(
    *,
    task_type: str = "scene_draft",
    auto_run: bool = True,
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
        scene_draft_repository=InMemorySceneDraftRepository(),
        audit_writer=writer,
        llm_gateway=LlmGateway(
            fake,
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
        scene_draft_task_type=task_type,
        scene_draft_auto_run=auto_run,
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


def _create_plan(
    client: TestClient, project_id: str, scene_id: str, snapshot_id: str
) -> dict:
    created = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot_id},
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "succeeded"
    current = client.get(f"/projects/{project_id}/scenes/{scene_id}/plans/current")
    assert current.status_code == 200, current.text
    return current.json()["plan"]


def _ready(
    client: TestClient,
) -> tuple[dict, dict, dict, dict]:
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"], 1)
    approved = _approve(client, project["id"], scene["id"])
    snapshot = _create_snapshot(client, project["id"])
    plan = _create_plan(client, project["id"], approved["id"], snapshot["id"])
    return project, approved, snapshot, plan


def _trigger_body(snapshot_id: str, plan_id: str, **overrides: object) -> dict:
    payload: dict = {
        "snapshot_id": snapshot_id,
        "plan_id": plan_id,
        "context_pack_id": STATIC_CONTEXT_PACK_ID,
    }
    payload.update(overrides)
    return payload


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
    assert "/projects/{project_id}/scenes/{scene_id}/drafts/jobs" in paths
    assert "/projects/{project_id}/scene-draft-jobs/{job_id}" in paths
    assert "/projects/{project_id}/scene-draft-jobs/{job_id}/cancel" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/drafts" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/scenes/{scene_id}/extract" not in paths


def test_prompt_template_has_version_and_forbids_canon() -> None:
    text = load_prompt_template()
    assert prompt_version() == "scene_draft.v1"
    assert "scene_draft.v1" in text
    assert "Canon" in text
    assert "不得" in text or "禁止" in text
    assert "整章" in text
    path = ROOT / "prompts" / "scene_draft.v1.md"
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == text


def test_success_job_persists_immutable_draft_metadata_and_audit() -> None:
    client, sink, provider = _client()
    project, scene, snapshot, plan = _ready(client)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(snapshot["id"], plan["id"]),
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "succeeded"
    assert job["draft_id"]
    assert job["draft_revision"] == 1
    assert job["scene_id"] == scene["id"]
    assert job["scene_card_id"] == scene["scene_card_id"]
    assert job["plan_id"] == plan["id"]
    assert job["snapshot_id"] == snapshot["id"]
    assert job["context_pack_id"] == STATIC_CONTEXT_PACK_ID
    assert job["prompt_version"] == "scene_draft.v1"
    assert job["is_canon"] is False
    assert job["is_approved"] is False
    assert job["is_published"] is False
    assert job["auto_approved"] is False
    assert job["writes_canon"] is False
    assert [item["to"] for item in job["transitions"]] == ["running", "succeeded"]
    assert provider.calls >= 2  # plan job + draft job

    queried = client.get(f"/projects/{project['id']}/scene-draft-jobs/{job['id']}")
    assert queried.status_code == 200
    assert queried.json()["state"] == "succeeded"

    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/drafts")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    draft = items[0]
    assert draft["id"] == job["draft_id"]
    assert draft["revision"] == 1
    assert draft["status"] == "Generated"
    assert draft["body"] == FIXTURE_PROSE
    assert draft["content_hash"] == content_hash(FIXTURE_PROSE)
    assert draft["character_count"] == len(FIXTURE_PROSE)
    assert draft["word_count_estimate"] == word_count_estimate(FIXTURE_PROSE)
    assert draft["generation_model"] == "fake-model"
    assert draft["prompt_version"] == "scene_draft.v1"
    assert draft["generated_at"]
    assert draft["input_versions"] == {
        "scene_id": scene["id"],
        "scene_card_id": scene["scene_card_id"],
        "plan_id": plan["id"],
        "snapshot_id": snapshot["id"],
        "context_pack_id": STATIC_CONTEXT_PACK_ID,
    }
    assert draft["is_canon"] is False
    assert draft["is_approved"] is False
    assert draft["is_published"] is False
    assert draft["auto_approved"] is False

    one = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft['id']}"
    )
    assert one.status_code == 200
    assert one.json()["content_hash"] == draft["content_hash"]

    actions = {event.action for event in sink.events}
    assert "scene_draft_job.create" in actions
    assert "scene_draft_job.transition" in actions
    assert "scene_draft.create" in actions
    assert not any(
        event.resource_type.startswith("canon_fact") for event in sink.events
    )
    assert not any(event.action.startswith("canon_fact") for event in sink.events)
    assert not any("extract" in event.action for event in sink.events)
    dumped = "".join(
        str(event.after_json) + str(event.before_json) for event in sink.events
    )
    assert FIXTURE_PROSE not in dumped
    assert "system_prompt" not in dumped or "redacted" in dumped
    create_events = [e for e in sink.events if e.action == "scene_draft.create"]
    assert create_events
    after = create_events[0].after_json or {}
    assert after.get("content_hash") == content_hash(FIXTURE_PROSE)
    assert "body" not in after or (
        isinstance(after.get("body"), dict) and after["body"].get("redacted")
    )


def test_retry_after_success_creates_new_revision_old_intact() -> None:
    client, _, _ = _client()
    project, scene, snapshot, plan = _ready(client)
    first = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(snapshot["id"], plan["id"], idempotency_key="k-success"),
    )
    assert first.status_code == 201, first.text
    first_job = first.json()
    first_id = first_job["draft_id"]
    first_hash = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{first_id}"
    ).json()["content_hash"]

    duplicate = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(snapshot["id"], plan["id"], idempotency_key="k-success"),
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == first_job["id"]
    assert duplicate.json()["draft_id"] == first_id

    second = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(snapshot["id"], plan["id"], idempotency_key="k-retry"),
    )
    assert second.status_code == 201, second.text
    second_job = second.json()
    assert second_job["id"] != first_job["id"]
    assert second_job["draft_id"] != first_id
    assert second_job["draft_revision"] == 2

    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/drafts")
    items = listed.json()["items"]
    assert [item["revision"] for item in items] == [2, 1]
    newest, oldest = items
    assert newest["status"] == "Generated"
    assert oldest["id"] == first_id
    assert oldest["status"] == "Superseded"
    assert oldest["content_hash"] == first_hash
    assert oldest["body"] == FIXTURE_PROSE
    assert newest["body"] == FIXTURE_PROSE
    assert newest["is_approved"] is False
    assert newest["is_published"] is False


def test_generate_failure_keeps_job_and_allows_retry() -> None:
    client, sink, provider = _client(task_type="scene_draft_fail")
    project, scene, snapshot, plan = _ready(client)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(snapshot["id"], plan["id"], idempotency_key="k-fail"),
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "failed"
    assert job["draft_id"] is None
    assert job["failure_reason"] == "provider_failed"
    assert job["evidence"] is not None
    assert job["evidence"]["request_refs"]
    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/drafts")
    assert listed.json()["items"] == []
    assert not any(event.action == "scene_draft.create" for event in sink.events)
    assert provider.calls >= 2

    retry = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(snapshot["id"], plan["id"], idempotency_key="k-fail"),
    )
    assert retry.status_code == 201
    retry_job = retry.json()
    assert retry_job["id"] != job["id"]
    assert retry_job["state"] == "failed"
    kept = client.get(f"/projects/{project['id']}/scene-draft-jobs/{job['id']}")
    assert kept.status_code == 200
    assert kept.json()["state"] == "failed"


def test_cancel_is_terminal_and_does_not_delete() -> None:
    client, _, provider = _client(auto_run=False)
    project, scene, snapshot, plan = _ready(client)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(snapshot["id"], plan["id"], idempotency_key="k-hold"),
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "queued"
    draft_calls_before_cancel = provider.calls

    duplicate = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(snapshot["id"], plan["id"], idempotency_key="k-hold"),
    )
    assert duplicate.json()["id"] == job["id"]
    assert duplicate.json()["state"] == "queued"

    blocked = client.post(
        f"/projects/{project['id']}/scene-draft-jobs/{job['id']}/cancel",
        headers=GENERATE,
        json={},
    )
    assert blocked.status_code == 403

    cancelled = client.post(
        f"/projects/{project['id']}/scene-draft-jobs/{job['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["draft_id"] is None
    assert provider.calls == draft_calls_before_cancel

    still = client.get(f"/projects/{project['id']}/scene-draft-jobs/{job['id']}")
    assert still.status_code == 200
    assert still.json()["state"] == "cancelled"

    again = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(snapshot["id"], plan["id"], idempotency_key="k-hold"),
    )
    assert again.status_code == 201
    assert again.json()["id"] != job["id"]
    assert again.json()["state"] == "queued"


def test_cannot_cancel_succeeded_job() -> None:
    client, _, _ = _client()
    project, scene, snapshot, plan = _ready(client)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=HUMAN,
        json=_trigger_body(snapshot["id"], plan["id"]),
    )
    job = created.json()
    assert job["state"] == "succeeded"
    denied = client.post(
        f"/projects/{project['id']}/scene-draft-jobs/{job['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"]["error"] == "job_not_cancellable"


def test_rejects_unapproved_card_missing_plan_snapshot_or_pack() -> None:
    client, _, provider = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    draft_scene = _create_scene(client, project["id"], chapter["id"], 1)
    snapshot = _create_snapshot(client, project["id"])
    calls_before = provider.calls

    unapproved = client.post(
        f"/projects/{project['id']}/scenes/{draft_scene['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(snapshot["id"], "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    )
    assert unapproved.status_code == 409
    assert unapproved.json()["detail"]["error"] == "scene_not_generatable"

    approved = _approve(client, project["id"], draft_scene["id"])
    missing_plan = client.post(
        f"/projects/{project['id']}/scenes/{approved['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(snapshot["id"], "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    )
    assert missing_plan.status_code == 404
    assert missing_plan.json()["detail"]["error"] == "scene_plan_not_found"

    plan = _create_plan(client, project["id"], approved["id"], snapshot["id"])
    missing_snapshot = client.post(
        f"/projects/{project['id']}/scenes/{approved['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(
            "99999999-9999-4999-8999-999999999999",
            plan["id"],
        ),
    )
    assert missing_snapshot.status_code == 404
    assert missing_snapshot.json()["detail"]["error"] == "canon_snapshot_not_found"

    missing_pack = client.post(
        f"/projects/{project['id']}/scenes/{approved['id']}/drafts/jobs",
        headers=GENERATE,
        json=_trigger_body(
            snapshot["id"],
            plan["id"],
            context_pack_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        ),
    )
    assert missing_pack.status_code == 404
    assert missing_pack.json()["detail"]["error"] == "context_pack_not_found"
    assert provider.calls == calls_before + 1  # only the plan job ran


def test_review_agent_cannot_trigger_and_no_chapter_or_extract() -> None:
    client, _, _ = _client()
    project, scene, snapshot, plan = _ready(client)
    blocked = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers={"X-Actor-Type": "review_agent", "X-Actor-Id": "rev-1"},
        json=_trigger_body(snapshot["id"], plan["id"]),
    )
    assert blocked.status_code == 403
    assert (
        client.post(f"/projects/{project['id']}/chapters/generate", json={}).status_code
        == 404
    )
    assert (
        client.post(
            f"/projects/{project['id']}/scenes/{scene['id']}/extract",
            json={},
        ).status_code
        == 404
    )


def test_scene_draft_migration_is_incremental() -> None:
    path = (
        ROOT / "backend" / "alembic" / "versions" / "007_create_scene_draft_tables.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "CREATE TABLE scene_draft_jobs" in text
    assert "CREATE TABLE scene_drafts" in text
    assert "CREATE TABLE story_projects" not in text
    assert "CREATE TABLE canon_facts" not in text
    assert "CREATE TABLE scenes" not in text
    assert "CREATE TABLE scene_plans" not in text
    assert "CREATE TABLE candidate_changes" not in text
    assert "down_revision" in text
    assert "006_scene_plan" in text


def test_scene_draft_package_has_no_vendor_http_or_extraction() -> None:
    draft_dir = ROOT / "backend" / "slove_context" / "scene_draft"
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
    for path in draft_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in text
            assert f"from {name}" not in text
        assert "extract_candidate" not in text
        assert "auto_approve" not in text or "False" in text or "forbid" in text.lower()
