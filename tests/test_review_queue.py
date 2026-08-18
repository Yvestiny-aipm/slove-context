"""Human review-queue API (node 7.3).

In-memory repositories. No live Postgres. No network. No real models.
Six subject types can enqueue. Only a human 主编 may approve / reject /
request_revision / escalate, each with a reason_code. Queue approve on
a Candidate Change reuses 4.2 approve and does not submit Canon.
Style-report approve is not Canon approval. 2.1–7.2 APIs remain.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.candidate_change.models import (
    CANDIDATE_APPROVED,
    CANDIDATE_AWAITING_VERDICT,
    CANDIDATE_SUBMITTED,
    SEEDABLE_STATUSES,
)
from slove_context.candidate_change.repository import InMemoryCandidateChangeRepository
from slove_context.canon.models import FACT_ACTIVE
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.repair.repository import InMemoryRepairRepository
from slove_context.review_queue.repository import InMemoryReviewQueueRepository
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_draft.context_pack import STATIC_CONTEXT_PACK_ID
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.scene_plan.repository import InMemoryScenePlanRepository
from slove_context.story.repository import InMemoryStoryRepository
from slove_context.style.repository import InMemoryStyleRepository
from slove_context.style_validation.repository import InMemoryStyleValidationRepository
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
POSITIVE_EXAMPLE = "她把残玉握进掌心，河风贴着腕骨过去。"
NEGATIVE_EXAMPLE = "哇塞这玉也太酷了吧路人也能触活！"


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
        validation_repository=InMemoryValidationRepository(),
        repair_repository=InMemoryRepairRepository(),
        style_repository=InMemoryStyleRepository(),
        style_validation_repository=InMemoryStyleValidationRepository(),
        review_queue_repository=InMemoryReviewQueueRepository(),
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


def _create_chapter(
    client: TestClient,
    project_id: str,
    *,
    title: str = "得玉",
    sort_order: int = 1,
    arc_id: str | None = None,
) -> dict:
    if arc_id is None:
        arc = client.post(
            f"/projects/{project_id}/arcs",
            headers=HUMAN,
            json={"title": "七日寻祠", "sort_order": 1, "created_by": "主编"},
        )
        assert arc.status_code == 201, arc.text
        arc_id = arc.json()["id"]
    chapter = client.post(
        f"/projects/{project_id}/chapters",
        headers=HUMAN,
        json={
            "arc_id": arc_id,
            "title": title,
            "sort_order": sort_order,
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
    story_order: int = 1,
) -> dict:
    response = client.post(
        f"/projects/{project_id}/scenes",
        headers=HUMAN,
        json={
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
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _pipeline(client: TestClient) -> dict[str, dict]:
    project = _create_project(client)
    _write_spec(client, project["id"])
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
    return {
        "project": project,
        "chapter": chapter,
        "scene": scene,
        "snapshot": snapshot.json(),
        "plan": plan.json()["plan"],
        "draft": {"id": draft_id},
        "candidate": listed.json()["items"][0],
    }


def _enqueue(
    client: TestClient,
    project_id: str,
    subject_type: str,
    subject_id: str,
    **extra: object,
) -> dict:
    payload: dict[str, object] = {
        "subject_type": subject_type,
        "subject_id": subject_id,
    }
    payload.update(extra)
    response = client.post(
        f"/projects/{project_id}/review-queue/items",
        headers=HUMAN,
        json=payload,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["subject_type"] == subject_type
    assert body["subject_id"] == subject_id
    assert body["writes_canon"] is False
    assert "input_versions" in body
    assert "context_pack_id" in body
    assert "evidence_refs" in body
    assert "diff" in body
    assert "decision_history" in body
    return body


def _seed_awaiting(client: TestClient, project_id: str, candidate_id: str) -> dict:
    if CANDIDATE_AWAITING_VERDICT not in SEEDABLE_STATUSES:
        raise AssertionError("AwaitingVerdict must stay seedable for tests.")
    repo = client.app.state.candidate_change_repository
    item = repo.get_candidate(candidate_id)
    assert item is not None
    item.status = CANDIDATE_AWAITING_VERDICT
    item.payload["status"] = CANDIDATE_AWAITING_VERDICT
    repo.save_candidate(item)
    fetched = client.get(f"/projects/{project_id}/candidate-changes/{candidate_id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["status"] == CANDIDATE_AWAITING_VERDICT
    return fetched.json()


def _style_report(
    client: TestClient, project_id: str, scene_id: str, draft_id: str
) -> dict:
    guide = client.post(
        f"/projects/{project_id}/style-guides",
        headers=HUMAN,
        json={
            "pov": "林晚",
            "人称": "第三人称限制",
            "时态": "过去进行",
            "叙述距离": "中距，贴着感官",
            "语气": "克制、冷而干净",
            "节奏": "短句推进，少解释",
            "对话规则": ["少称呼全名"],
            "词汇偏好": ["河风"],
            "禁用表达": ["哇塞"],
            "正例": [POSITIVE_EXAMPLE],
            "反例": [NEGATIVE_EXAMPLE],
            "created_by": "主编",
        },
    )
    assert guide.status_code == 201, guide.text
    approved = client.post(
        f"/projects/{project_id}/style-guides/{guide.json()['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    run = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/drafts/{draft_id}/style-validations",
        headers=HUMAN,
        json={
            "style_guide_revision_id": approved.json()["id"],
            "include_llm": False,
            "created_by": "主编",
        },
    )
    assert run.status_code == 201, run.text
    return run.json()


def _passed_report(client: TestClient, project_id: str, candidate_id: str) -> dict:
    run = client.post(
        f"/projects/{project_id}/validation-runs",
        headers=HUMAN,
        json={"candidate_ids": [candidate_id]},
    )
    assert run.status_code == 201, run.text
    assert run.json()["state"] == "Passed"
    report = client.get(
        f"/projects/{project_id}/validation-runs/{run.json()['id']}/report"
    )
    assert report.status_code == 200, report.text
    return report.json()


def _rule_failed_and_repair(
    client: TestClient,
    project_id: str,
    scene_id: str,
    *,
    story_order: int,
    arc_id: str | None = None,
) -> tuple[dict, dict]:
    chapter = _create_chapter(
        client, project_id, title="试门", sort_order=2, arc_id=arc_id
    )
    scene = _create_scene(client, project_id, chapter["id"], story_order=story_order)
    approved = client.post(
        f"/projects/{project_id}/scenes/{scene['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    snapshot = client.post(
        f"/projects/{project_id}/canon-snapshots",
        headers=HUMAN,
        json={
            "as_of_scene_seq": story_order,
            "as_of_story_time": "day-02",
            "created_by": "主编",
        },
    )
    assert snapshot.status_code == 201, snapshot.text
    plan_job = client.post(
        f"/projects/{project_id}/scenes/{scene['id']}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot.json()["id"]},
    )
    assert plan_job.status_code == 201, plan_job.text
    plan = client.get(f"/projects/{project_id}/scenes/{scene['id']}/plans/current")
    assert plan.status_code == 200, plan.text
    draft_job = client.post(
        f"/projects/{project_id}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json={
            "snapshot_id": snapshot.json()["id"],
            "plan_id": plan.json()["plan"]["id"],
            "context_pack_id": STATIC_CONTEXT_PACK_ID,
        },
    )
    assert draft_job.status_code == 201, draft_job.text
    extracted = client.post(
        f"/projects/{project_id}/scenes/{scene['id']}/drafts/"
        f"{draft_job.json()['draft_id']}/extract-jobs",
        headers=GENERATE,
        json={},
    )
    assert extracted.status_code == 201, extracted.text
    listed = client.get(
        f"/projects/{project_id}/scenes/{scene['id']}/candidate-changes"
    )
    candidate = listed.json()["items"][0]
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
    approved_fact = client.post(
        f"/projects/{project_id}/canon-facts/{fact.json()['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved_fact.status_code == 200, approved_fact.text
    assert approved_fact.json()["status"] == FACT_ACTIVE
    repo = client.app.state.candidate_change_repository
    item = repo.get_candidate(candidate["id"])
    assert item is not None
    item.object = "路人"
    item.value = "路人持有残玉"
    item.evidence_quote = "残玉在路人手中也亮了"
    item.payload["object"] = item.object
    item.payload["value"] = item.value
    item.payload["evidence_quote"] = item.evidence_quote
    repo.save_candidate(item)
    run = client.post(
        f"/projects/{project_id}/validation-runs",
        headers=HUMAN,
        json={"candidate_ids": [candidate["id"]]},
    )
    assert run.status_code == 201, run.text
    assert run.json()["state"] == "RuleFailed"
    report = client.get(
        f"/projects/{project_id}/validation-runs/{run.json()['id']}/report"
    )
    assert report.status_code == 200, report.text
    repair = client.post(
        f"/projects/{project_id}/repair-tasks",
        headers=HUMAN,
        json={"validation_run_id": run.json()["id"], "action": "Reextract"},
    )
    assert repair.status_code == 201, repair.text
    return report.json(), repair.json()


def _canon_fact_count(canon: InMemoryCanonRepository, project_id: str) -> int:
    return len([item for item in canon.facts.values() if item.project_id == project_id])


def _queue_url(project_id: str, item_id: str | None = None, tail: str = "") -> str:
    base = f"/projects/{project_id}/review-queue"
    if item_id is None:
        return base
    return f"{base}/{item_id}{tail}"


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
    assert "/projects/{project_id}/review-queue" in paths
    assert "/projects/{project_id}/review-queue/{item_id}" in paths
    assert "/projects/{project_id}/review-queue/{item_id}/approve" in paths
    assert "/projects/{project_id}/review-queue/{item_id}/reject" in paths
    assert "/projects/{project_id}/review-queue/{item_id}/request-revision" in paths
    assert "/projects/{project_id}/review-queue/{item_id}/escalate" in paths
    assert "/projects/{project_id}/review-queue/{item_id}/export" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/auto-approve" not in paths
    assert "/projects/{project_id}/workers" not in paths
    assert "/projects/{project_id}/agent-registry" not in paths
    assert (
        "/projects/{project_id}/candidate-changes/{candidate_id}/seed-status"
        not in paths
    )
    assert not any("seed-status" in path for path in paths)
    assert not any("orchestrat" in path for path in paths)


def test_six_subjects_enqueue_with_required_fields() -> None:
    client, sink, canon = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    style = _style_report(client, project_id, data["scene"]["id"], data["draft"]["id"])
    report = _passed_report(client, project_id, data["candidate"]["id"])
    failed_report, repair = _rule_failed_and_repair(
        client,
        project_id,
        data["scene"]["id"],
        story_order=2,
        arc_id=data["chapter"]["arc_id"],
    )
    before = _canon_fact_count(canon, project_id)
    subjects = [
        ("scene_plan", data["plan"]["id"]),
        ("scene_draft", data["draft"]["id"]),
        ("candidate_change", data["candidate"]["id"]),
        ("validation_report", report["id"]),
        ("repair_task", repair["id"]),
        ("style_report", style["id"]),
    ]
    items = []
    for subject_type, subject_id in subjects:
        item = _enqueue(client, project_id, subject_type, subject_id)
        items.append(item)
        assert item["status"] == "Opened"
        assert item["chapter_id"]
        assert item["diff"]["kind"] == subject_type
        assert isinstance(item["input_versions"], dict)
        assert isinstance(item["evidence_refs"], list)
        assert item["is_canon_approval"] is False
        assert item["blocks_canon_submit"] is False
    listed = client.get(f"/projects/{project_id}/review-queue")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["items"]) >= 6
    assert _canon_fact_count(canon, project_id) == before
    actions = [event.action for event in sink.events]
    assert actions.count("review_queue.enqueue") >= 6
    assert failed_report["id"] != report["id"]
    again = client.post(
        f"/projects/{project_id}/review-queue/items",
        headers=HUMAN,
        json={"subject_type": "scene_plan", "subject_id": data["plan"]["id"]},
    )
    assert again.status_code == 201
    assert again.json()["id"] == items[0]["id"]


def test_human_decisions_require_reason_code() -> None:
    client, _, _ = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    style = _style_report(client, project_id, data["scene"]["id"], data["draft"]["id"])
    plan_item = _enqueue(client, project_id, "scene_plan", data["plan"]["id"])
    draft_item = _enqueue(client, project_id, "scene_draft", data["draft"]["id"])
    style_item = _enqueue(client, project_id, "style_report", style["id"])
    extra_plan = client.post(
        f"/projects/{project_id}/review-queue/items",
        headers=HUMAN,
        json={"subject_type": "scene_draft", "subject_id": data["draft"]["id"]},
    )
    # Re-enqueue of the open draft item is idempotent; make another plan-like
    # subject for request_revision by using the style item later.
    assert extra_plan.status_code == 201
    missing = client.post(
        _queue_url(project_id, plan_item["id"], "/approve"),
        headers=HUMAN,
        json={},
    )
    assert missing.status_code == 422, missing.text
    assert missing.json()["detail"]["error"] == "reason_code_required"
    approved = client.post(
        _queue_url(project_id, plan_item["id"], "/approve"),
        headers=HUMAN,
        json={"reason_code": "editorial_ok", "comment": "节拍可用"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["item"]["status"] == "Approved"
    assert approved.json()["decision"]["reason_code"] == "editorial_ok"
    assert approved.json()["decision"]["comment"] == "节拍可用"
    assert approved.json()["writes_canon"] is False
    rejected = client.post(
        _queue_url(project_id, draft_item["id"], "/reject"),
        headers=HUMAN,
        json={"reason_code": "editorial_reject"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["item"]["status"] == "Rejected"
    revised = client.post(
        _queue_url(project_id, style_item["id"], "/request-revision"),
        headers=HUMAN,
        json={"reason_code": "needs_revision"},
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["item"]["status"] == "RevisionRequested"
    candidate_item = _enqueue(
        client, project_id, "candidate_change", data["candidate"]["id"]
    )
    escalated = client.post(
        _queue_url(project_id, candidate_item["id"], "/escalate"),
        headers=HUMAN,
        json={"reason_code": "escalate"},
    )
    assert escalated.status_code == 200, escalated.text
    assert escalated.json()["item"]["status"] == "Escalated"
    fetched = client.get(_queue_url(project_id, plan_item["id"]))
    assert fetched.status_code == 200
    history = fetched.json()["decision_history"]
    assert history
    assert history[0]["reason_code"] == "editorial_ok"


def test_non_human_decisions_are_403() -> None:
    client, _, canon = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    item = _enqueue(client, project_id, "scene_plan", data["plan"]["id"])
    before = _canon_fact_count(canon, project_id)
    for headers in (SYSTEM, GENERATE, REVIEW):
        for tail in ("/approve", "/reject", "/request-revision", "/escalate"):
            response = client.post(
                _queue_url(project_id, item["id"], tail),
                headers=headers,
                json={"reason_code": "auto"},
            )
            assert response.status_code == 403, response.text
            assert response.json()["detail"]["error"] == "human_editor_required"
    still = client.get(_queue_url(project_id, item["id"]))
    assert still.json()["status"] == "Opened"
    assert _canon_fact_count(canon, project_id) == before


def test_filter_and_sort_by_blocker_chapter_and_status() -> None:
    client, _, _ = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    style = _style_report(client, project_id, data["scene"]["id"], data["draft"]["id"])
    failed_report, repair = _rule_failed_and_repair(
        client,
        project_id,
        data["scene"]["id"],
        story_order=2,
        arc_id=data["chapter"]["arc_id"],
    )
    plan_item = _enqueue(client, project_id, "scene_plan", data["plan"]["id"])
    style_item = _enqueue(client, project_id, "style_report", style["id"])
    report_item = _enqueue(client, project_id, "validation_report", failed_report["id"])
    repair_item = _enqueue(client, project_id, "repair_task", repair["id"])
    assert report_item["is_blocker"] is True
    assert repair_item["is_blocker"] is True
    assert style_item["is_blocker"] is False
    client.post(
        _queue_url(project_id, plan_item["id"], "/approve"),
        headers=HUMAN,
        json={"reason_code": "editorial_ok"},
    )
    blockers = client.get(f"/projects/{project_id}/review-queue?blocker=true")
    assert blockers.status_code == 200
    blocker_ids = {item["id"] for item in blockers.json()["items"]}
    assert report_item["id"] in blocker_ids
    assert repair_item["id"] in blocker_ids
    assert plan_item["id"] not in blocker_ids
    opened = client.get(f"/projects/{project_id}/review-queue?status=Opened")
    opened_ids = {item["id"] for item in opened.json()["items"]}
    assert report_item["id"] in opened_ids
    assert plan_item["id"] not in opened_ids
    chapter_a = client.get(
        f"/projects/{project_id}/review-queue?chapter_id={data['chapter']['id']}"
    )
    chapter_ids = {item["chapter_id"] for item in chapter_a.json()["items"]}
    assert chapter_ids == {data["chapter"]["id"]}
    sorted_items = client.get(
        f"/projects/{project_id}/review-queue?sort=status,subject_type"
    )
    assert sorted_items.status_code == 200
    statuses = [item["status"] for item in sorted_items.json()["items"]]
    assert statuses == sorted(statuses)


def test_export_review_pack_and_audit_redaction() -> None:
    client, sink, _ = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    style = _style_report(client, project_id, data["scene"]["id"], data["draft"]["id"])
    item = _enqueue(client, project_id, "style_report", style["id"])
    client.post(
        _queue_url(project_id, item["id"], "/approve"),
        headers=HUMAN,
        json={
            "reason_code": "style_note",
            "comment": POSITIVE_EXAMPLE,
        },
    )
    exported = client.get(_queue_url(project_id, item["id"], "/export"))
    assert exported.status_code == 200, exported.text
    pack = exported.json()
    assert pack["schema"] == "review-pack.v1"
    assert pack["item"]["id"] == item["id"]
    assert pack["subject"]["subject_type"] == "style_report"
    assert pack["subject"]["input_versions"]
    assert pack["subject"]["evidence_refs"]
    assert pack["subject"]["diff"]["kind"] == "style_report"
    assert pack["decisions"]
    assert pack["writes_canon"] is False
    assert pack["is_canon_approval"] is False
    assert pack["style_report_approve_is_canon_approve"] is False
    assert pack["blocks_canon_submit"] is False
    dumped = str(sink.events)
    assert POSITIVE_EXAMPLE not in dumped
    assert NEGATIVE_EXAMPLE not in dumped
    for event in sink.events:
        blob = str(event.before_json) + str(event.after_json)
        assert "text_evidence" not in blob or "redacted" in blob.lower()
        assert POSITIVE_EXAMPLE not in blob
        assert "哇塞这玉也太酷了吧路人也能触活" not in blob
    actions = [event.action for event in sink.events]
    assert "review_queue.approve" in actions
    assert "review_decision.create" in actions


def test_candidate_approve_reuses_4_2_and_does_not_write_canon() -> None:
    client, sink, canon = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    candidate_id = data["candidate"]["id"]
    _seed_awaiting(client, project_id, candidate_id)
    before = _canon_fact_count(canon, project_id)
    item = _enqueue(client, project_id, "candidate_change", candidate_id)
    assert item["canon_commit_required"] is True
    assert item["canon_commit_path"] == (
        f"POST /projects/{project_id}/candidate-changes/{candidate_id}/submit"
    )
    approved = client.post(
        _queue_url(project_id, item["id"], "/approve"),
        headers=HUMAN,
        json={"reason_code": "editorial_ok", "created_by": "主编"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["writes_canon"] is False
    assert approved.json()["auto_submitted"] is False
    assert approved.json()["item"]["status"] == "Approved"
    fetched = client.get(f"/projects/{project_id}/candidate-changes/{candidate_id}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == CANDIDATE_APPROVED
    assert fetched.json()["writes_canon"] is False
    assert fetched.json()["submitted_canon_fact_id"] is None
    assert _canon_fact_count(canon, project_id) == before
    exported = client.get(_queue_url(project_id, item["id"], "/export"))
    assert exported.json()["canon_commit_path"].endswith("/submit")
    assert "not submit" in exported.json()["note"]
    submitted = client.post(
        f"/projects/{project_id}/candidate-changes/{candidate_id}/submit",
        headers=HUMAN,
        json={"created_by": "主编", "entity_type": "物品"},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["writes_canon"] is True
    assert submitted.json()["candidate"]["status"] == CANDIDATE_SUBMITTED
    assert _canon_fact_count(canon, project_id) == before + 1
    assert "candidate_change.submit" in [event.action for event in sink.events]


def test_style_report_approve_is_not_canon_approve() -> None:
    client, _, canon = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    style = _style_report(client, project_id, data["scene"]["id"], data["draft"]["id"])
    before = _canon_fact_count(canon, project_id)
    item = _enqueue(client, project_id, "style_report", style["id"])
    assert item["blocks_canon_submit"] is False
    assert item["style_report_approve_is_canon_approve"] is False
    approved = client.post(
        _queue_url(project_id, item["id"], "/approve"),
        headers=HUMAN,
        json={"reason_code": "style_note"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["is_canon_approval"] is False
    assert approved.json()["blocks_canon_submit"] is False
    assert approved.json()["style_report_approve_is_canon_approve"] is False
    assert _canon_fact_count(canon, project_id) == before
    candidate = data["candidate"]
    _seed_awaiting(client, project_id, candidate["id"])
    human_approve = client.post(
        f"/projects/{project_id}/candidate-changes/{candidate['id']}/approve",
        headers=HUMAN,
        json={"created_by": "主编"},
    )
    assert human_approve.status_code == 200, human_approve.text
    submitted = client.post(
        f"/projects/{project_id}/candidate-changes/{candidate['id']}/submit",
        headers=HUMAN,
        json={"created_by": "主编", "entity_type": "物品"},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["writes_canon"] is True


def test_cancel_keeps_record() -> None:
    client, _, _ = _client()
    data = _pipeline(client)
    project_id = data["project"]["id"]
    item = _enqueue(client, project_id, "scene_plan", data["plan"]["id"])
    cancelled = client.post(
        _queue_url(project_id, item["id"], "/cancel"),
        headers=HUMAN,
        json={"reason_code": "withdrawn"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["item"]["status"] == "Cancelled"
    assert cancelled.json()["kept"] is True
    fetched = client.get(_queue_url(project_id, item["id"]))
    assert fetched.status_code == 200
    assert fetched.json()["id"] == item["id"]
    listed = client.get(f"/projects/{project_id}/review-queue?status=Cancelled")
    assert any(row["id"] == item["id"] for row in listed.json()["items"])


def test_migration_adds_queue_tables_without_rebuilding_prior() -> None:
    versions = ROOT / "backend" / "alembic" / "versions"
    create = (versions / "017_create_review_queue.py").read_text(encoding="utf-8")
    assert "CREATE TABLE review_queue_items" in create
    assert "CREATE TABLE review_decisions" in create
    assert "CREATE TABLE style_validations" not in create
    assert "CREATE TABLE scene_drafts" not in create
    assert "CREATE TABLE validation_runs" not in create
    assert "CREATE TABLE repair_tasks" not in create
    assert 'down_revision: str | None = "016_style_validation"' in create
    upgrade = create.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    lowered = upgrade.lower()
    assert "vector(" not in lowered
    assert "embedding" not in lowered
    assert "openai" not in lowered
    assert "worker" not in lowered
    assert "agent_registry" not in lowered
    package = ROOT / "backend" / "slove_context" / "review_queue"
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in ("openai", "anthropic", "langchain", "chromadb", "pgvector"):
            assert f"import {name}" not in text
            assert f"from {name}" not in text
    draft_service = (
        ROOT / "backend" / "slove_context" / "scene_draft" / "service.py"
    ).read_text(encoding="utf-8")
    assert "review_queue" not in draft_service
    validation_rules = (
        ROOT / "backend" / "slove_context" / "validation" / "rules.py"
    ).read_text(encoding="utf-8")
    assert "review_queue" not in validation_rules
