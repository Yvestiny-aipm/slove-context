"""Single-scene DAG orchestrator (node 8.3).

In-memory repositories. No live Postgres. No network. No real models.
The orchestrator dispatches through the 8.1 Worker. canon_commit
calls existing 4.2 submit only after a human 主编 approve.
2.1–8.2 APIs and /healthz remain.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import REDACTED, AuditWriter, InMemoryAuditSink
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.dags.graph import (
    NODE_CANDIDATE_EXTRACTION,
    NODE_CANON_COMMIT,
    NODE_CONTEXT_PACK,
    NODE_DOWNSTREAM_UNBLOCK,
    NODE_DRAFT_VALIDATION,
    NODE_HUMAN_REVIEW,
    NODE_IDS,
    NODE_PLAN_VALIDATION,
    NODE_SCENE_DRAFT,
    NODE_SCENE_PLAN,
    NODE_SPECS,
    NODE_SUMMARY,
    parallel_write_pairs,
    writes_are_disjoint,
)
from slove_context.dags.models import (
    DAG_BLOCKED,
    DAG_SUCCEEDED,
    DAG_WAITING_HUMAN,
    STATUS_BLOCKED,
    STATUS_SUCCEEDED,
    STATUS_WAITING_HUMAN,
)
from slove_context.dags.repository import InMemoryDagRepository
from slove_context.jobs.repository import InMemoryJobRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.scene.repository import InMemorySceneRepository
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
        job_repository=InMemoryJobRepository(),
        dag_repository=InMemoryDagRepository(),
        audit_writer=writer,
        llm_gateway=LlmGateway(
            FakeProvider(),
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
        job_auto_run=False,
        job_base_backoff_s=0.0,
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


def _ready_scene(client: TestClient) -> dict[str, dict]:
    project = _create_project(client)
    _write_spec(client, project["id"])
    scene = _create_scene(client, project["id"])
    snapshot = _create_snapshot(client, project["id"])
    return {"project": project, "scene": scene, "snapshot": snapshot}


def _create_dag(
    client: TestClient,
    data: dict[str, dict],
    *,
    rebuild_context_pack: bool = False,
    start_from: str | None = None,
) -> dict:
    body: dict[str, object] = {"snapshot_id": data["snapshot"]["id"]}
    if rebuild_context_pack:
        body["rebuild_context_pack"] = True
    if start_from is not None:
        body["start_from"] = start_from
    response = client.post(
        f"/projects/{data['project']['id']}/scenes/{data['scene']['id']}/dags",
        headers=GENERATE,
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _advance(client: TestClient, project_id: str, dag_id: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/dags/{dag_id}/advance",
        headers=GENERATE,
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _node(dag: dict, node_id: str) -> dict:
    matches = [item for item in dag["nodes"] if item["node_id"] == node_id]
    assert matches, node_id
    return matches[0]


def _canon_fact_count(canon: InMemoryCanonRepository, project_id: str) -> int:
    return len([item for item in canon.facts.values() if item.project_id == project_id])


def _seed_conflict(client: TestClient, project_id: str, scene_id: str) -> None:
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
            "value_json": {"object": "路人", "value": "路人持有残玉"},
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


def test_fixed_nodes_and_parallel_writes_are_disjoint() -> None:
    assert list(NODE_SPECS) == list(NODE_IDS)
    for node_id, spec in NODE_SPECS.items():
        assert spec.inputs
        assert spec.outputs
        assert spec.failure_policy
        assert spec.id == node_id
    assert NODE_SPECS[NODE_CANDIDATE_EXTRACTION].dependencies == (NODE_SCENE_DRAFT,)
    assert NODE_SPECS[NODE_DRAFT_VALIDATION].dependencies == (NODE_SCENE_DRAFT,)
    assert NODE_SPECS[NODE_CANON_COMMIT].dependencies == (NODE_HUMAN_REVIEW,)
    for left, right in parallel_write_pairs():
        assert writes_are_disjoint(left, right)
        assert NODE_SPECS[left].writes
        assert NODE_SPECS[right].writes
    shared = (
        NODE_SPECS[NODE_CANDIDATE_EXTRACTION].writes
        & NODE_SPECS[NODE_DRAFT_VALIDATION].writes
    )
    assert shared == frozenset()


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
    assert "/projects/{project_id}/agent-runs" in paths
    assert "/agents" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/dags" in paths
    assert "/projects/{project_id}/dags/{dag_id}/graph" in paths
    assert "/projects/{project_id}/dags/{dag_id}/human-review" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/auto-approve" not in paths
    assert "/projects/{project_id}/batch" not in paths
    assert not any("seed-status" in path for path in paths)


def test_full_success_human_approve_then_canon_commit() -> None:
    client, sink, canon = _client()
    data = _ready_scene(client)
    project_id = data["project"]["id"]
    before = _canon_fact_count(canon, project_id)
    created = _create_dag(client, data)
    dag = _advance(client, project_id, created["id"])
    assert dag["status"] == DAG_WAITING_HUMAN
    assert dag["auto_canon_commit"] is False
    assert _node(dag, NODE_HUMAN_REVIEW)["status"] == STATUS_WAITING_HUMAN
    assert _node(dag, NODE_CANON_COMMIT)["status"] != STATUS_SUCCEEDED
    assert _canon_fact_count(canon, project_id) == before

    forbidden = client.post(
        f"/projects/{project_id}/dags/{created['id']}/human-review",
        headers=GENERATE,
        json={"decision": "approve", "reason_code": "looks_right"},
    )
    assert forbidden.status_code == 403

    reviewed = client.post(
        f"/projects/{project_id}/dags/{created['id']}/human-review",
        headers=HUMAN,
        json={"decision": "approve", "reason_code": "looks_right"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["human_decision"] == "approve"
    assert _canon_fact_count(canon, project_id) == before

    finished = _advance(client, project_id, created["id"])
    assert finished["status"] == DAG_SUCCEEDED
    assert _node(finished, NODE_CANON_COMMIT)["status"] == STATUS_SUCCEEDED
    assert _node(finished, NODE_SUMMARY)["status"] == STATUS_SUCCEEDED
    assert _node(finished, NODE_DOWNSTREAM_UNBLOCK)["status"] == STATUS_SUCCEEDED
    assert _canon_fact_count(canon, project_id) > before
    graph = client.get(f"/projects/{project_id}/dags/{created['id']}/graph")
    assert graph.status_code == 200
    body = graph.json()
    assert body["nodes"]
    for item in body["nodes"]:
        assert "status" in item
        assert "duration_ms" in item
        if item["id"] in {
            NODE_CONTEXT_PACK,
            NODE_SCENE_PLAN,
            NODE_SCENE_DRAFT,
            NODE_CANON_COMMIT,
        }:
            assert item["duration_ms"] is not None
    assert any(event.action == "scene_dag.create" for event in sink.events)
    assert any(event.action == "candidate_change.submit" for event in sink.events)
    assert any(event.action == "scene_dag.human_review" for event in sink.events)
    for event in sink.events:
        dumped = str(event.after_json) + str(event.before_json)
        assert "api_key" not in dumped.lower() or REDACTED in dumped


def test_validation_failure_is_blocker_and_skips_canon_commit() -> None:
    client, _, canon = _client()
    data = _ready_scene(client)
    project_id = data["project"]["id"]
    _seed_conflict(client, project_id, data["scene"]["id"])
    before = _canon_fact_count(canon, project_id)
    created = _create_dag(client, data)
    dag = _advance(client, project_id, created["id"])
    assert dag["blocked"] is True
    assert dag["status"] == DAG_BLOCKED
    assert dag["blocker_node_id"] == NODE_DRAFT_VALIDATION
    assert _node(dag, NODE_DRAFT_VALIDATION)["status"] == STATUS_BLOCKED
    assert _node(dag, NODE_CANON_COMMIT)["status"] == STATUS_BLOCKED
    assert _node(dag, NODE_HUMAN_REVIEW)["status"] == STATUS_BLOCKED
    later = _advance(client, project_id, created["id"])
    assert later["blocked"] is True
    assert _node(later, NODE_CANON_COMMIT)["status"] != STATUS_SUCCEEDED
    assert _canon_fact_count(canon, project_id) == before
    review = client.post(
        f"/projects/{project_id}/dags/{created['id']}/human-review",
        headers=HUMAN,
        json={"decision": "approve", "reason_code": "force"},
    )
    assert review.status_code == 409


def test_human_reject_does_not_canon_commit() -> None:
    client, _, canon = _client()
    data = _ready_scene(client)
    project_id = data["project"]["id"]
    before = _canon_fact_count(canon, project_id)
    created = _create_dag(client, data)
    dag = _advance(client, project_id, created["id"])
    assert dag["status"] == DAG_WAITING_HUMAN
    rejected = client.post(
        f"/projects/{project_id}/dags/{created['id']}/human-review",
        headers=HUMAN,
        json={"decision": "reject", "reason_code": "not_canon"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["human_decision"] == "reject"
    assert rejected.json()["blocked"] is True
    assert _node(rejected.json(), NODE_CANON_COMMIT)["status"] == STATUS_BLOCKED
    later = _advance(client, project_id, created["id"])
    assert _node(later, NODE_CANON_COMMIT)["status"] != STATUS_SUCCEEDED
    assert _canon_fact_count(canon, project_id) == before


def test_repair_rerun_reuses_frozen_upstream_unless_rebuild_pack() -> None:
    client, _, canon = _client()
    data = _ready_scene(client)
    project_id = data["project"]["id"]
    _seed_conflict(client, project_id, data["scene"]["id"])
    before = _canon_fact_count(canon, project_id)
    created = _create_dag(client, data)
    blocked = _advance(client, project_id, created["id"])
    pack_id = blocked["frozen_outputs"]["context_pack_id"]
    plan_id = blocked["frozen_outputs"]["plan_id"]
    draft_id = blocked["frozen_outputs"]["draft_revision_id"]
    assert pack_id
    assert plan_id

    non_human = client.post(
        f"/projects/{project_id}/dags/{created['id']}/rerun",
        headers=SYSTEM,
        json={"from_node": NODE_CANDIDATE_EXTRACTION},
    )
    assert non_human.status_code == 403

    rerun = client.post(
        f"/projects/{project_id}/dags/{created['id']}/rerun",
        headers=HUMAN,
        json={"from_node": NODE_CANDIDATE_EXTRACTION, "rebuild_context_pack": False},
    )
    assert rerun.status_code == 200, rerun.text
    body = rerun.json()
    assert _node(body, NODE_CONTEXT_PACK)["status"] == STATUS_SUCCEEDED
    assert _node(body, NODE_SCENE_PLAN)["status"] == STATUS_SUCCEEDED
    assert _node(body, NODE_SCENE_DRAFT)["status"] == STATUS_SUCCEEDED
    assert _node(body, NODE_CANDIDATE_EXTRACTION)["status"] == "pending"
    assert body["frozen_outputs"]["context_pack_id"] == pack_id
    assert body["frozen_outputs"]["plan_id"] == plan_id
    assert body["frozen_outputs"]["draft_revision_id"] == draft_id
    assert "candidate_ids" not in body["frozen_outputs"]
    again = _advance(client, project_id, created["id"])
    assert again["frozen_outputs"]["context_pack_id"] == pack_id
    assert again["frozen_outputs"]["plan_id"] == plan_id
    assert again["blocked"] is True
    assert _canon_fact_count(canon, project_id) == before

    rebuild = client.post(
        f"/projects/{project_id}/dags/{created['id']}/rerun",
        headers=HUMAN,
        json={"from_node": NODE_SCENE_DRAFT, "rebuild_context_pack": True},
    )
    assert rebuild.status_code == 200, rebuild.text
    assert _node(rebuild.json(), NODE_CONTEXT_PACK)["status"] == "pending"
    assert "context_pack_id" not in rebuild.json()["frozen_outputs"]
    rebuilt = _advance(client, project_id, created["id"])
    new_pack = rebuilt["frozen_outputs"]["context_pack_id"]
    assert new_pack
    assert new_pack != pack_id
    assert rebuilt["frozen_outputs"]["plan_id"] == plan_id


def test_dag_order_and_blocker_stops_later_submit() -> None:
    client, _, canon = _client()
    data = _ready_scene(client)
    project_id = data["project"]["id"]
    created = _create_dag(client, data)
    dag = _advance(client, project_id, created["id"])
    order = [
        NODE_CONTEXT_PACK,
        NODE_SCENE_PLAN,
        NODE_PLAN_VALIDATION,
        NODE_SCENE_DRAFT,
        NODE_CANDIDATE_EXTRACTION,
        NODE_DRAFT_VALIDATION,
    ]
    for node_id in order:
        assert _node(dag, node_id)["status"] == STATUS_SUCCEEDED, node_id
    extract_writes = set(_node(dag, NODE_CANDIDATE_EXTRACTION)["writes"])
    validate_writes = set(_node(dag, NODE_DRAFT_VALIDATION)["writes"])
    assert extract_writes.isdisjoint(validate_writes)
    assert _node(dag, NODE_CANON_COMMIT)["status"] != STATUS_SUCCEEDED
    assert _canon_fact_count(canon, project_id) == 0


def test_cancel_keeps_record_and_audit_is_redacted() -> None:
    client, sink, _ = _client()
    data = _ready_scene(client)
    project_id = data["project"]["id"]
    created = _create_dag(client, data)
    cancelled = client.post(
        f"/projects/{project_id}/dags/{created['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["kept"] is True
    item = cancelled.json()["item"]
    assert item["status"] == "cancelled"
    fetched = client.get(f"/projects/{project_id}/dags/{created['id']}")
    assert fetched.json()["status"] == "cancelled"
    assert fetched.json()["kept"] is True
    assert any(event.action == "scene_dag.cancel" for event in sink.events)
    for event in sink.events:
        blob = event.after_json or {}
        assert "system_prompt" not in blob
        assert "user_prompt" not in blob
        assert "prose" not in blob
