"""Repair Task (node 5.2).

In-memory repositories. No live Postgres. No network. No real models.
Opened only from RuleFailed / Violation. Completed must re-run
Validation. RecheckPassed is not approve and does not write Canon.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.candidate_change.repository import InMemoryCandidateChangeRepository
from slove_context.canon.models import FACT_ACTIVE
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.repair.repository import InMemoryRepairRepository
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_draft.context_pack import STATIC_CONTEXT_PACK_ID
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.scene_plan.repository import InMemoryScenePlanRepository
from slove_context.story.repository import InMemoryStoryRepository
from slove_context.validation.repository import InMemoryValidationRepository

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
    InMemoryRepairRepository,
    InMemoryValidationRepository,
]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    canon = InMemoryCanonRepository()
    repair = InMemoryRepairRepository()
    validation = InMemoryValidationRepository()
    app = create_app(
        repository=InMemoryStoryRepository(),
        canon_repository=canon,
        scene_repository=InMemorySceneRepository(),
        scene_plan_repository=InMemoryScenePlanRepository(),
        scene_draft_repository=InMemorySceneDraftRepository(),
        candidate_change_repository=InMemoryCandidateChangeRepository(),
        validation_repository=validation,
        repair_repository=repair,
        audit_writer=writer,
        llm_gateway=LlmGateway(
            FakeProvider(),
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
    )
    return TestClient(app), sink, canon, repair, validation


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


def _ready(client: TestClient) -> tuple[dict, dict, dict]:
    project = _create_project(client)
    _write_spec(client, project["id"])
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"])
    candidate = _extract(client, project["id"], scene["id"])
    return project, scene, candidate


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


def _add_conflicting_canon(client: TestClient, project_id: str, scene_id: str) -> None:
    entity = client.post(
        f"/projects/{project_id}/entities",
        headers=HUMAN,
        json={"name": "残玉", "entity_type": "物品", "created_by": "主编"},
    )
    assert entity.status_code == 201, entity.text
    evidence = client.post(
        f"/projects/{project_id}/evidence",
        headers=HUMAN,
        json={
            "source_type": "editor",
            "quote": "残玉只能由林晚触活",
            "created_by": "主编",
        },
    )
    assert evidence.status_code == 201, evidence.text
    fact = client.post(
        f"/projects/{project_id}/canon-facts",
        headers=HUMAN,
        json={
            "entity_id": entity.json()["id"],
            "predicate": "被拾起",
            "value_json": {"object": "林晚", "value": "林晚持有残玉"},
            "effective_story_time": "第一日黄昏",
            "valid_from_scene_id": scene_id,
            "source_type": "editor",
            "evidence_id": evidence.json()["id"],
            "created_by": "主编",
        },
    )
    assert fact.status_code == 201, fact.text
    approved = client.post(
        f"/projects/{project_id}/canon-facts/{fact.json()['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == FACT_ACTIVE


def _rule_failed_run(
    client: TestClient, project_id: str, scene_id: str, candidate_id: str
) -> dict:
    _add_conflicting_canon(client, project_id, scene_id)
    _patch_candidate(
        client,
        candidate_id,
        object="路人",
        value="路人持有残玉",
        evidence_quote="残玉在路人手中也亮了",
    )
    response = client.post(
        f"/projects/{project_id}/validation-runs",
        headers=HUMAN,
        json={"candidate_ids": [candidate_id]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["state"] == "RuleFailed"
    return response.json()


def _open(
    client: TestClient,
    project_id: str,
    run_id: str,
    *,
    action: str = "Reextract",
    violation_id: str | None = None,
) -> dict:
    payload: dict[str, object] = {
        "validation_run_id": run_id,
        "action": action,
    }
    if violation_id is not None:
        payload["violation_id"] = violation_id
    response = client.post(
        f"/projects/{project_id}/repair-tasks",
        headers=HUMAN,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_healthz_and_prior_apis_still_present() -> None:
    client, _, _, _, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/version").json().get("version")
    paths = client.get("/openapi.json").json()["paths"]
    assert "/healthz" in paths
    assert "/version" in paths
    assert "/projects/{project_id}/validation-runs" in paths
    assert "/projects/{project_id}/repair-tasks" in paths
    assert "/projects/{project_id}/repair-tasks/{task_id}" in paths
    assert "/projects/{project_id}/repair-tasks/{task_id}/start" in paths
    assert "/projects/{project_id}/repair-tasks/{task_id}/complete" in paths
    assert "/projects/{project_id}/repair-tasks/{task_id}/cancel" in paths
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/approve" in paths
    assert (
        "/projects/{project_id}/candidate-changes/{candidate_id}/seed-status"
        not in paths
    )
    assert not any("seed-status" in path for path in paths)
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/auto-approve" not in paths
    assert "/projects/{project_id}/context-packs/assemble" not in paths


def test_open_task_from_rule_failed_only() -> None:
    passed_client, _, _, passed_repair, _ = _client()
    project, scene, candidate = _ready(passed_client)
    passed = passed_client.post(
        f"/projects/{project['id']}/validation-runs",
        headers=REVIEW,
        json={"scene_id": scene["id"], "candidate_ids": [candidate["id"]]},
    )
    assert passed.status_code == 201, passed.text
    assert passed.json()["state"] == "Passed"
    blocked_passed = passed_client.post(
        f"/projects/{project['id']}/repair-tasks",
        headers=HUMAN,
        json={
            "validation_run_id": passed.json()["id"],
            "action": "Reextract",
        },
    )
    assert blocked_passed.status_code == 409
    assert blocked_passed.json()["detail"]["error"] == "repair_requires_rule_failed"
    assert passed_repair.tasks == {}

    exec_client, _, _, exec_repair, validation = _client()
    project_e, scene_e, candidate_e = _ready(exec_client)
    validation.force_exec_fail = True
    exec_failed = exec_client.post(
        f"/projects/{project_e['id']}/validation-runs",
        headers=SYSTEM,
        json={"scene_id": scene_e["id"], "candidate_ids": [candidate_e["id"]]},
    )
    assert exec_failed.json()["state"] == "ExecFailed"
    blocked_exec = exec_client.post(
        f"/projects/{project_e['id']}/repair-tasks",
        headers=HUMAN,
        json={
            "validation_run_id": exec_failed.json()["id"],
            "action": "Reextract",
        },
    )
    assert blocked_exec.status_code == 409
    assert blocked_exec.json()["detail"]["error"] == "repair_requires_rule_failed"
    assert exec_repair.tasks == {}

    client, sink, canon, repair, _ = _client()
    project_r, scene_r, candidate_r = _ready(client)
    facts_before = _canon_fact_count(canon, project_r["id"])
    run = _rule_failed_run(client, project_r["id"], scene_r["id"], candidate_r["id"])
    opened = _open(client, project_r["id"], run["id"])
    assert opened["state"] == "Opened"
    assert opened["action"] == "Reextract"
    assert opened["recommended_action"] in {
        "ReviseScenePlan",
        "Regenerate",
        "Reextract",
        "HumanReject",
    }
    assert opened["writes_canon"] is False
    assert opened["auto_approved"] is False
    assert opened["is_approval"] is False
    assert repair.get_task(opened["id"]) is not None
    assert _canon_fact_count(canon, project_r["id"]) == facts_before + 1
    assert "repair_task.create" in [event.action for event in sink.events]


def test_complete_must_start_validation_recheck() -> None:
    client, sink, canon, repair, validation = _client()
    project, scene, candidate = _ready(client)
    facts_before = _canon_fact_count(canon, project["id"])
    run = _rule_failed_run(client, project["id"], scene["id"], candidate["id"])
    opened = _open(client, project["id"], run["id"], action="Reextract")
    started = client.post(
        f"/projects/{project['id']}/repair-tasks/{opened['id']}/start",
        headers=GENERATE,
        json={},
    )
    assert started.status_code == 200, started.text
    assert started.json()["state"] == "InProgress"
    assert started.json()["produced_candidate_ids"]
    runs_before = set(validation.runs)
    completed = client.post(
        f"/projects/{project['id']}/repair-tasks/{opened['id']}/complete",
        headers=GENERATE,
        json={},
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert "Rechecking" in [item["to"] for item in body["transitions"]]
    assert body["recheck_run_id"]
    assert body["recheck_run_id"] not in runs_before
    assert body["recheck_run_id"] in validation.runs
    assert body["recheck_skipped_reason"] is None
    recheck = client.get(
        f"/projects/{project['id']}/validation-runs/{body['recheck_run_id']}"
    )
    assert recheck.status_code == 200, recheck.text
    assert recheck.json()["id"] == body["recheck_run_id"]
    assert repair.get_task(opened["id"]) is not None
    assert _canon_fact_count(canon, project["id"]) == facts_before + 1
    assert "repair_task.transition" in [event.action for event in sink.events]


def test_recheck_passed_is_not_approve_and_does_not_write_canon() -> None:
    client, sink, canon, _, _ = _client()
    project, scene, candidate = _ready(client)
    facts_before = _canon_fact_count(canon, project["id"])
    run = _rule_failed_run(client, project["id"], scene["id"], candidate["id"])
    opened = _open(client, project["id"], run["id"], action="Reextract")
    started = client.post(
        f"/projects/{project['id']}/repair-tasks/{opened['id']}/start",
        headers=GENERATE,
        json={},
    )
    assert started.status_code == 200, started.text
    completed = client.post(
        f"/projects/{project['id']}/repair-tasks/{opened['id']}/complete",
        headers=GENERATE,
        json={},
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["state"] == "RecheckPassed"
    assert body["recheck_status"] == "Passed"
    assert body["is_approved"] is False
    assert body["writes_canon"] is False
    assert body["auto_approved"] is False
    assert body["is_approval"] is False
    produced = body["produced_candidate_ids"]
    assert produced
    fetched = client.get(f"/projects/{project['id']}/candidate-changes/{produced[0]}")
    assert fetched.json()["status"] == "AwaitingVerdict"
    assert fetched.json()["is_approved"] is False
    assert fetched.json()["writes_canon"] is False
    original = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert original.json()["status"] == "FailedValidation"
    blocked = client.post(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}/approve",
        headers=HUMAN,
        json={"created_by": "主编", "decision": "Approve"},
    )
    assert blocked.status_code == 409
    listed = client.get(f"/projects/{project['id']}/canon-facts")
    assert listed.status_code == 200
    assert _canon_fact_count(canon, project["id"]) == facts_before + 1
    actions = [event.action for event in sink.events]
    assert "candidate_change.approve" not in actions
    assert "candidate_change.submit" not in actions
    assert "canon_fact.create" not in actions
    for event in sink.events:
        blob = f"{event.before_json} {event.after_json}"
        assert "伸手拾起残玉" not in blob
        assert "残玉在路人手中也亮了" not in blob
        assert "'evidence_quote'" not in blob
        assert '"evidence_quote"' not in blob


def test_recheck_failure_blocks_approval() -> None:
    client, sink, canon, repair, _ = _client()
    project, scene, candidate = _ready(client)
    facts_before = _canon_fact_count(canon, project["id"])
    run = _rule_failed_run(client, project["id"], scene["id"], candidate["id"])
    opened = _open(client, project["id"], run["id"], action="Reextract")
    started = client.post(
        f"/projects/{project['id']}/repair-tasks/{opened['id']}/start",
        headers=GENERATE,
        json={},
    )
    assert started.status_code == 200, started.text
    new_id = started.json()["produced_candidate_ids"][0]
    _patch_candidate(
        client,
        new_id,
        object="路人",
        value="路人持有残玉",
        evidence_quote="残玉在路人手中也亮了",
    )
    completed = client.post(
        f"/projects/{project['id']}/repair-tasks/{opened['id']}/complete",
        headers=GENERATE,
        json={},
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["state"] == "Failed"
    assert body["recheck_status"] == "RuleFailed"
    assert repair.get_task(opened["id"]) is not None
    fetched = client.get(f"/projects/{project['id']}/candidate-changes/{new_id}")
    assert fetched.json()["status"] == "FailedValidation"
    blocked = client.post(
        f"/projects/{project['id']}/candidate-changes/{new_id}/approve",
        headers=HUMAN,
        json={"created_by": "主编", "decision": "Approve"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error"] == "invalid_candidate_transition"
    assert _canon_fact_count(canon, project["id"]) == facts_before + 1
    assert "candidate_change.approve" not in [event.action for event in sink.events]


def test_cancel_does_not_delete() -> None:
    client, sink, _, repair, _ = _client()
    project, scene, candidate = _ready(client)
    run = _rule_failed_run(client, project["id"], scene["id"], candidate["id"])
    opened = _open(client, project["id"], run["id"])
    cancelled = client.post(
        f"/projects/{project['id']}/repair-tasks/{opened['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "Cancelled"
    assert repair.get_task(opened["id"]) is not None
    fetched = client.get(f"/projects/{project['id']}/repair-tasks/{opened['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["state"] == "Cancelled"
    listed = client.get(f"/projects/{project['id']}/repair-tasks")
    assert listed.status_code == 200
    assert any(item["id"] == opened["id"] for item in listed.json()["items"])
    by_run = client.get(
        f"/projects/{project['id']}/validation-runs/{run['id']}/repair-tasks"
    )
    assert by_run.status_code == 200
    assert any(item["id"] == opened["id"] for item in by_run.json()["items"])
    again = client.post(
        f"/projects/{project['id']}/repair-tasks/{opened['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert again.status_code == 409
    assert any(event.action == "repair_task.transition" for event in sink.events)


def test_human_reject_rejects_without_canon_and_skips_recheck() -> None:
    client, sink, canon, _, _ = _client()
    project, scene, candidate = _ready(client)
    facts_before = _canon_fact_count(canon, project["id"])
    run = _rule_failed_run(client, project["id"], scene["id"], candidate["id"])
    opened = _open(client, project["id"], run["id"], action="HumanReject")
    started = client.post(
        f"/projects/{project['id']}/repair-tasks/{opened['id']}/start",
        headers=HUMAN,
        json={},
    )
    assert started.status_code == 200, started.text
    completed = client.post(
        f"/projects/{project['id']}/repair-tasks/{opened['id']}/complete",
        headers=HUMAN,
        json={},
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["state"] == "Completed"
    assert body["recheck_status"] == "not_applicable"
    assert body["recheck_skipped_reason"] == "human_reject_no_new_candidates"
    assert body["recheck_run_id"] is None
    assert body["is_approved"] is False
    assert body["writes_canon"] is False
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Rejected"
    assert fetched.json()["approval_decision"]["decision"] == "Reject"
    submit = client.post(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}/submit",
        headers=HUMAN,
        json={"created_by": "主编", "entity_type": "物品"},
    )
    assert submit.status_code == 409
    assert _canon_fact_count(canon, project["id"]) == facts_before + 1
    actions = [event.action for event in sink.events]
    assert "candidate_change.reject" in actions
    assert "candidate_change.approve" not in actions
    assert "candidate_change.submit" not in actions
    assert "canon_fact.create" not in actions


def test_invalid_action_and_non_human_open_are_rejected() -> None:
    client, _, _, _, _ = _client()
    project, scene, candidate = _ready(client)
    run = _rule_failed_run(client, project["id"], scene["id"], candidate["id"])
    invalid = client.post(
        f"/projects/{project['id']}/repair-tasks",
        headers=HUMAN,
        json={"validation_run_id": run["id"], "action": "AutoApprove"},
    )
    assert invalid.status_code == 422
    blocked = client.post(
        f"/projects/{project['id']}/repair-tasks",
        headers=GENERATE,
        json={"validation_run_id": run["id"], "action": "Reextract"},
    )
    assert blocked.status_code == 403
    assert (
        client.post(
            f"/projects/{project['id']}/auto-approve",
            json={},
        ).status_code
        == 404
    )
    assert (
        client.post(f"/projects/{project['id']}/chapters/generate", json={}).status_code
        == 404
    )


def test_repair_migration_is_incremental() -> None:
    path = ROOT / "backend" / "alembic" / "versions" / "012_create_repair_tasks.py"
    text = path.read_text(encoding="utf-8")
    assert "CREATE TABLE repair_tasks" in text
    assert "Opened" in text
    assert "RecheckPassed" in text
    assert "ReviseScenePlan" in text
    assert "HumanReject" in text
    assert "CREATE TABLE story_projects" not in text
    assert "CREATE TABLE canon_facts" not in text
    assert "CREATE TABLE scenes" not in text
    assert "CREATE TABLE candidate_changes" not in text
    assert "CREATE TABLE validation_runs" not in text
    assert "down_revision" in text
    assert "011_validation" in text


def test_repair_package_has_no_vendor_http_or_auto_approve() -> None:
    package = ROOT / "backend" / "slove_context" / "repair"
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
        assert "chapters/generate" not in text
        assert "context pack assembler" not in text.lower()
