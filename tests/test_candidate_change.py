"""Candidate Change extraction jobs (node 4.1).

Fake Provider fixtures only. In-memory repositories. No live Postgres.
No network. No Validate / Validation Run. Jobs do not write Canon.
Candidates start as Extracted only and never auto-approve.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.candidate_change.prompt import load_prompt_template, prompt_version
from slove_context.candidate_change.repository import InMemoryCandidateChangeRepository
from slove_context.candidate_change.validate import validate_candidate_change
from slove_context.canon.repository import InMemoryCanonRepository
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
FIXTURE_PROSE = "FAKE_SCENE_DRAFT_PROSE：河滩风冷，林晚看见一点光，伸手拾起残玉。"
EVIDENCE_QUOTE = "伸手拾起残玉"


def _client(
    *,
    task_type: str = "extract_candidates",
    repair_task_type: str = "extract_candidates_repair",
    auto_run: bool = True,
    provider: FakeProvider | None = None,
) -> tuple[TestClient, InMemoryAuditSink, FakeProvider, InMemoryCanonRepository]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    fake = provider or FakeProvider()
    canon = InMemoryCanonRepository()
    app = create_app(
        repository=InMemoryStoryRepository(),
        canon_repository=canon,
        scene_repository=InMemorySceneRepository(),
        scene_plan_repository=InMemoryScenePlanRepository(),
        scene_draft_repository=InMemorySceneDraftRepository(),
        candidate_change_repository=InMemoryCandidateChangeRepository(),
        audit_writer=writer,
        llm_gateway=LlmGateway(
            fake,
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
        extract_task_type=task_type,
        extract_repair_task_type=repair_task_type,
        extract_auto_run=auto_run,
    )
    return TestClient(app), sink, fake, canon


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
    assert created.json()["state"] == "succeeded"
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


def _ready(client: TestClient) -> tuple[dict, dict, dict]:
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


def _extract_url(project_id: str, scene_id: str, draft_id: str) -> str:
    return f"/projects/{project_id}/scenes/{scene_id}/drafts/{draft_id}/extract-jobs"


def test_healthz_and_prior_apis_still_present() -> None:
    client, _, _, _ = _client()
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
    assert "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}" in paths
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/extract-jobs"
        in paths
    )
    assert "/projects/{project_id}/extract-jobs/{job_id}" in paths
    assert "/projects/{project_id}/extract-jobs/{job_id}/cancel" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/candidate-changes" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/validation-runs" not in paths
    assert "/projects/{project_id}/scenes/{scene_id}/validate" not in paths
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/approve" in paths
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/reject" in paths
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/submit" in paths


def test_prompt_template_has_version_requires_json_forbids_canon() -> None:
    text = load_prompt_template()
    assert prompt_version() == "extract_candidates.v1"
    assert "extract_candidates.v1" in text
    assert "JSON" in text
    assert "Evidence" in text or "evidence_quote" in text
    assert "Canon" in text
    assert "禁止" in text or "不得" in text
    assert "批准" in text
    path = ROOT / "prompts" / "extract_candidates.v1.md"
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == text


def test_success_extract_binds_evidence_and_does_not_write_canon() -> None:
    client, sink, provider, canon = _client()
    project, scene, draft = _ready(client)
    body_before = draft["body"]
    hash_before = draft["content_hash"]
    assert draft["status"] == "Generated"
    facts_before = len(canon.facts)
    evidence_before = len(canon.evidence)

    created = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers=GENERATE,
        json={"idempotency_key": "k-ok"},
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "succeeded"
    assert job["draft_id"] == draft["id"]
    assert job["scene_id"] == scene["id"]
    assert job["prompt_version"] == "extract_candidates.v1"
    assert job["extract_batch"] == 1
    assert job["candidate_ids"]
    assert job["is_canon"] is False
    assert job["is_approved"] is False
    assert job["auto_approved"] is False
    assert job["writes_canon"] is False
    assert job["repair_count"] == 0
    assert job["validation_result"]["ok"] is True
    assert job["request_refs"]
    assert job["request_refs"][0]["raw_response_reference"]
    assert [item["to"] for item in job["transitions"]] == ["running", "succeeded"]
    assert provider.calls >= 3  # plan + draft + extract

    queried = client.get(f"/projects/{project['id']}/extract-jobs/{job['id']}")
    assert queried.status_code == 200
    assert queried.json()["state"] == "succeeded"

    listed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/candidate-changes"
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["is_canon"] is False
    assert body["auto_approved"] is False
    assert body["writes_canon"] is False
    items = body["items"]
    assert len(items) == 1
    candidate = items[0]
    validate_candidate_change(
        {
            key: candidate[key]
            for key in (
                "schema_version",
                "id",
                "project_id",
                "created_at",
                "created_by",
                "subject",
                "predicate",
                "object",
                "value",
                "effective_story_time",
                "source_scene_id",
                "evidence_quote",
                "confidence",
                "status",
            )
        }
    )
    assert candidate["status"] == "Extracted"
    assert candidate["source_scene_id"] == scene["id"]
    assert candidate["evidence_quote"] == EVIDENCE_QUOTE
    assert EVIDENCE_QUOTE in FIXTURE_PROSE
    assert candidate["is_canon"] is False
    assert candidate["is_canon_fact"] is False
    assert candidate["is_approved"] is False
    assert candidate["auto_approved"] is False
    assert candidate["writes_canon"] is False
    assert candidate["extract_batch"] == 1

    refreshed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft['id']}"
    )
    assert refreshed.status_code == 200
    after = refreshed.json()
    assert after["status"] == "Extracted"
    assert after["body"] == body_before == FIXTURE_PROSE
    assert after["content_hash"] == hash_before

    facts = client.get(f"/projects/{project['id']}/canon-facts")
    assert facts.status_code == 200
    assert facts.json()["facts"] == []
    assert len(canon.facts) == facts_before == 0
    assert len(canon.evidence) == evidence_before == 0

    actions = {event.action for event in sink.events}
    assert "extract_job.create" in actions
    assert "extract_job.transition" in actions
    assert "candidate_change.create" in actions
    assert "scene_draft.extract" in actions
    assert not any(
        event.resource_type.startswith("canon_fact") for event in sink.events
    )
    assert not any(event.action.startswith("canon_fact") for event in sink.events)
    extract_actions = {
        event.action
        for event in sink.events
        if event.action.startswith(("extract_", "candidate_change"))
    }
    assert not any("approve" in action for action in extract_actions)
    assert not any("submit" in action for action in extract_actions)
    assert not any("validat" in action for action in extract_actions)
    dumped = "".join(
        str(event.after_json) + str(event.before_json) for event in sink.events
    )
    assert FIXTURE_PROSE not in dumped
    assert EVIDENCE_QUOTE not in dumped
    assert "system_prompt" not in dumped or "redacted" in dumped
    create_events = [e for e in sink.events if e.action == "candidate_change.create"]
    assert create_events
    after_audit = create_events[0].after_json or {}
    assert after_audit.get("status") == "Extracted"
    assert after_audit.get("has_evidence_quote") is True
    assert "evidence_quote" not in after_audit


def test_invalid_json_is_not_persisted_and_repairs_once() -> None:
    client, sink, provider, canon = _client(
        task_type="extract_candidates_invalid_json",
        repair_task_type="extract_candidates_invalid_json",
    )
    project, scene, draft = _ready(client)
    created = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers=GENERATE,
        json={},
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "failed"
    assert job["candidate_ids"] == []
    assert job["repair_count"] == 1
    assert job["evidence"] is not None
    assert job["evidence"]["repair_attempted"] is True
    assert job["evidence"]["validation_errors"]
    assert job["evidence"]["request_refs"]
    assert job["evidence"]["raw_response_references"]
    assert len(job["request_refs"]) == 2
    assert provider.calls >= 4  # plan + draft + 2 extract attempts
    assert "repair" in {item["to"] for item in job["transitions"]}
    listed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/candidate-changes"
    )
    assert listed.json()["items"] == []
    refreshed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft['id']}"
    )
    assert refreshed.json()["status"] == "Generated"
    assert refreshed.json()["body"] == FIXTURE_PROSE
    assert not any(event.action == "candidate_change.create" for event in sink.events)
    assert canon.facts == {}


def test_schema_fail_then_repair_fail_keeps_evidence() -> None:
    client, sink, provider, canon = _client(
        task_type="extract_candidates_invalid_schema",
        repair_task_type="extract_candidates_repair_fail",
    )
    project, scene, draft = _ready(client)
    created = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers=HUMAN,
        json={},
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "failed"
    assert job["candidate_ids"] == []
    assert job["repair_count"] == 1
    assert job["failure_reason"] == "schema_validation_failed"
    assert job["validation_result"]["ok"] is False
    evidence = job["evidence"]
    assert evidence is not None
    assert evidence["repair_attempted"] is True
    assert evidence["repair_count"] == 1
    assert evidence["validation_errors"]
    assert evidence["raw_response_references"]
    assert len(evidence["request_refs"]) == 2
    assert [item["to"] for item in job["transitions"]] == [
        "running",
        "repair",
        "failed",
    ]
    listed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/candidate-changes"
    )
    assert listed.json()["items"] == []
    queried = client.get(f"/projects/{project['id']}/extract-jobs/{job['id']}")
    assert queried.status_code == 200
    assert queried.json()["evidence"]["validation_errors"]
    assert not any(event.action == "candidate_change.create" for event in sink.events)
    assert canon.facts == {}
    assert provider.calls >= 4


def test_idempotency_and_failed_job_can_retry_as_new_job() -> None:
    client, _, _, _ = _client(
        task_type="extract_candidates_invalid_schema",
        repair_task_type="extract_candidates_repair_fail",
    )
    project, scene, draft = _ready(client)
    first = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers=GENERATE,
        json={"idempotency_key": "k-fail"},
    )
    assert first.status_code == 201, first.text
    job = first.json()
    assert job["state"] == "failed"

    duplicate_failed = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers=GENERATE,
        json={"idempotency_key": "k-fail"},
    )
    assert duplicate_failed.status_code == 201
    retry_job = duplicate_failed.json()
    assert retry_job["id"] != job["id"]
    assert retry_job["state"] == "failed"
    kept = client.get(f"/projects/{project['id']}/extract-jobs/{job['id']}")
    assert kept.status_code == 200
    assert kept.json()["state"] == "failed"
    listed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/candidate-changes"
    )
    assert listed.json()["items"] == []


def test_success_idempotency_and_append_only_retry() -> None:
    client, _, _, _ = _client()
    project, scene, draft = _ready(client)
    first = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers=GENERATE,
        json={"idempotency_key": "k-success"},
    )
    assert first.status_code == 201, first.text
    first_job = first.json()
    assert first_job["state"] == "succeeded"
    first_ids = first_job["candidate_ids"]

    duplicate = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers=GENERATE,
        json={"idempotency_key": "k-success"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == first_job["id"]
    assert duplicate.json()["candidate_ids"] == first_ids

    second = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers=GENERATE,
        json={"idempotency_key": "k-retry"},
    )
    assert second.status_code == 201, second.text
    second_job = second.json()
    assert second_job["id"] != first_job["id"]
    assert second_job["state"] == "succeeded"
    assert second_job["extract_batch"] == 2
    assert second_job["candidate_ids"] != first_ids

    listed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/candidate-changes"
    )
    items = listed.json()["items"]
    assert len(items) == 2
    assert [item["extract_batch"] for item in items] == [1, 2]
    assert {item["id"] for item in items} == set(
        first_ids + second_job["candidate_ids"]
    )
    assert all(item["status"] == "Extracted" for item in items)
    kept = client.get(f"/projects/{project['id']}/extract-jobs/{first_job['id']}")
    assert kept.json()["candidate_ids"] == first_ids


def test_cancel_is_terminal_and_does_not_delete() -> None:
    client, _, provider, _ = _client(auto_run=False)
    project, scene, draft = _ready(client)
    created = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers=GENERATE,
        json={"idempotency_key": "k-hold"},
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "queued"
    calls_before = provider.calls

    duplicate = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers=GENERATE,
        json={"idempotency_key": "k-hold"},
    )
    assert duplicate.json()["id"] == job["id"]
    assert duplicate.json()["state"] == "queued"

    blocked = client.post(
        f"/projects/{project['id']}/extract-jobs/{job['id']}/cancel",
        headers=GENERATE,
        json={},
    )
    assert blocked.status_code == 403

    cancelled = client.post(
        f"/projects/{project['id']}/extract-jobs/{job['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["candidate_ids"] == []
    assert provider.calls == calls_before

    still = client.get(f"/projects/{project['id']}/extract-jobs/{job['id']}")
    assert still.status_code == 200
    assert still.json()["state"] == "cancelled"

    again = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers=GENERATE,
        json={"idempotency_key": "k-hold"},
    )
    assert again.status_code == 201
    assert again.json()["id"] != job["id"]
    assert again.json()["state"] == "queued"


def test_rejects_missing_or_superseded_draft() -> None:
    client, _, provider, _ = _client()
    project, scene, draft = _ready(client)
    calls_before = provider.calls

    missing = client.post(
        _extract_url(
            project["id"],
            scene["id"],
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        ),
        headers=GENERATE,
        json={},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["error"] == "scene_draft_not_found"

    snapshot = _create_snapshot(client, project["id"])
    current_plan = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/current"
    ).json()["plan"]
    newer = _create_draft(
        client, project["id"], scene["id"], snapshot["id"], current_plan["id"]
    )
    old = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft['id']}"
    )
    assert old.json()["status"] == "Superseded"
    rejected = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers=GENERATE,
        json={},
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["error"] == "draft_not_extractable"
    assert newer["status"] == "Generated"
    listed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/candidate-changes"
    )
    assert listed.json()["items"] == []
    assert provider.calls == calls_before + 1  # only the extra draft job


def test_review_agent_cannot_trigger_and_no_validate_or_approve() -> None:
    client, _, _, _ = _client()
    project, scene, draft = _ready(client)
    blocked = client.post(
        _extract_url(project["id"], scene["id"], draft["id"]),
        headers={"X-Actor-Type": "review_agent", "X-Actor-Id": "rev-1"},
        json={},
    )
    assert blocked.status_code == 403
    assert (
        client.post(f"/projects/{project['id']}/chapters/generate", json={}).status_code
        == 404
    )
    assert (
        client.post(
            f"/projects/{project['id']}/scenes/{scene['id']}/validate",
            json={},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/projects/{project['id']}/validation-runs",
            json={},
        ).status_code
        == 404
    )


def test_extract_migration_is_incremental() -> None:
    path = ROOT / "backend" / "alembic" / "versions" / "008_create_extract_tables.py"
    text = path.read_text(encoding="utf-8")
    assert "CREATE TABLE extract_jobs" in text
    assert "CREATE TABLE candidate_changes" in text
    assert "Extracted" in text
    assert "CREATE TABLE story_projects" not in text
    assert "CREATE TABLE canon_facts" not in text
    assert "CREATE TABLE scenes" not in text
    assert "CREATE TABLE scene_plans" not in text
    assert "CREATE TABLE scene_drafts" not in text
    assert "CREATE TABLE validation_runs" not in text
    assert "down_revision" in text
    assert "007_scene_draft" in text


def test_extract_package_has_no_vendor_http_or_validate() -> None:
    extract_dir = ROOT / "backend" / "slove_context" / "candidate_change"
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
    for path in extract_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in text
            assert f"from {name}" not in text
        assert "validation_run" not in text
        assert "auto_approve" not in text or "False" in text
