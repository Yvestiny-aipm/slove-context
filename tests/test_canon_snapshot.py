"""Canon Snapshot create / freeze / query / diff / replay (node 2.3).

In-memory repository. No live Postgres. No model calls.
No Scene Card, Context Pack, generator, vector search, or LLM.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.story.repository import InMemoryStoryRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
SCENE_1 = "11111111-1111-4111-8111-111111111111"
SCENE_2 = "22222222-2222-4222-8222-222222222222"


def _client() -> tuple[TestClient, InMemoryAuditSink]:
    sink = InMemoryAuditSink()
    app = create_app(
        repository=InMemoryStoryRepository(),
        canon_repository=InMemoryCanonRepository(),
        audit_writer=AuditWriter(sink),
    )
    return TestClient(app), sink


def _create_project(client: TestClient) -> dict:
    response = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": "青石夜祠", "language": "zh-CN", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_entity(
    client: TestClient,
    project_id: str,
    *,
    name: str = "林晚",
    entity_type: str = "角色",
) -> dict:
    response = client.post(
        f"/projects/{project_id}/entities",
        headers=HUMAN,
        json={"name": name, "entity_type": entity_type, "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_evidence(
    client: TestClient,
    project_id: str,
    *,
    scene_id: str = SCENE_1,
    quote: str = "她把残玉按进缺口，门轴轻响",
) -> dict:
    response = client.post(
        f"/projects/{project_id}/evidence",
        headers=HUMAN,
        json={
            "source_type": "prose",
            "quote": quote,
            "scene_id": scene_id,
            "created_by": "主编",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_active_fact(
    client: TestClient,
    project_id: str,
    entity_id: str,
    evidence_id: str,
    **overrides: object,
) -> dict:
    payload = {
        "entity_id": entity_id,
        "predicate": "左腕有",
        "value_json": {"text": "烧痕"},
        "effective_story_time": "day-01",
        "valid_from_scene_id": SCENE_1,
        "source_type": "prose",
        "evidence_id": evidence_id,
        "created_by": "主编",
    }
    payload.update(overrides)
    created = client.post(
        f"/projects/{project_id}/canon-facts",
        headers=HUMAN,
        json=payload,
    )
    assert created.status_code == 201, created.text
    approved = client.post(
        f"/projects/{project_id}/canon-facts/{created.json()['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def _create_snapshot(
    client: TestClient,
    project_id: str,
    **overrides: object,
) -> dict:
    payload = {
        "as_of_scene_seq": 1,
        "as_of_story_time": "day-01",
        "created_by": "主编",
    }
    payload.update(overrides)
    response = client.post(
        f"/projects/{project_id}/canon-snapshots",
        headers=HUMAN,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_snapshot_routes_exist_and_21_22_health_remain() -> None:
    client, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/version").json().get("version")
    paths = client.get("/openapi.json").json()["paths"]
    assert "/healthz" in paths
    assert "/version" in paths
    assert "/projects" in paths
    assert "/projects/{project_id}/specs/{spec_id}/approve" in paths
    assert "/projects/{project_id}/canon-facts" in paths
    assert "/projects/{project_id}/canon-snapshots" in paths
    assert "/projects/{project_id}/canon-snapshots/{snapshot_id}" in paths
    assert "/projects/{project_id}/canon-snapshots/{snapshot_id}/facts" in paths
    assert "/projects/{project_id}/canon-snapshots/{snapshot_id}/freeze" in paths
    assert (
        "/projects/{project_id}/canon-snapshots/{snapshot_id_a}/diff/{snapshot_id_b}"
        in paths
    )
    assert "/projects/{project_id}/canon-replay" in paths
    assert "/projects/{project_id}/scene-cards" not in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/chapters/{chapter_id}/context-packs" not in paths


def test_create_then_freeze_is_read_only_and_audited() -> None:
    client, sink = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    fact = _create_active_fact(client, project["id"], entity["id"], evidence["id"])

    created = _create_snapshot(client, project["id"])
    assert created["status"] == "unfrozen"
    assert created["frozen_at"] is None
    assert created["as_of_scene_seq"] == 1
    assert created["as_of_story_time"] == "day-01"
    assert created["fact_ids"] == [fact["id"]]

    frozen = client.post(
        f"/projects/{project['id']}/canon-snapshots/{created['id']}/freeze",
        headers=HUMAN,
        json={},
    )
    assert frozen.status_code == 200, frozen.text
    body = frozen.json()
    assert body["status"] == "frozen"
    assert body["frozen_at"]
    assert body["fact_ids"] == [fact["id"]]

    again = client.post(
        f"/projects/{project['id']}/canon-snapshots/{created['id']}/freeze",
        headers=HUMAN,
        json={},
    )
    assert again.status_code == 409
    assert again.json()["detail"]["error"] == "snapshot_already_frozen"

    patched = client.patch(
        f"/projects/{project['id']}/canon-snapshots/{created['id']}",
        headers=HUMAN,
        json={"fact_ids": []},
    )
    assert patched.status_code in {404, 405}

    fetched = client.get(f"/projects/{project['id']}/canon-snapshots/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["fact_ids"] == [fact["id"]]
    assert fetched.json()["status"] == "frozen"

    actions = [event.action for event in sink.events]
    assert "canon_snapshot.create" in actions
    assert "canon_snapshot.freeze" in actions
    freeze_events = [
        event for event in sink.events if event.action == "canon_snapshot.freeze"
    ]
    assert freeze_events[0].actor_type == "human_editor"
    assert freeze_events[0].after_json is not None
    assert freeze_events[0].after_json["status"] == "frozen"


def test_non_human_cannot_freeze_snapshot() -> None:
    client, sink = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    _create_active_fact(client, project["id"], entity["id"], evidence["id"])
    snapshot = _create_snapshot(client, project["id"])

    for actor_type in ("system", "generation_agent", "review_agent"):
        response = client.post(
            f"/projects/{project['id']}/canon-snapshots/{snapshot['id']}/freeze",
            headers={"X-Actor-Type": actor_type, "X-Actor-Id": "bot"},
            json={},
        )
        assert response.status_code == 403, actor_type
        assert response.json()["detail"]["error"] == "human_editor_required"

    missing = client.post(
        f"/projects/{project['id']}/canon-snapshots/{snapshot['id']}/freeze",
        json={},
    )
    assert missing.status_code == 403

    current = client.get(f"/projects/{project['id']}/canon-snapshots/{snapshot['id']}")
    assert current.json()["status"] == "unfrozen"
    assert not any(event.action == "canon_snapshot.freeze" for event in sink.events)


def test_later_facts_do_not_leak_into_earlier_snapshot_or_replay() -> None:
    client, _ = _client()
    project = _create_project(client)
    lin = _create_entity(client, project["id"], name="林晚")
    jade = _create_entity(client, project["id"], name="残玉", entity_type="物品")
    early_evidence = _create_evidence(client, project["id"], scene_id=SCENE_1)
    later_evidence = _create_evidence(
        client, project["id"], scene_id=SCENE_2, quote="残玉可开祠门"
    )

    burn = _create_active_fact(
        client,
        project["id"],
        lin["id"],
        early_evidence["id"],
        predicate="左腕有",
        value_json={"text": "烧痕"},
        effective_story_time="day-01",
        valid_from_scene_id=SCENE_1,
    )
    early = _create_snapshot(
        client,
        project["id"],
        as_of_scene_seq=1,
        as_of_story_time="day-01",
    )
    client.post(
        f"/projects/{project['id']}/canon-snapshots/{early['id']}/freeze",
        headers=HUMAN,
        json={},
    )

    opens = _create_active_fact(
        client,
        project["id"],
        jade["id"],
        later_evidence["id"],
        predicate="可开启",
        value_json={"object": "祠门"},
        effective_story_time="day-03",
        valid_from_scene_id=SCENE_2,
    )

    live = client.get(f"/projects/{project['id']}/canon-facts")
    live_ids = {item["id"] for item in live.json()["facts"]}
    assert live_ids == {burn["id"], opens["id"]}

    snapshot_facts = client.get(
        f"/projects/{project['id']}/canon-snapshots/{early['id']}/facts"
    )
    assert snapshot_facts.status_code == 200
    snap_ids = [item["id"] for item in snapshot_facts.json()["facts"]]
    assert snap_ids == [burn["id"]]
    assert opens["id"] not in snap_ids

    replay_time = client.get(
        f"/projects/{project['id']}/canon-replay",
        params={"snapshot_id": early["id"], "as_of_story_time": "day-03"},
    )
    assert replay_time.status_code == 200
    replay_ids = [item["id"] for item in replay_time.json()["facts"]]
    assert replay_ids == [burn["id"]]
    assert opens["id"] not in replay_ids

    replay_scene = client.get(
        f"/projects/{project['id']}/canon-replay",
        params={"snapshot_id": early["id"], "scene_id": SCENE_2},
    )
    assert replay_scene.status_code == 200
    assert replay_scene.json()["facts"] == []


def test_replay_filters_snapshot_facts_by_scene_or_story_time() -> None:
    client, _ = _client()
    project = _create_project(client)
    lin = _create_entity(client, project["id"], name="林晚")
    jade = _create_entity(client, project["id"], name="残玉", entity_type="物品")
    evidence_1 = _create_evidence(client, project["id"], scene_id=SCENE_1)
    evidence_2 = _create_evidence(
        client, project["id"], scene_id=SCENE_2, quote="第二日试门"
    )
    burn = _create_active_fact(
        client,
        project["id"],
        lin["id"],
        evidence_1["id"],
        predicate="左腕有",
        value_json={"text": "烧痕"},
        effective_story_time="day-01",
        valid_from_scene_id=SCENE_1,
    )
    opens = _create_active_fact(
        client,
        project["id"],
        jade["id"],
        evidence_2["id"],
        predicate="可开启",
        value_json={"object": "祠门"},
        effective_story_time="day-03",
        valid_from_scene_id=SCENE_2,
    )
    snapshot = _create_snapshot(
        client,
        project["id"],
        as_of_scene_seq=3,
        as_of_story_time="day-03",
    )

    by_scene = client.get(
        f"/projects/{project['id']}/canon-replay",
        params={"snapshot_id": snapshot["id"], "scene_id": SCENE_1},
    )
    assert [item["id"] for item in by_scene.json()["facts"]] == [burn["id"]]

    by_time = client.get(
        f"/projects/{project['id']}/canon-replay",
        params={"snapshot_id": snapshot["id"], "as_of_story_time": "day-01"},
    )
    assert [item["id"] for item in by_time.json()["facts"]] == [burn["id"]]

    later = client.get(
        f"/projects/{project['id']}/canon-replay",
        params={"snapshot_id": snapshot["id"], "as_of_story_time": "day-03"},
    )
    later_ids = {item["id"] for item in later.json()["facts"]}
    assert later_ids == {burn["id"], opens["id"]}

    missing = client.get(
        f"/projects/{project['id']}/canon-replay",
        params={"snapshot_id": snapshot["id"]},
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["error"] == "replay_point_required"


def test_diff_is_stably_sorted_added_removed_superseded() -> None:
    client, _ = _client()
    project = _create_project(client)
    lin = _create_entity(client, project["id"], name="林晚")
    jade = _create_entity(client, project["id"], name="残玉", entity_type="物品")
    keep_entity = _create_entity(
        client, project["id"], name="青石镇", entity_type="地点"
    )
    evidence = _create_evidence(client, project["id"])

    keep = _create_active_fact(
        client,
        project["id"],
        keep_entity["id"],
        evidence["id"],
        predicate="位于",
        value_json={"text": "河东"},
        effective_story_time="day-01",
    )
    old_burn = _create_active_fact(
        client,
        project["id"],
        lin["id"],
        evidence["id"],
        predicate="左腕有",
        value_json={"text": "烧痕"},
        effective_story_time="day-01",
    )
    abandoned_source = client.post(
        f"/projects/{project['id']}/canon-facts",
        headers=HUMAN,
        json={
            "entity_id": jade["id"],
            "predicate": "会被路人触活",
            "value_json": {"text": "否"},
            "effective_story_time": "day-01",
            "valid_from_scene_id": SCENE_1,
            "source_type": "prose",
            "evidence_id": evidence["id"],
            "created_by": "主编",
        },
    )
    assert abandoned_source.status_code == 201
    # Not approved: must not enter either snapshot.

    first = _create_snapshot(
        client,
        project["id"],
        as_of_scene_seq=1,
        as_of_story_time="day-01",
    )

    later_evidence = _create_evidence(
        client, project["id"], quote="主编改判：左腕无烧痕"
    )
    superseded = client.post(
        f"/projects/{project['id']}/canon-facts/{old_burn['id']}/supersede",
        headers=HUMAN,
        json={
            "entity_id": lin["id"],
            "predicate": "左腕有",
            "value_json": {"text": "无烧痕"},
            "effective_story_time": "day-02",
            "valid_from_scene_id": SCENE_2,
            "source_type": "editor",
            "evidence_id": later_evidence["id"],
            "created_by": "主编",
        },
    )
    assert superseded.status_code == 200, superseded.text
    new_burn = superseded.json()["fact"]

    added_fact = _create_active_fact(
        client,
        project["id"],
        jade["id"],
        evidence["id"],
        predicate="可开启",
        value_json={"object": "祠门"},
        effective_story_time="day-03",
        valid_from_scene_id=SCENE_2,
    )

    second = _create_snapshot(
        client,
        project["id"],
        as_of_scene_seq=3,
        as_of_story_time="day-03",
    )

    diff = client.get(
        f"/projects/{project['id']}/canon-snapshots/{first['id']}/diff/{second['id']}"
    )
    assert diff.status_code == 200, diff.text
    body = diff.json()
    added_ids = [item["id"] for item in body["added"]]
    removed_ids = [item["id"] for item in body["removed"]]
    superseded_ids = [item["id"] for item in body["superseded"]]

    assert keep["id"] not in added_ids
    assert keep["id"] not in removed_ids
    assert keep["id"] not in superseded_ids
    assert set(added_ids) == {new_burn["id"], added_fact["id"]}
    assert added_ids == sorted(added_ids)
    assert [item["predicate"] for item in body["added"]] == [
        next(item["predicate"] for item in body["added"] if item["id"] == fact_id)
        for fact_id in added_ids
    ]
    assert superseded_ids == [old_burn["id"]]
    assert removed_ids == []

    predicates_added = [item["predicate"] for item in body["added"]]
    assert predicates_added == [
        item["predicate"]
        for item in sorted(
            body["added"], key=lambda item: (item["id"], item["predicate"])
        )
    ]
    assert body["superseded"] == sorted(
        body["superseded"], key=lambda item: (item["id"], item["predicate"])
    )
    assert body["removed"] == sorted(
        body["removed"], key=lambda item: (item["id"], item["predicate"])
    )


def test_create_snapshot_requires_as_of_and_only_captures_active() -> None:
    client, _ = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    pending = client.post(
        f"/projects/{project['id']}/canon-facts",
        headers=HUMAN,
        json={
            "entity_id": entity["id"],
            "predicate": "知道",
            "value_json": {"text": "残玉是钥匙"},
            "effective_story_time": "day-01",
            "valid_from_scene_id": SCENE_1,
            "source_type": "prose",
            "evidence_id": evidence["id"],
            "created_by": "主编",
        },
    )
    assert pending.status_code == 201
    active = _create_active_fact(client, project["id"], entity["id"], evidence["id"])

    missing = client.post(
        f"/projects/{project['id']}/canon-snapshots",
        headers=HUMAN,
        json={"created_by": "主编"},
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["error"] == "as_of_required"

    snapshot = _create_snapshot(client, project["id"], as_of_scene_seq=1)
    assert pending.json()["id"] not in snapshot["fact_ids"]
    assert snapshot["fact_ids"] == [active["id"]]


def test_snapshot_query_does_not_change_live_canon() -> None:
    client, sink = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    fact = _create_active_fact(client, project["id"], entity["id"], evidence["id"])
    snapshot = _create_snapshot(client, project["id"])
    client.get(f"/projects/{project['id']}/canon-snapshots/{snapshot['id']}/facts")
    client.get(
        f"/projects/{project['id']}/canon-replay",
        params={"snapshot_id": snapshot["id"], "as_of_story_time": "day-01"},
    )
    live = client.get(f"/projects/{project['id']}/canon-facts")
    assert [item["id"] for item in live.json()["facts"]] == [fact["id"]]
    assert live.json()["facts"][0]["status"] == "Active"
    assert not any(
        event.action.startswith("canon_fact.")
        and event.action != "canon_fact.create"
        and event.action != "canon_fact.approve"
        for event in sink.events
        if event.resource_type == "canon_fact"
        and event.action not in {"canon_fact.create", "canon_fact.approve"}
    )


def test_snapshot_migration_adds_columns_without_recreating_canon() -> None:
    versions = ROOT / "backend" / "alembic" / "versions"
    create = (versions / "003_create_canon_tables.py").read_text(encoding="utf-8")
    snapshot = (versions / "004_canon_snapshot_columns.py").read_text(encoding="utf-8")
    assert "CREATE TABLE canon_snapshots" in create
    assert "CREATE TABLE canon_facts" not in snapshot
    assert "CREATE TABLE entities" not in snapshot
    assert "ADD COLUMN fact_ids" in snapshot
    assert "ADD COLUMN frozen_at" in snapshot
    assert "ADD COLUMN as_of_scene_seq" in snapshot
    assert "ADD COLUMN as_of_story_time" in snapshot
    assert "ADD COLUMN status" in snapshot
    upgrade = snapshot.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    lowered_sql = upgrade.lower()
    assert "vector(" not in lowered_sql
    assert "embedding" not in lowered_sql
    assert "scene_card" not in lowered_sql
    assert "context_pack" not in lowered_sql


def test_canon_package_still_has_no_llm_or_vector_imports() -> None:
    canon_dir = ROOT / "backend" / "slove_context" / "canon"
    forbidden = (
        "openai",
        "anthropic",
        "langchain",
        "chromadb",
        "pgvector",
        "faiss",
        "numpy",
        "sentence_transformers",
    )
    for path in canon_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in text
            assert f"from {name}" not in text
