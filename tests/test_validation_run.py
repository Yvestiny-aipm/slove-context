"""Validation Run (node 5.1).

In-memory repositories. No live Postgres. No network. No real models.
Passed is not Approval and does not write Canon. No Repair Task.
Tests seed candidate fields via the in-memory repository only.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.candidate_change.models import (
    CANDIDATE_APPROVED,
    CANDIDATE_SUBMITTED,
    SEEDABLE_STATUSES,
)
from slove_context.candidate_change.repository import InMemoryCandidateChangeRepository
from slove_context.canon.models import FACT_ACTIVE
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_draft.context_pack import STATIC_CONTEXT_PACK_ID
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.scene_plan.repository import InMemoryScenePlanRepository
from slove_context.story.repository import InMemoryStoryRepository
from slove_context.validation.repository import InMemoryValidationRepository
from slove_context.validation.validate import validate_validation_report

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


def _client(
    *, auto_run: bool = True
) -> tuple[
    TestClient,
    InMemoryAuditSink,
    InMemoryCanonRepository,
    InMemoryValidationRepository,
]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    canon = InMemoryCanonRepository()
    validation = InMemoryValidationRepository()
    app = create_app(
        repository=InMemoryStoryRepository(),
        canon_repository=canon,
        scene_repository=InMemorySceneRepository(),
        scene_plan_repository=InMemoryScenePlanRepository(),
        scene_draft_repository=InMemorySceneDraftRepository(),
        candidate_change_repository=InMemoryCandidateChangeRepository(),
        validation_repository=validation,
        audit_writer=writer,
        llm_gateway=LlmGateway(
            FakeProvider(),
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
        validation_auto_run=auto_run,
    )
    return TestClient(app), sink, canon, validation


def _create_project(client: TestClient) -> dict:
    response = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": "青石夜祠", "language": "zh-CN", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _write_spec(client: TestClient, project_id: str, *, effective: bool = True) -> dict:
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
    if not effective:
        return submitted.json()
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


def _create_scene(client: TestClient, project_id: str, chapter_id: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/scenes",
        headers=HUMAN,
        json={
            "chapter_id": chapter_id,
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
    assert response.status_code == 201, response.text
    return response.json()


def _extract(client: TestClient, project_id: str, scene_id: str) -> dict:
    approved = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    snapshot = client.post(
        f"/projects/{project_id}/canon-snapshots",
        headers=HUMAN,
        json={
            "as_of_scene_seq": 1,
            "as_of_story_time": "day-01",
            "created_by": "主编",
        },
    )
    assert snapshot.status_code == 201, snapshot.text
    plan_job = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot.json()["id"]},
    )
    assert plan_job.status_code == 201, plan_job.text
    plan = client.get(f"/projects/{project_id}/scenes/{scene_id}/plans/current")
    assert plan.status_code == 200, plan.text
    draft_job = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/drafts/jobs",
        headers=GENERATE,
        json={
            "snapshot_id": snapshot.json()["id"],
            "plan_id": plan.json()["plan"]["id"],
            "context_pack_id": STATIC_CONTEXT_PACK_ID,
        },
    )
    assert draft_job.status_code == 201, draft_job.text
    draft_id = draft_job.json()["draft_id"]
    extracted = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/drafts/{draft_id}/extract-jobs",
        headers=GENERATE,
        json={},
    )
    assert extracted.status_code == 201, extracted.text
    listed = client.get(f"/projects/{project_id}/scenes/{scene_id}/candidate-changes")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert items
    return items[0]


def _ready(client: TestClient, *, with_spec: bool = True) -> tuple[dict, dict, dict]:
    project = _create_project(client)
    if with_spec:
        _write_spec(client, project["id"])
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"])
    candidate = _extract(client, project["id"], scene["id"])
    return project, scene, candidate


def _seed(client: TestClient, project_id: str, candidate_id: str, status: str) -> dict:
    if status in {CANDIDATE_APPROVED, CANDIDATE_SUBMITTED}:
        raise AssertionError("Tests must not seed Approved or Submitted.")
    if status not in SEEDABLE_STATUSES:
        raise AssertionError(f"Status {status!r} is not seedable in tests.")
    repo = client.app.state.candidate_change_repository
    item = repo.get_candidate(candidate_id)
    assert item is not None
    item.status = status
    item.payload["status"] = status
    repo.save_candidate(item)
    fetched = client.get(f"/projects/{project_id}/candidate-changes/{candidate_id}")
    assert fetched.status_code == 200, fetched.text
    return fetched.json()


def _patch_candidate(client: TestClient, candidate_id: str, **fields: object) -> None:
    repo = client.app.state.candidate_change_repository
    item = repo.get_candidate(candidate_id)
    assert item is not None
    for key, value in fields.items():
        setattr(item, key, value)
        item.payload[key] = value
    repo.save_candidate(item)


def _canon_fact_count(canon: InMemoryCanonRepository, project_id: str) -> int:
    return len([item for item in canon.facts.values() if item.project_id == project_id])


def _run_url(project_id: str) -> str:
    return f"/projects/{project_id}/validation-runs"


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
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/extract-jobs"
        in paths
    )
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/approve" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/summaries/jobs" in paths
    assert "/projects/{project_id}/validation-runs" in paths
    assert "/projects/{project_id}/validation-runs/{run_id}" in paths
    assert "/projects/{project_id}/validation-runs/{run_id}/cancel" in paths
    assert "/projects/{project_id}/validation-runs/{run_id}/report" in paths
    assert "/projects/{project_id}/repair-tasks" not in paths
    assert (
        "/projects/{project_id}/candidate-changes/{candidate_id}/seed-status"
        not in paths
    )
    assert not any("seed-status" in path for path in paths)
    assert "/projects/{project_id}/chapters/generate" not in paths


def test_pass_moves_candidate_to_awaiting_verdict_without_canon_or_approve() -> None:
    client, sink, canon, _ = _client()
    project, scene, candidate = _ready(client)
    facts_before = _canon_fact_count(canon, project["id"])
    response = client.post(
        _run_url(project["id"]),
        headers=REVIEW,
        json={"scene_id": scene["id"], "candidate_ids": [candidate["id"]]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "Passed"
    assert body["outcome"] == "Passed"
    assert body["writes_canon"] is False
    assert body["auto_approved"] is False
    assert body["is_approval"] is False
    report = client.get(
        f"/projects/{project['id']}/validation-runs/{body['id']}/report"
    )
    assert report.status_code == 200, report.text
    payload = report.json()
    validate_validation_report(payload)
    assert payload["outcome"] == "Passed"
    assert payload["violations"] == []
    assert payload["candidate_change_ids"] == [candidate["id"]]
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "AwaitingVerdict"
    assert fetched.json()["is_approved"] is False
    assert fetched.json()["writes_canon"] is False
    listed = client.get(f"/projects/{project['id']}/canon-facts")
    assert listed.status_code == 200
    assert _canon_fact_count(canon, project["id"]) == facts_before
    assert listed.json()["facts"] == []
    actions = [event.action for event in sink.events]
    assert "validation_run.create" in actions
    assert "validation_run.transition" in actions
    assert "validation_report.create" in actions
    assert "candidate_change.awaiting_verdict" in actions
    assert "canon_fact.create" not in actions
    assert "canon_fact.approve" not in actions
    assert "candidate_change.approve" not in actions
    assert "candidate_change.submit" not in actions
    for event in sink.events:
        blob = f"{event.before_json} {event.after_json}"
        assert "伸手拾起残玉" not in blob
        assert "evidence_quote" not in blob or "redacted" in blob.lower()


def test_canon_conflict_is_rule_failed_and_blocks_approval() -> None:
    client, sink, canon, _ = _client()
    project, scene, candidate = _ready(client)
    entity = client.post(
        f"/projects/{project['id']}/entities",
        headers=HUMAN,
        json={"name": "残玉", "entity_type": "物品", "created_by": "主编"},
    )
    assert entity.status_code == 201, entity.text
    evidence = client.post(
        f"/projects/{project['id']}/evidence",
        headers=HUMAN,
        json={
            "source_type": "editor",
            "quote": "残玉只能由林晚触活",
            "created_by": "主编",
        },
    )
    assert evidence.status_code == 201, evidence.text
    fact = client.post(
        f"/projects/{project['id']}/canon-facts",
        headers=HUMAN,
        json={
            "entity_id": entity.json()["id"],
            "predicate": "被拾起",
            "value_json": {"object": "林晚", "value": "林晚持有残玉"},
            "effective_story_time": "第一日黄昏",
            "valid_from_scene_id": scene["id"],
            "source_type": "editor",
            "evidence_id": evidence.json()["id"],
            "created_by": "主编",
        },
    )
    assert fact.status_code == 201, fact.text
    approved = client.post(
        f"/projects/{project['id']}/canon-facts/{fact.json()['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == FACT_ACTIVE
    facts_before = _canon_fact_count(canon, project["id"])
    _patch_candidate(
        client,
        candidate["id"],
        object="路人",
        value="路人持有残玉",
        evidence_quote="残玉在路人手中也亮了",
    )
    response = client.post(
        _run_url(project["id"]),
        headers=HUMAN,
        json={"candidate_ids": [candidate["id"]]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["state"] == "RuleFailed"
    assert response.json()["outcome"] == "RuleFailed"
    report = client.get(
        f"/projects/{project['id']}/validation-runs/{response.json()['id']}/report"
    )
    payload = report.json()
    validate_validation_report(payload)
    assert payload["outcome"] == "RuleFailed"
    assert payload["violations"]
    violation = payload["violations"][0]
    for key in (
        "rule_id",
        "severity",
        "entity_ids",
        "source_evidence",
        "canon_evidence",
        "recommended_action",
    ):
        assert violation[key]
    assert violation["severity"] == "Blocking"
    assert violation["rule_id"] == "canon-active-conflict"
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "FailedValidation"
    blocked = client.post(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}/approve",
        headers=HUMAN,
        json={"created_by": "主编", "decision": "Approve"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error"] == "invalid_candidate_transition"
    assert _canon_fact_count(canon, project["id"]) == facts_before
    assert "candidate_change.approve" not in [event.action for event in sink.events]


def test_spec_forbid_list_is_rule_failed() -> None:
    client, _, _, _ = _client()
    project, scene, candidate = _ready(client)
    _patch_candidate(
        client,
        candidate["id"],
        value="第二主角视角旁观捡玉",
        evidence_quote="旁白改用第二主角视角",
    )
    response = client.post(
        _run_url(project["id"]),
        headers=REVIEW,
        json={"scene_id": scene["id"]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["state"] == "RuleFailed"
    payload = client.get(
        f"/projects/{project['id']}/validation-runs/{response.json()['id']}/report"
    ).json()
    validate_validation_report(payload)
    assert payload["violations"][0]["rule_id"] == "spec-must-not-write"
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "FailedValidation"


def test_exec_fail_keeps_records_and_cannot_enter_approval() -> None:
    client, sink, canon, validation = _client()
    project, scene, candidate = _ready(client)
    facts_before = _canon_fact_count(canon, project["id"])
    validation.force_exec_fail = True
    response = client.post(
        _run_url(project["id"]),
        headers=SYSTEM,
        json={"scene_id": scene["id"], "candidate_ids": [candidate["id"]]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "ExecFailed"
    assert body["outcome"] == "ExecFailed"
    assert validation.get_run(body["id"]) is not None
    payload = client.get(
        f"/projects/{project['id']}/validation-runs/{body['id']}/report"
    ).json()
    validate_validation_report(payload)
    assert payload["outcome"] == "ExecFailed"
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Failed"
    blocked = client.post(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}/approve",
        headers=HUMAN,
        json={"created_by": "主编"},
    )
    assert blocked.status_code == 409
    assert _canon_fact_count(canon, project["id"]) == facts_before
    assert any(event.action == "validation_run.transition" for event in sink.events)


def test_non_extracted_candidate_cannot_start_a_run() -> None:
    client, _, canon, validation = _client()
    project, _scene, candidate = _ready(client)
    facts_before = _canon_fact_count(canon, project["id"])
    for status in ("AwaitingVerdict", "Validating", "FailedValidation", "Failed"):
        _seed(client, project["id"], candidate["id"], status)
        response = client.post(
            _run_url(project["id"]),
            headers=REVIEW,
            json={"candidate_ids": [candidate["id"]]},
        )
        assert response.status_code == 409, status
        assert response.json()["detail"]["error"] == "candidate_not_extracted"
        fetched = client.get(
            f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
        )
        assert fetched.json()["status"] == status
    assert validation.runs == {}
    assert _canon_fact_count(canon, project["id"]) == facts_before


def test_missing_evidence_cannot_start_a_run() -> None:
    client, _, _, validation = _client()
    project, _, candidate = _ready(client)
    _patch_candidate(client, candidate["id"], evidence_quote="")
    response = client.post(
        _run_url(project["id"]),
        headers=REVIEW,
        json={"candidate_ids": [candidate["id"]]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "candidate_missing_evidence"
    assert validation.runs == {}
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Extracted"


def test_missing_or_draft_spec_cannot_start_a_run() -> None:
    client, _, _, _ = _client()
    project, scene, candidate = _ready(client, with_spec=False)
    missing = client.post(
        _run_url(project["id"]),
        headers=REVIEW,
        json={"scene_id": scene["id"], "candidate_ids": [candidate["id"]]},
    )
    assert missing.status_code == 409
    assert missing.json()["detail"]["error"] == "story_spec_required"
    draft = client.post(
        f"/projects/{project['id']}/specs",
        headers=HUMAN,
        json=SPEC,
    )
    assert draft.status_code == 201, draft.text
    still_draft = client.post(
        _run_url(project["id"]),
        headers=REVIEW,
        json={"candidate_ids": [candidate["id"]]},
    )
    assert still_draft.status_code == 409
    assert still_draft.json()["detail"]["error"] == "story_spec_not_written"
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Extracted"


def test_missing_snapshot_is_rejected() -> None:
    client, _, _, _ = _client()
    project, _, candidate = _ready(client)
    response = client.post(
        _run_url(project["id"]),
        headers=REVIEW,
        json={
            "candidate_ids": [candidate["id"]],
            "snapshot_id": "99999999-9999-4999-8999-999999999999",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "snapshot_required"


def test_cancel_keeps_run_and_returns_candidates_to_extracted() -> None:
    client, sink, _, validation = _client(auto_run=False)
    project, scene, candidate = _ready(client)
    created = client.post(
        _run_url(project["id"]),
        headers=REVIEW,
        json={"scene_id": scene["id"], "candidate_ids": [candidate["id"]]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["state"] == "Queued"
    mid = client.get(f"/projects/{project['id']}/candidate-changes/{candidate['id']}")
    assert mid.json()["status"] == "Validating"
    cancelled = client.post(
        f"/projects/{project['id']}/validation-runs/{created.json()['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "Cancelled"
    assert validation.get_run(created.json()["id"]) is not None
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Extracted"
    again = client.post(
        f"/projects/{project['id']}/validation-runs/{created.json()['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert again.status_code == 409
    assert again.json()["detail"]["error"] == "run_not_cancellable"
    assert any(event.action == "validation_run.transition" for event in sink.events)


def test_generation_agent_cannot_trigger_validate() -> None:
    client, _, _, _ = _client()
    project, scene, candidate = _ready(client)
    response = client.post(
        _run_url(project["id"]),
        headers=GENERATE,
        json={"scene_id": scene["id"], "candidate_ids": [candidate["id"]]},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "actor_not_allowed"
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Extracted"


def test_non_human_cannot_cancel() -> None:
    client, _, _, _ = _client(auto_run=False)
    project, _, candidate = _ready(client)
    created = client.post(
        _run_url(project["id"]),
        headers=REVIEW,
        json={"candidate_ids": [candidate["id"]]},
    )
    assert created.status_code == 201, created.text
    blocked = client.post(
        f"/projects/{project['id']}/validation-runs/{created.json()['id']}/cancel",
        headers=REVIEW,
        json={},
    )
    assert blocked.status_code == 403


def test_no_repair_task_or_auto_approve_routes() -> None:
    client, _, _, _ = _client()
    project, scene, _ = _ready(client)
    assert (
        client.post(
            f"/projects/{project['id']}/repair-tasks",
            json={},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/projects/{project['id']}/scenes/{scene['id']}/repair",
            json={},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/projects/{project['id']}/candidate-changes/auto-approve",
            json={},
        ).status_code
        == 404
    )
    assert (
        client.post(f"/projects/{project['id']}/chapters/generate", json={}).status_code
        == 404
    )


def test_validation_migration_is_incremental() -> None:
    path = ROOT / "backend" / "alembic" / "versions" / "011_create_validation_tables.py"
    text = path.read_text(encoding="utf-8")
    assert "CREATE TABLE validation_runs" in text
    assert "CREATE TABLE validation_reports" in text
    assert "Queued" in text
    assert "RuleFailed" in text
    assert "CREATE TABLE story_projects" not in text
    assert "CREATE TABLE canon_facts" not in text
    assert "CREATE TABLE scenes" not in text
    assert "CREATE TABLE candidate_changes" not in text
    assert "CREATE TABLE summary_jobs" not in text
    assert "CREATE TABLE repair_tasks" not in text
    assert "down_revision" in text
    assert "010_summaries" in text


def test_validation_package_has_no_vendor_http_or_repair_task() -> None:
    package = ROOT / "backend" / "slove_context" / "validation"
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
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in text
            assert f"from {name}" not in text
        assert "auto_approve" not in text or "False" in text
        assert "repair_task" not in text.lower() or "no repair" in text.lower()
