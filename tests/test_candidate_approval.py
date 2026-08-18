"""Human approve / reject / submit for Candidate Changes (node 4.2).

In-memory repositories. No live Postgres. No network. No real models.
No Validate / Validation Run (5.x). Tests seed AwaitingVerdict.

Duplicate submit rule: second submit is rejected (409) and does not
write another Canon Fact. It is not idempotent.
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
from slove_context.candidate_change.validate import validate_approval_decision
from slove_context.canon.models import FACT_ACTIVE, FACT_SUPERSEDED
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
SYSTEM = {"X-Actor-Type": "system", "X-Actor-Id": "sys-1"}
REVIEW = {"X-Actor-Type": "review_agent", "X-Actor-Id": "rev-1"}
EVIDENCE_QUOTE = "伸手拾起残玉"


def _client() -> tuple[TestClient, InMemoryAuditSink, InMemoryCanonRepository]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
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
            FakeProvider(),
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
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


def _ready_extracted(client: TestClient) -> tuple[dict, dict, dict]:
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"])
    approved = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    snapshot = client.post(
        f"/projects/{project['id']}/canon-snapshots",
        headers=HUMAN,
        json={
            "as_of_scene_seq": 1,
            "as_of_story_time": "day-01",
            "created_by": "主编",
        },
    )
    assert snapshot.status_code == 201, snapshot.text
    plan_job = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot.json()["id"]},
    )
    assert plan_job.status_code == 201, plan_job.text
    plan = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/plans/current")
    assert plan.status_code == 200, plan.text
    draft_job = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
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
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft_id}/extract-jobs",
        headers=GENERATE,
        json={},
    )
    assert extracted.status_code == 201, extracted.text
    listed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/candidate-changes"
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert items
    return project, scene, items[0]


def _seed(client: TestClient, project_id: str, candidate_id: str, status: str) -> dict:
    """Test-only: skip Validate by writing the in-memory repository.

    Not an HTTP route. Cannot seed Approved or Submitted.
    """
    if status in {CANDIDATE_APPROVED, CANDIDATE_SUBMITTED}:
        raise AssertionError(
            "Tests must not seed Approved or Submitted. "
            "Those states require human approve / submit."
        )
    if status not in SEEDABLE_STATUSES:
        raise AssertionError(f"Status {status!r} is not seedable in tests.")
    repo = client.app.state.candidate_change_repository
    item = repo.get_candidate(candidate_id)
    assert item is not None
    assert item.project_id == project_id
    item.status = status
    item.payload["status"] = status
    repo.save_candidate(item)
    fetched = client.get(f"/projects/{project_id}/candidate-changes/{candidate_id}")
    assert fetched.status_code == 200, fetched.text
    body = fetched.json()
    assert body["status"] == status
    assert body["is_canon"] is False
    assert body["writes_canon"] is False
    return body


def _awaiting(client: TestClient) -> tuple[dict, dict, dict]:
    project, scene, candidate = _ready_extracted(client)
    seeded = _seed(client, project["id"], candidate["id"], "AwaitingVerdict")
    return project, scene, seeded


def _approve_url(project_id: str, candidate_id: str) -> str:
    return f"/projects/{project_id}/candidate-changes/{candidate_id}/approve"


def _reject_url(project_id: str, candidate_id: str) -> str:
    return f"/projects/{project_id}/candidate-changes/{candidate_id}/reject"


def _submit_url(project_id: str, candidate_id: str) -> str:
    return f"/projects/{project_id}/candidate-changes/{candidate_id}/submit"


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
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/extract-jobs"
        in paths
    )
    assert "/projects/{project_id}/scenes/{scene_id}/candidate-changes" in paths
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/approve" in paths
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/reject" in paths
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/submit" in paths
    assert (
        "/projects/{project_id}/candidate-changes/{candidate_id}/seed-status"
        not in paths
    )
    assert not any("seed-status" in path for path in paths)
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/validation-runs" not in paths
    assert "/projects/{project_id}/scenes/{scene_id}/validate" not in paths
    assert "/projects/{project_id}/scenes/{scene_id}/summary" not in paths
    assert "/projects/{project_id}/chapters/{chapter_id}/summary" not in paths


def test_seed_status_is_not_registered_on_the_app() -> None:
    client, _, _ = _client()
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("seed-status" in path for path in paths)
    project, _, candidate = _ready_extracted(client)
    missing = client.post(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}/seed-status",
        headers=HUMAN,
        json={"status": "AwaitingVerdict"},
    )
    assert missing.status_code == 404
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Extracted"


def test_fixture_cannot_seed_approved_or_submitted() -> None:
    client, _, _ = _client()
    project, _, candidate = _ready_extracted(client)
    for status in (CANDIDATE_APPROVED, CANDIDATE_SUBMITTED):
        try:
            _seed(client, project["id"], candidate["id"], status)
        except AssertionError:
            continue
        raise AssertionError(f"must not seed {status}")
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Extracted"
    assert fetched.json()["is_approved"] is False


def test_approve_does_not_write_canon() -> None:
    client, sink, canon = _client()
    project, _, candidate = _awaiting(client)
    facts_before = len(canon.facts)

    response = client.post(
        _approve_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={
            "created_by": "主编",
            "reason": "与已写定规格不冲突；仍须主编另一次提交才会改 Canon。",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["writes_canon"] is False
    assert body["auto_approved"] is False
    assert body["auto_submitted"] is False
    assert body["candidate"]["status"] == "Approved"
    assert body["candidate"]["is_approved"] is True
    assert body["candidate"]["is_canon"] is False
    assert body["candidate"]["is_canon_fact"] is False
    assert body["candidate"]["writes_canon"] is False
    assert body["candidate"]["auto_approved"] is False
    decision = body["approval_decision"]
    validate_approval_decision(decision)
    assert decision["decision"] == "Approve"
    assert decision["created_by"] == "主编"
    assert decision["candidate_change_id"] == candidate["id"]
    assert decision["project_id"] == project["id"]

    facts = client.get(f"/projects/{project['id']}/canon-facts")
    assert facts.status_code == 200
    assert facts.json()["facts"] == []
    assert len(canon.facts) == facts_before == 0

    actions = {event.action for event in sink.events}
    assert "candidate_change.approve" in actions
    assert "approval_decision.create" in actions
    assert "candidate_change.submit" not in actions
    assert not any(event.action == "canon_fact.approve" for event in sink.events)
    dumped = "".join(
        str(event.after_json) + str(event.before_json) for event in sink.events
    )
    assert EVIDENCE_QUOTE not in dumped
    assert "system_prompt" not in dumped or "redacted" in dumped


def test_submit_creates_canon_fact_candidate_stays_candidate() -> None:
    client, sink, canon = _client()
    project, _, candidate = _awaiting(client)
    approved = client.post(
        _approve_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["candidate"]["status"] == "Approved"
    assert client.get(f"/projects/{project['id']}/canon-facts").json()["facts"] == []

    submitted = client.post(
        _submit_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={"entity_type": "物品"},
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["writes_canon"] is True
    assert body["auto_approved"] is False
    assert body["auto_submitted"] is False
    assert body["is_canon_fact"] is False
    assert body["candidate"]["status"] == "Submitted"
    assert body["candidate"]["is_canon"] is False
    assert body["candidate"]["is_canon_fact"] is False
    assert body["candidate"]["is_approved"] is True
    fact = body["canon_fact"]
    assert fact["status"] == FACT_ACTIVE
    assert fact["predicate"] == candidate["predicate"]
    assert fact["id"] != candidate["id"]
    assert body["candidate"]["submitted_canon_fact_id"] == fact["id"]
    assert body["superseded"] is None

    listed = client.get(f"/projects/{project['id']}/canon-facts")
    assert listed.status_code == 200
    facts = listed.json()["facts"]
    assert len(facts) == 1
    assert facts[0]["id"] == fact["id"]
    assert facts[0]["status"] == FACT_ACTIVE
    assert len(canon.facts) == 1

    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "Submitted"
    assert fetched.json()["is_canon_fact"] is False

    actions = {event.action for event in sink.events}
    assert "candidate_change.submit" in actions
    assert "canon_fact.create" in actions
    assert "canon_fact.approve" in actions
    dumped = "".join(
        str(event.after_json) + str(event.before_json) for event in sink.events
    )
    assert EVIDENCE_QUOTE not in dumped


def test_submit_supersedes_existing_active_fact() -> None:
    client, _, canon = _client()
    project, scene, candidate = _awaiting(client)
    entity = client.post(
        f"/projects/{project['id']}/entities",
        headers=HUMAN,
        json={
            "name": candidate["subject"],
            "entity_type": "物品",
            "created_by": "主编",
        },
    )
    assert entity.status_code == 201, entity.text
    evidence = client.post(
        f"/projects/{project['id']}/evidence",
        headers=HUMAN,
        json={
            "source_type": "prose",
            "quote": "旧证据占位",
            "scene_id": scene["id"],
            "created_by": "主编",
        },
    )
    assert evidence.status_code == 201, evidence.text
    created = client.post(
        f"/projects/{project['id']}/canon-facts",
        headers=HUMAN,
        json={
            "entity_id": entity.json()["id"],
            "predicate": candidate["predicate"],
            "value_json": {"text": "旧值"},
            "effective_story_time": "day-00",
            "valid_from_scene_id": scene["id"],
            "source_type": "prose",
            "evidence_id": evidence.json()["id"],
            "created_by": "主编",
        },
    )
    assert created.status_code == 201, created.text
    old = client.post(
        f"/projects/{project['id']}/canon-facts/{created.json()['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert old.status_code == 200, old.text
    old_body = dict(old.json()["value_json"])
    assert old.json()["status"] == FACT_ACTIVE

    approved = client.post(
        _approve_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200
    submitted = client.post(
        _submit_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={"entity_id": entity.json()["id"]},
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    new_fact = body["canon_fact"]
    superseded = body["superseded"]
    assert superseded is not None
    assert superseded["id"] == old.json()["id"]
    assert superseded["status"] == FACT_SUPERSEDED
    assert superseded["value_json"] == old_body
    assert new_fact["id"] != old.json()["id"]
    assert new_fact["status"] == FACT_ACTIVE
    assert new_fact["supersedes_fact_id"] == old.json()["id"]
    stored_old = canon.facts[old.json()["id"]]
    assert stored_old.status == FACT_SUPERSEDED
    assert stored_old.value_json == old_body
    listed = client.get(f"/projects/{project['id']}/canon-facts")
    assert [item["id"] for item in listed.json()["facts"]] == [new_fact["id"]]


def test_non_human_cannot_approve_or_submit() -> None:
    client, _, canon = _client()
    project, _, candidate = _awaiting(client)
    for headers in (GENERATE, SYSTEM, REVIEW):
        blocked = client.post(
            _approve_url(project["id"], candidate["id"]),
            headers=headers,
            json={},
        )
        assert blocked.status_code == 403, headers
        assert blocked.json()["detail"]["error"] == "human_editor_required"
    still = client.get(f"/projects/{project['id']}/candidate-changes/{candidate['id']}")
    assert still.json()["status"] == "AwaitingVerdict"
    assert client.get(f"/projects/{project['id']}/canon-facts").json()["facts"] == []
    assert canon.facts == {}

    approved = client.post(
        _approve_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200
    for headers in (GENERATE, SYSTEM, REVIEW):
        blocked = client.post(
            _submit_url(project["id"], candidate["id"]),
            headers=headers,
            json={"entity_type": "物品"},
        )
        assert blocked.status_code == 403, headers
    assert approved.json()["candidate"]["status"] == "Approved"
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Approved"
    assert client.get(f"/projects/{project['id']}/canon-facts").json()["facts"] == []


def test_extracted_cannot_approve_or_submit() -> None:
    client, _, canon = _client()
    project, _, candidate = _ready_extracted(client)
    assert candidate["status"] == "Extracted"
    approve = client.post(
        _approve_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={},
    )
    assert approve.status_code == 409
    assert approve.json()["detail"]["error"] == "invalid_candidate_transition"
    submit = client.post(
        _submit_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={"entity_type": "物品"},
    )
    assert submit.status_code == 409
    assert submit.json()["detail"]["error"] == "invalid_candidate_transition"
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Extracted"
    assert client.get(f"/projects/{project['id']}/canon-facts").json()["facts"] == []
    assert canon.facts == {}


def test_blocked_statuses_cannot_approve_or_submit() -> None:
    client, _, _ = _client()
    project, _, candidate = _ready_extracted(client)
    for status in (
        "Validating",
        "FailedValidation",
        "Failed",
        "Rework",
        "Cancelled",
    ):
        _seed(client, project["id"], candidate["id"], status)
        approve = client.post(
            _approve_url(project["id"], candidate["id"]),
            headers=HUMAN,
            json={},
        )
        assert approve.status_code == 409, status
        submit = client.post(
            _submit_url(project["id"], candidate["id"]),
            headers=HUMAN,
            json={"entity_type": "物品"},
        )
        assert submit.status_code == 409, status
        fetched = client.get(
            f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
        )
        assert fetched.json()["status"] == status
        assert (
            client.get(f"/projects/{project['id']}/canon-facts").json()["facts"] == []
        )


def test_reject_does_not_write_canon_and_keeps_record() -> None:
    client, sink, canon = _client()
    project, _, candidate = _awaiting(client)
    rejected = client.post(
        _reject_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={"created_by": "主编", "reason": "与已有 Canon 冲突，Canon 胜。"},
    )
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["writes_canon"] is False
    assert body["candidate"]["status"] == "Rejected"
    assert body["candidate"]["is_canon"] is False
    decision = body["approval_decision"]
    validate_approval_decision(decision)
    assert decision["decision"] == "Reject"
    assert decision["created_by"] == "主编"
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "Rejected"
    assert client.get(f"/projects/{project['id']}/canon-facts").json()["facts"] == []
    assert canon.facts == {}
    assert any(event.action == "candidate_change.reject" for event in sink.events)
    dumped = "".join(
        str(event.after_json) + str(event.before_json) for event in sink.events
    )
    assert EVIDENCE_QUOTE not in dumped


def test_reject_approved_before_submit_does_not_write_canon() -> None:
    client, _, canon = _client()
    project, _, candidate = _awaiting(client)
    approved = client.post(
        _approve_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200
    rejected = client.post(
        _reject_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["candidate"]["status"] == "Rejected"
    assert rejected.json()["writes_canon"] is False
    assert client.get(f"/projects/{project['id']}/canon-facts").json()["facts"] == []
    assert canon.facts == {}
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Rejected"


def test_duplicate_submit_is_rejected_and_does_not_double_write() -> None:
    client, _, canon = _client()
    project, _, candidate = _awaiting(client)
    client.post(_approve_url(project["id"], candidate["id"]), headers=HUMAN, json={})
    first = client.post(
        _submit_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={"entity_type": "物品"},
    )
    assert first.status_code == 200, first.text
    fact_id = first.json()["canon_fact"]["id"]
    facts_after_first = len(canon.facts)

    second = client.post(
        _submit_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={"entity_type": "物品"},
    )
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["error"] == "candidate_already_submitted"
    assert len(canon.facts) == facts_after_first == 1
    listed = client.get(f"/projects/{project['id']}/canon-facts")
    assert [item["id"] for item in listed.json()["facts"]] == [fact_id]
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Submitted"
    assert fetched.json()["submitted_canon_fact_id"] == fact_id


def test_approved_does_not_auto_submit() -> None:
    client, _, canon = _client()
    project, _, candidate = _awaiting(client)
    approved = client.post(
        _approve_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200
    fetched = client.get(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
    )
    assert fetched.json()["status"] == "Approved"
    assert fetched.json()["submitted_canon_fact_id"] is None
    assert client.get(f"/projects/{project['id']}/canon-facts").json()["facts"] == []
    assert canon.facts == {}


def test_awaiting_verdict_cannot_skip_to_submit() -> None:
    client, _, canon = _client()
    project, _, candidate = _awaiting(client)
    skipped = client.post(
        _submit_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={"entity_type": "物品"},
    )
    assert skipped.status_code == 409
    assert (
        client.get(
            f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
        ).json()["status"]
        == "AwaitingVerdict"
    )
    assert canon.facts == {}


def test_approval_decision_schema_rejects_auto_approve() -> None:
    client, _, _ = _client()
    project, _, candidate = _awaiting(client)
    response = client.post(
        _approve_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={"decision": "AutoApprove", "created_by": "主编"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "decision_mismatch"
    assert (
        client.get(
            f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
        ).json()["status"]
        == "AwaitingVerdict"
    )


def test_created_by_must_be_human_editor() -> None:
    client, _, _ = _client()
    project, _, candidate = _awaiting(client)
    response = client.post(
        _approve_url(project["id"], candidate["id"]),
        headers=HUMAN,
        json={"created_by": "审校 Agent"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "created_by_must_be_human_editor"
    assert (
        client.get(
            f"/projects/{project['id']}/candidate-changes/{candidate['id']}"
        ).json()["status"]
        == "AwaitingVerdict"
    )


def test_missing_human_actor_cannot_approve() -> None:
    client, _, _ = _client()
    project, _, candidate = _awaiting(client)
    response = client.post(
        _approve_url(project["id"], candidate["id"]),
        json={},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "human_editor_required"


def test_approval_migration_is_incremental() -> None:
    path = ROOT / "backend" / "alembic" / "versions" / "009_candidate_approval.py"
    text = path.read_text(encoding="utf-8")
    assert "ALTER TABLE candidate_changes" in text
    assert "approval_decision_json" in text
    assert "submitted_canon_fact_id" in text
    assert "CREATE TABLE story_projects" not in text
    assert "CREATE TABLE canon_facts" not in text
    assert "CREATE TABLE validation_runs" not in text
    assert "CREATE TABLE scene_summaries" not in text
    assert "down_revision" in text
    assert "008_extract" in text


def test_approval_package_has_no_vendor_http_or_validate_run() -> None:
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
