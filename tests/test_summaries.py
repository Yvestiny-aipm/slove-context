"""Scene / Chapter summary jobs (node 4.3).

Fake Provider fixtures only. In-memory repositories. No live Postgres.
No network. Summaries are not Canon, not Scene Draft, and not Candidate
Changes. Chapter jobs roll up scene summaries; there is no chapter-level
prose generate entrance.
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
from slove_context.scene_draft.metrics import content_hash
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.scene_plan.repository import InMemoryScenePlanRepository
from slove_context.story.repository import InMemoryStoryRepository
from slove_context.summary.prompt import (
    chapter_prompt_version,
    load_chapter_prompt_template,
    load_scene_prompt_template,
    scene_prompt_version,
)
from slove_context.summary.repository import InMemorySummaryRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}
FIXTURE_PROSE = "FAKE_SCENE_DRAFT_PROSE：河滩风冷，林晚看见一点光，伸手拾起残玉。"
FIXTURE_SCENE_SUMMARY = "FAKE_SCENE_SUMMARY：林晚在河滩拾得残玉。"
FIXTURE_CHAPTER_SUMMARY = "FAKE_CHAPTER_SUMMARY：本章由各场场景摘要汇总，林晚得玉。"


def _client(
    *,
    scene_task_type: str = "scene_summary",
    chapter_task_type: str = "chapter_summary",
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
        summary_repository=InMemorySummaryRepository(),
        audit_writer=writer,
        llm_gateway=LlmGateway(
            fake,
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
        scene_summary_task_type=scene_task_type,
        chapter_summary_task_type=chapter_task_type,
        summary_auto_run=auto_run,
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
    current = client.get(f"/projects/{project_id}/scenes/{scene_id}/plans/current")
    assert current.status_code == 200, current.text
    return current.json()["plan"]


def _create_draft(
    client: TestClient, project_id: str, scene_id: str, snapshot_id: str, plan_id: str
) -> dict:
    created = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/drafts/jobs",
        headers=GENERATE,
        json={
            "snapshot_id": snapshot_id,
            "plan_id": plan_id,
            "context_pack_id": STATIC_CONTEXT_PACK_ID,
        },
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "succeeded"
    draft = client.get(
        f"/projects/{project_id}/scenes/{scene_id}/drafts/{job['draft_id']}"
    )
    assert draft.status_code == 200, draft.text
    return draft.json()


def _ready_one_draft(
    client: TestClient,
) -> tuple[dict, dict, dict]:
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"], 1)
    approved = _approve(client, project["id"], scene["id"])
    snapshot = _create_snapshot(client, project["id"])
    plan = _create_plan(client, project["id"], approved["id"], snapshot["id"])
    draft = _create_draft(
        client, project["id"], approved["id"], snapshot["id"], plan["id"]
    )
    return project, approved, draft


def _summarize_scene(
    client: TestClient,
    project_id: str,
    scene_id: str,
    draft: dict,
    **overrides: object,
) -> dict:
    payload: dict = {"draft_revision_id": draft["id"]}
    payload.update(overrides)
    response = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/summaries/jobs",
        headers=GENERATE,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_healthz_and_prior_apis_still_present() -> None:
    client, _, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/version").json().get("version")
    paths = client.get("/openapi.json").json()["paths"]
    assert "/healthz" in paths
    assert "/version" in paths
    assert "/projects" in paths
    assert "/projects/{project_id}/canon-facts" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/drafts/jobs" in paths
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/extract-jobs"
        in paths
    )
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/approve" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/summaries/jobs" in paths
    assert "/projects/{project_id}/scene-summary-jobs/{job_id}" in paths
    assert "/projects/{project_id}/chapters/{chapter_id}/summaries/jobs" in paths
    assert "/projects/{project_id}/chapters/{chapter_id}/summaries" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/chapters/{chapter_id}/generate" not in paths
    assert "/projects/{project_id}/chapters/{chapter_id}/drafts" not in paths


def test_prompt_templates_have_version_and_forbid_canon() -> None:
    scene_text = load_scene_prompt_template()
    chapter_text = load_chapter_prompt_template()
    assert scene_prompt_version() == "scene_summary.v1"
    assert chapter_prompt_version() == "chapter_summary.v1"
    assert "scene_summary.v1" in scene_text
    assert "chapter_summary.v1" in chapter_text
    assert "Canon" in scene_text
    assert "Canon" in chapter_text
    assert "整章" in scene_text
    assert "整章" in chapter_text
    assert "Candidate Change" in scene_text
    scene_path = ROOT / "prompts" / "scene_summary.v1.md"
    chapter_path = ROOT / "prompts" / "chapter_summary.v1.md"
    assert scene_path.is_file()
    assert chapter_path.is_file()
    assert scene_path.read_text(encoding="utf-8") == scene_text
    assert chapter_path.read_text(encoding="utf-8") == chapter_text


def test_scene_summary_from_existing_draft_with_metadata_and_audit() -> None:
    client, sink, _ = _client()
    project, scene, draft = _ready_one_draft(client)
    job = _summarize_scene(client, project["id"], scene["id"], draft)
    assert job["state"] == "succeeded"
    assert job["kind"] == "scene"
    assert job["scene_id"] == scene["id"]
    assert job["draft_revision_id"] == draft["id"]
    assert job["source_draft_content_hash"] == draft["content_hash"]
    assert job["prompt_version"] == "scene_summary.v1"
    assert job["summary_revision"] == 1
    assert job["is_canon"] is False
    assert job["is_scene_draft"] is False
    assert job["is_candidate_change"] is False
    assert job["auto_approved"] is False
    assert job["writes_canon"] is False

    queried = client.get(f"/projects/{project['id']}/scene-summary-jobs/{job['id']}")
    assert queried.status_code == 200
    assert queried.json()["state"] == "succeeded"

    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/summaries")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    summary = items[0]
    assert summary["id"] == job["summary_id"]
    assert summary["revision"] == 1
    assert summary["status"] == "Generated"
    assert summary["body"] == FIXTURE_SCENE_SUMMARY
    assert summary["content_hash"] == content_hash(FIXTURE_SCENE_SUMMARY)
    assert summary["source_draft_revision_id"] == draft["id"]
    assert summary["source_draft_revision"] == draft["revision"]
    assert summary["source_draft_content_hash"] == draft["content_hash"]
    assert summary["prompt_version"] == "scene_summary.v1"
    assert summary["generated_at"]
    assert summary["is_canon"] is False
    assert summary["is_candidate_change"] is False
    assert summary["auto_approved"] is False

    one = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/{summary['id']}"
    )
    assert one.status_code == 200
    assert one.json()["content_hash"] == summary["content_hash"]

    kept_draft = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft['id']}"
    )
    assert kept_draft.status_code == 200
    assert kept_draft.json()["body"] == FIXTURE_PROSE
    assert kept_draft.json()["content_hash"] == draft["content_hash"]

    actions = {event.action for event in sink.events}
    assert "summary_job.create" in actions
    assert "summary_job.transition" in actions
    assert "scene_summary.create" in actions
    assert not any(event.action.startswith("canon_fact") for event in sink.events)
    assert not any("extract" in event.action for event in sink.events)
    summary_events = [
        event
        for event in sink.events
        if event.resource_type in {"summary_job", "scene_summary", "chapter_summary"}
    ]
    assert summary_events
    assert not any("approve" in event.action for event in summary_events)
    assert not any("submit" in event.action for event in summary_events)
    dumped = "".join(
        str(event.after_json) + str(event.before_json) for event in sink.events
    )
    assert FIXTURE_PROSE not in dumped
    assert FIXTURE_SCENE_SUMMARY not in dumped
    create_events = [e for e in sink.events if e.action == "scene_summary.create"]
    assert create_events
    after = create_events[0].after_json or {}
    assert after.get("content_hash") == content_hash(FIXTURE_SCENE_SUMMARY)
    assert "body" not in after


def test_rejects_missing_draft() -> None:
    client, _, _ = _client()
    project, scene, _draft = _ready_one_draft(client)
    missing = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/jobs",
        headers=GENERATE,
        json={"draft_revision_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["error"] == "scene_draft_not_found"
    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/summaries")
    assert listed.json()["items"] == []


def test_rejects_content_hash_mismatch() -> None:
    client, _, _ = _client()
    project, scene, draft = _ready_one_draft(client)
    mismatch = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/jobs",
        headers=GENERATE,
        json={
            "draft_revision_id": draft["id"],
            "content_hash": "0" * 64,
        },
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["error"] == "draft_content_hash_mismatch"


def test_chapter_rollup_from_scene_summaries() -> None:
    client, sink, _ = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    first = _create_scene(client, project["id"], chapter["id"], 1)
    second = _create_scene(
        client,
        project["id"],
        chapter["id"],
        2,
        story_time="第一日夜",
        goal="藏起残玉",
        expected_end_state="残玉被藏好",
        location="林晚家",
        generation_boundary="只写回家藏玉这一场，不写整章。",
    )
    first = _approve(client, project["id"], first["id"])
    second = _approve(client, project["id"], second["id"])
    snapshot = _create_snapshot(client, project["id"])
    plan1 = _create_plan(client, project["id"], first["id"], snapshot["id"])
    plan2 = _create_plan(client, project["id"], second["id"], snapshot["id"])
    draft1 = _create_draft(
        client, project["id"], first["id"], snapshot["id"], plan1["id"]
    )
    draft2 = _create_draft(
        client, project["id"], second["id"], snapshot["id"], plan2["id"]
    )
    job1 = _summarize_scene(client, project["id"], first["id"], draft1)
    job2 = _summarize_scene(client, project["id"], second["id"], draft2)
    created = client.post(
        f"/projects/{project['id']}/chapters/{chapter['id']}/summaries/jobs",
        headers=GENERATE,
        json={"idempotency_key": "ch-1"},
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "succeeded"
    assert job["kind"] == "chapter"
    assert job["chapter_id"] == chapter["id"]
    assert job["prompt_version"] == "chapter_summary.v1"
    assert set(job["source_scene_summary_revision_ids"]) == {
        job1["summary_id"],
        job2["summary_id"],
    }
    assert job["is_canon"] is False
    assert job["is_candidate_change"] is False
    assert job["writes_canon"] is False

    listed = client.get(f"/projects/{project['id']}/chapters/{chapter['id']}/summaries")
    assert listed.status_code == 200, listed.text
    assert listed.json()["is_chapter_prose_generate"] is False
    items = listed.json()["items"]
    assert len(items) == 1
    summary = items[0]
    assert summary["body"] == FIXTURE_CHAPTER_SUMMARY
    assert summary["content_hash"] == content_hash(FIXTURE_CHAPTER_SUMMARY)
    assert set(summary["source_scene_summary_revision_ids"]) == {
        job1["summary_id"],
        job2["summary_id"],
    }
    assert summary["prompt_version"] == "chapter_summary.v1"
    assert summary["generated_at"]
    assert summary["is_canon"] is False
    assert summary["is_scene_draft"] is False

    one = client.get(
        f"/projects/{project['id']}/chapters/{chapter['id']}/summaries/{summary['id']}"
    )
    assert one.status_code == 200
    assert one.json()["id"] == summary["id"]

    duplicate = client.post(
        f"/projects/{project['id']}/chapters/{chapter['id']}/summaries/jobs",
        headers=GENERATE,
        json={"idempotency_key": "ch-1"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == job["id"]

    retry = client.post(
        f"/projects/{project['id']}/chapters/{chapter['id']}/summaries/jobs",
        headers=GENERATE,
        json={"idempotency_key": "ch-2"},
    )
    assert retry.status_code == 201
    assert retry.json()["id"] != job["id"]
    assert retry.json()["summary_revision"] == 2
    rolled = client.get(f"/projects/{project['id']}/chapters/{chapter['id']}/summaries")
    assert [item["revision"] for item in rolled.json()["items"]] == [2, 1]
    assert rolled.json()["items"][1]["status"] == "Superseded"
    assert rolled.json()["items"][1]["id"] == summary["id"]

    assert not any(event.action.startswith("canon_fact") for event in sink.events)
    dumped = "".join(
        str(event.after_json) + str(event.before_json) for event in sink.events
    )
    assert FIXTURE_CHAPTER_SUMMARY not in dumped
    assert FIXTURE_PROSE not in dumped


def test_chapter_rejects_missing_scene_summaries() -> None:
    client, _, _ = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    first = _create_scene(client, project["id"], chapter["id"], 1)
    second = _create_scene(client, project["id"], chapter["id"], 2)
    first = _approve(client, project["id"], first["id"])
    second = _approve(client, project["id"], second["id"])
    snapshot = _create_snapshot(client, project["id"])
    plan1 = _create_plan(client, project["id"], first["id"], snapshot["id"])
    draft1 = _create_draft(
        client, project["id"], first["id"], snapshot["id"], plan1["id"]
    )
    _summarize_scene(client, project["id"], first["id"], draft1)

    created = client.post(
        f"/projects/{project['id']}/chapters/{chapter['id']}/summaries/jobs",
        headers=GENERATE,
        json={},
    )
    assert created.status_code == 409
    detail = created.json()["detail"]
    assert detail["error"] == "scene_summaries_missing"
    assert second["id"] in detail["missing_scene_ids"]
    listed = client.get(f"/projects/{project['id']}/chapters/{chapter['id']}/summaries")
    assert listed.json()["items"] == []


def test_retry_creates_new_immutable_revision() -> None:
    client, _, _ = _client()
    project, scene, draft = _ready_one_draft(client)
    first = _summarize_scene(
        client,
        project["id"],
        scene["id"],
        draft,
        idempotency_key="k-success",
    )
    first_id = first["summary_id"]
    first_hash = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/{first_id}"
    ).json()["content_hash"]

    duplicate = _summarize_scene(
        client,
        project["id"],
        scene["id"],
        draft,
        idempotency_key="k-success",
    )
    assert duplicate["id"] == first["id"]
    assert duplicate["summary_id"] == first_id

    second = _summarize_scene(
        client,
        project["id"],
        scene["id"],
        draft,
        idempotency_key="k-retry",
    )
    assert second["id"] != first["id"]
    assert second["summary_id"] != first_id
    assert second["summary_revision"] == 2

    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/summaries")
    items = listed.json()["items"]
    assert [item["revision"] for item in items] == [2, 1]
    newest, oldest = items
    assert newest["status"] == "Generated"
    assert oldest["id"] == first_id
    assert oldest["status"] == "Superseded"
    assert oldest["content_hash"] == first_hash
    assert oldest["body"] == FIXTURE_SCENE_SUMMARY
    assert newest["body"] == FIXTURE_SCENE_SUMMARY
    assert oldest["source_draft_revision_id"] == draft["id"]


def test_failure_keeps_job_and_allows_retry() -> None:
    client, sink, _ = _client(scene_task_type="scene_summary_fail")
    project, scene, draft = _ready_one_draft(client)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/jobs",
        headers=GENERATE,
        json={"draft_revision_id": draft["id"], "idempotency_key": "k-fail"},
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "failed"
    assert job["summary_id"] is None
    assert job["failure_reason"] == "provider_failed"
    assert job["evidence"] is not None
    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/summaries")
    assert listed.json()["items"] == []
    assert not any(event.action == "scene_summary.create" for event in sink.events)

    retry = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/jobs",
        headers=GENERATE,
        json={"draft_revision_id": draft["id"], "idempotency_key": "k-fail"},
    )
    assert retry.status_code == 201
    retry_job = retry.json()
    assert retry_job["id"] != job["id"]
    assert retry_job["state"] == "failed"
    kept = client.get(f"/projects/{project['id']}/scene-summary-jobs/{job['id']}")
    assert kept.status_code == 200
    assert kept.json()["state"] == "failed"


def test_cancel_is_terminal_and_does_not_delete() -> None:
    client, _, provider = _client(auto_run=False)
    project, scene, draft = _ready_one_draft(client)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/jobs",
        headers=GENERATE,
        json={"draft_revision_id": draft["id"], "idempotency_key": "k-hold"},
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "queued"
    calls_before = provider.calls

    duplicate = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/jobs",
        headers=GENERATE,
        json={"draft_revision_id": draft["id"], "idempotency_key": "k-hold"},
    )
    assert duplicate.json()["id"] == job["id"]
    assert duplicate.json()["state"] == "queued"

    blocked = client.post(
        f"/projects/{project['id']}/scene-summary-jobs/{job['id']}/cancel",
        headers=GENERATE,
        json={},
    )
    assert blocked.status_code == 403

    cancelled = client.post(
        f"/projects/{project['id']}/scene-summary-jobs/{job['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["summary_id"] is None
    assert provider.calls == calls_before

    still = client.get(f"/projects/{project['id']}/scene-summary-jobs/{job['id']}")
    assert still.status_code == 200
    assert still.json()["state"] == "cancelled"

    again = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/jobs",
        headers=GENERATE,
        json={"draft_revision_id": draft["id"], "idempotency_key": "k-hold"},
    )
    assert again.status_code == 201
    assert again.json()["id"] != job["id"]
    assert again.json()["state"] == "queued"


def test_cannot_cancel_succeeded_job() -> None:
    client, _, _ = _client()
    project, scene, draft = _ready_one_draft(client)
    job = _summarize_scene(client, project["id"], scene["id"], draft)
    denied = client.post(
        f"/projects/{project['id']}/scene-summary-jobs/{job['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"]["error"] == "job_not_cancellable"


def test_no_chapter_generate_or_new_extract_or_validate_paths() -> None:
    client, _, _ = _client()
    project, scene, draft = _ready_one_draft(client)
    blocked = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/jobs",
        headers={"X-Actor-Type": "review_agent", "X-Actor-Id": "rev-1"},
        json={"draft_revision_id": draft["id"]},
    )
    assert blocked.status_code == 403
    assert (
        client.post(f"/projects/{project['id']}/chapters/generate", json={}).status_code
        == 404
    )
    assert (
        client.post(
            f"/projects/{project['id']}/chapters/{scene['id']}/generate",
            json={},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/projects/{project['id']}/scenes/{scene['id']}/summaries/{draft['id']}/extract",
            json={},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/projects/{project['id']}/scenes/{scene['id']}/summaries/{draft['id']}/approve",
            json={},
        ).status_code
        == 404
    )


def test_summary_migration_is_incremental() -> None:
    path = ROOT / "backend" / "alembic" / "versions" / "010_create_summary_tables.py"
    text = path.read_text(encoding="utf-8")
    assert "CREATE TABLE summary_jobs" in text
    assert "CREATE TABLE scene_summaries" in text
    assert "CREATE TABLE chapter_summaries" in text
    assert "CREATE TABLE story_projects" not in text
    assert "CREATE TABLE canon_facts" not in text
    assert "CREATE TABLE scenes" not in text
    assert "CREATE TABLE scene_drafts" not in text
    assert "CREATE TABLE candidate_changes" not in text
    assert "CREATE TABLE validation_runs" not in text
    assert "down_revision" in text
    assert "009_candidate_approval" in text


def test_summary_package_has_no_vendor_http_or_chapter_generate() -> None:
    summary_dir = ROOT / "backend" / "slove_context" / "summary"
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
    for path in summary_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in text
            assert f"from {name}" not in text
        assert "chapters/generate" not in text
        assert "auto_approve" not in text or "False" in text or "forbid" in text.lower()
        assert "validation_run" not in text.lower()
