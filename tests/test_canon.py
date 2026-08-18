"""Canon entities / evidence / facts API (node 2.2).

In-memory repository. No live Postgres. No model calls.
No snapshot freeze / replay (node 2.3).
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
SCENE_ID = "33333333-3333-4333-8333-333333333333"


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
    source_type: str = "prose",
    quote: str = "她把残玉按进缺口，门轴轻响",
) -> dict:
    response = client.post(
        f"/projects/{project_id}/evidence",
        headers=HUMAN,
        json={
            "source_type": source_type,
            "quote": quote,
            "scene_id": SCENE_ID,
            "created_by": "主编",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _fact_payload(entity_id: str, evidence_id: str, **overrides: object) -> dict:
    payload = {
        "entity_id": entity_id,
        "predicate": "左腕有",
        "value_json": {"text": "烧痕"},
        "effective_story_time": "day-01",
        "valid_from_scene_id": SCENE_ID,
        "source_type": "prose",
        "evidence_id": evidence_id,
        "created_by": "主编",
    }
    payload.update(overrides)
    return payload


def _create_fact(
    client: TestClient,
    project_id: str,
    entity_id: str,
    evidence_id: str,
    **overrides: object,
) -> dict:
    response = client.post(
        f"/projects/{project_id}/canon-facts",
        headers=HUMAN,
        json=_fact_payload(entity_id, evidence_id, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_healthz_version_and_21_apis_still_present() -> None:
    client, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/version").json().get("version")
    paths = client.get("/openapi.json").json()["paths"]
    assert "/healthz" in paths
    assert "/version" in paths
    assert "/projects" in paths
    assert "/projects/{project_id}/specs/{spec_id}/approve" in paths
    assert "/projects/{project_id}/entities" in paths
    assert "/projects/{project_id}/evidence" in paths
    assert "/projects/{project_id}/canon-facts" in paths
    assert "/projects/{project_id}/canon-facts/{fact_id}/approve" in paths
    assert "/projects/{project_id}/canon-facts/{fact_id}/abandon" in paths
    assert "/projects/{project_id}/canon-facts/{fact_id}/supersede" in paths
    assert "/projects/{project_id}/canon-snapshots" not in paths
    assert not any("replay" in path or "freeze" in path for path in paths)


def test_create_and_list_generic_entities() -> None:
    client, sink = _client()
    project = _create_project(client)
    created = _create_entity(client, project["id"])
    assert created["entity_type"] == "character"
    assert created["name"] == "林晚"
    listed = client.get(f"/projects/{project['id']}/entities")
    assert listed.status_code == 200
    body = listed.json()
    assert body["project_id"] == project["id"]
    assert len(body["entities"]) == 1
    assert body["entities"][0]["id"] == created["id"]
    assert any(event.action == "entity.create" for event in sink.events)


def test_invalid_entity_type_is_rejected() -> None:
    client, _ = _client()
    project = _create_project(client)
    response = client.post(
        f"/projects/{project['id']}/entities",
        headers=HUMAN,
        json={"name": "林晚", "entity_type": "protagonist_sheet", "created_by": "主编"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "invalid_entity_type"


def test_create_evidence_is_not_canon() -> None:
    client, sink = _client()
    project = _create_project(client)
    evidence = _create_evidence(client, project["id"])
    assert evidence["source_type"] == "prose"
    assert evidence["quote"]
    listed = client.get(f"/projects/{project['id']}/canon-facts")
    assert listed.status_code == 200
    assert listed.json()["facts"] == []
    events = [event for event in sink.events if event.action == "evidence.create"]
    assert events
    assert events[0].after_json is not None
    assert "quote" not in events[0].after_json
    dumped = str(events[0].after_json)
    assert "残玉" not in dumped


def test_create_fact_is_not_in_canon_and_does_not_activate() -> None:
    client, sink = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    fact = _create_fact(client, project["id"], entity["id"], evidence["id"])
    assert fact["status"] == "NotInCanon"
    assert fact["predicate"] == "左腕有"
    assert fact["value_json"] == {"text": "烧痕"}
    assert fact["effective_story_time"] == "day-01"
    assert fact["valid_from_scene_id"] == SCENE_ID
    assert fact["source_type"] == "prose"
    assert fact["evidence_id"] == evidence["id"]
    listed = client.get(f"/projects/{project['id']}/canon-facts")
    assert listed.json()["facts"] == []
    assert any(event.action == "canon_fact.create" for event in sink.events)


def test_create_fact_as_active_is_rejected() -> None:
    client, sink = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    response = client.post(
        f"/projects/{project['id']}/canon-facts",
        headers=HUMAN,
        json=_fact_payload(entity["id"], evidence["id"], status="Active"),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "unapproved_fact_cannot_be_activated"
    assert not any(event.action == "canon_fact.create" for event in sink.events)


def test_missing_fact_fields_are_rejected() -> None:
    client, _ = _client()
    project = _create_project(client)
    response = client.post(
        f"/projects/{project['id']}/canon-facts",
        headers=HUMAN,
        json={"predicate": "左腕有", "created_by": "主编"},
    )
    assert response.status_code == 422


def test_human_approve_activates_and_writes_audit() -> None:
    client, sink = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    fact = _create_fact(client, project["id"], entity["id"], evidence["id"])
    approved = client.post(
        f"/projects/{project['id']}/canon-facts/{fact['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "Active"
    assert body["value_json"] == {"text": "烧痕"}
    listed = client.get(f"/projects/{project['id']}/canon-facts")
    assert len(listed.json()["facts"]) == 1
    assert listed.json()["facts"][0]["id"] == fact["id"]
    events = [event for event in sink.events if event.action == "canon_fact.approve"]
    assert events
    assert events[0].actor_type == "human_editor"
    assert events[0].after_json is not None
    assert events[0].after_json["status"] == "Active"


def test_non_human_actors_cannot_approve_or_abandon() -> None:
    client, sink = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    fact = _create_fact(client, project["id"], entity["id"], evidence["id"])

    for actor_type in ("system", "generation_agent", "review_agent"):
        response = client.post(
            f"/projects/{project['id']}/canon-facts/{fact['id']}/approve",
            headers={"X-Actor-Type": actor_type, "X-Actor-Id": "bot"},
            json={},
        )
        assert response.status_code == 403, actor_type
        assert response.json()["detail"]["error"] == "human_editor_required"

    missing = client.post(
        f"/projects/{project['id']}/canon-facts/{fact['id']}/approve",
        json={},
    )
    assert missing.status_code == 403

    abandon = client.post(
        f"/projects/{project['id']}/canon-facts/{fact['id']}/abandon",
        headers={"X-Actor-Type": "system", "X-Actor-Id": "bot"},
        json={},
    )
    assert abandon.status_code == 403

    current = client.get(f"/projects/{project['id']}/canon-facts")
    assert current.json()["facts"] == []
    assert not any(
        event.action in {"canon_fact.approve", "canon_fact.abandon"}
        for event in sink.events
    )


def test_abandon_not_yet_active_writes_audit() -> None:
    client, sink = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    fact = _create_fact(client, project["id"], entity["id"], evidence["id"])
    abandoned = client.post(
        f"/projects/{project['id']}/canon-facts/{fact['id']}/abandon",
        headers=HUMAN,
        json={},
    )
    assert abandoned.status_code == 200
    assert abandoned.json()["status"] == "Abandoned"
    listed = client.get(f"/projects/{project['id']}/canon-facts")
    assert listed.json()["facts"] == []
    events = [event for event in sink.events if event.action == "canon_fact.abandon"]
    assert events
    assert events[0].actor_type == "human_editor"
    assert events[0].after_json is not None
    assert events[0].after_json["status"] == "Abandoned"


def test_active_fact_cannot_be_abandoned() -> None:
    client, _ = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    fact = _create_fact(client, project["id"], entity["id"], evidence["id"])
    client.post(
        f"/projects/{project['id']}/canon-facts/{fact['id']}/approve",
        headers=HUMAN,
        json={},
    )
    response = client.post(
        f"/projects/{project['id']}/canon-facts/{fact['id']}/abandon",
        headers=HUMAN,
        json={},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "active_fact_cannot_be_abandoned"


def test_query_facts_in_effect_by_entity_predicate_and_story_time() -> None:
    client, _ = _client()
    project = _create_project(client)
    lin = _create_entity(client, project["id"], name="林晚", entity_type="角色")
    jade = _create_entity(client, project["id"], name="残玉", entity_type="物品")
    evidence = _create_evidence(client, project["id"])

    burn = _create_fact(
        client,
        project["id"],
        lin["id"],
        evidence["id"],
        predicate="左腕有",
        value_json={"text": "烧痕"},
        effective_story_time="day-01",
    )
    opens = _create_fact(
        client,
        project["id"],
        jade["id"],
        evidence["id"],
        predicate="可开启",
        value_json={"object": "祠门"},
        effective_story_time="day-03",
    )
    pending = _create_fact(
        client,
        project["id"],
        lin["id"],
        evidence["id"],
        predicate="知道",
        value_json={"text": "残玉是钥匙"},
        effective_story_time="day-02",
    )
    for fact_id in (burn["id"], opens["id"]):
        approved = client.post(
            f"/projects/{project['id']}/canon-facts/{fact_id}/approve",
            headers=HUMAN,
            json={},
        )
        assert approved.status_code == 200

    all_active = client.get(f"/projects/{project['id']}/canon-facts")
    ids = {item["id"] for item in all_active.json()["facts"]}
    assert ids == {burn["id"], opens["id"]}
    assert pending["id"] not in ids

    by_entity = client.get(
        f"/projects/{project['id']}/canon-facts",
        params={"entity_id": lin["id"]},
    )
    assert [item["id"] for item in by_entity.json()["facts"]] == [burn["id"]]

    by_predicate = client.get(
        f"/projects/{project['id']}/canon-facts",
        params={"predicate": "可开启"},
    )
    assert [item["id"] for item in by_predicate.json()["facts"]] == [opens["id"]]

    as_of_day_02 = client.get(
        f"/projects/{project['id']}/canon-facts",
        params={"as_of_story_time": "day-02"},
    )
    assert [item["id"] for item in as_of_day_02.json()["facts"]] == [burn["id"]]

    as_of_day_03 = client.get(
        f"/projects/{project['id']}/canon-facts",
        params={"as_of_story_time": "day-03"},
    )
    assert {item["id"] for item in as_of_day_03.json()["facts"]} == {
        burn["id"],
        opens["id"],
    }


def test_supersede_is_append_only_and_creates_new_version() -> None:
    client, sink = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    later = _create_evidence(
        client, project["id"], source_type="editor", quote="主编改判：左腕无烧痕"
    )
    fact = _create_fact(client, project["id"], entity["id"], evidence["id"])
    approved = client.post(
        f"/projects/{project['id']}/canon-facts/{fact['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200
    old_value = approved.json()["value_json"]
    old_version = approved.json()["current_version_id"]

    superseded = client.post(
        f"/projects/{project['id']}/canon-facts/{fact['id']}/supersede",
        headers=HUMAN,
        json=_fact_payload(
            entity["id"],
            later["id"],
            predicate="左腕有",
            value_json={"text": "无烧痕"},
            effective_story_time="day-02",
            source_type="editor",
        ),
    )
    assert superseded.status_code == 200, superseded.text
    body = superseded.json()
    assert body["superseded"]["id"] == fact["id"]
    assert body["superseded"]["status"] == "Superseded"
    assert body["superseded"]["value_json"] == old_value
    assert body["superseded"]["current_version_id"] == old_version
    assert body["fact"]["status"] == "Active"
    assert body["fact"]["value_json"] == {"text": "无烧痕"}
    assert body["fact"]["id"] != fact["id"]
    assert body["fact"]["supersedes_fact_id"] == fact["id"]
    assert body["fact"]["current_version_id"] != old_version
    assert body["superseded"]["superseded_by_fact_id"] == body["fact"]["id"]

    listed = client.get(f"/projects/{project['id']}/canon-facts")
    facts = listed.json()["facts"]
    assert len(facts) == 1
    assert facts[0]["id"] == body["fact"]["id"]
    assert facts[0]["status"] == "Active"

    repo = client.app.state.canon_repository
    stored_old = repo.get_fact(fact["id"])
    stored_new = repo.get_fact(body["fact"]["id"])
    assert stored_old is not None
    assert stored_new is not None
    assert stored_old.value_json == {"text": "烧痕"}
    assert stored_old.status == "Superseded"
    assert len(stored_old.versions) == 1
    assert stored_old.versions[0].value_json == {"text": "烧痕"}
    assert len(stored_new.versions) == 1
    assert stored_new.versions[0].value_json == {"text": "无烧痕"}
    assert stored_new.versions[0].revision_number == 1

    actions = [event.action for event in sink.events]
    assert "canon_fact.supersede" in actions
    assert actions.count("canon_fact.create") == 2


def test_non_human_cannot_supersede() -> None:
    client, _ = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    fact = _create_fact(client, project["id"], entity["id"], evidence["id"])
    client.post(
        f"/projects/{project['id']}/canon-facts/{fact['id']}/approve",
        headers=HUMAN,
        json={},
    )
    response = client.post(
        f"/projects/{project['id']}/canon-facts/{fact['id']}/supersede",
        headers={"X-Actor-Type": "generation_agent", "X-Actor-Id": "bot"},
        json=_fact_payload(entity["id"], evidence["id"], value_json={"text": "改"}),
    )
    assert response.status_code == 403
    listed = client.get(f"/projects/{project['id']}/canon-facts")
    assert listed.json()["facts"][0]["value_json"] == {"text": "烧痕"}


def test_patch_of_canon_fact_is_not_offered() -> None:
    client, _ = _client()
    project = _create_project(client)
    entity = _create_entity(client, project["id"])
    evidence = _create_evidence(client, project["id"])
    fact = _create_fact(client, project["id"], entity["id"], evidence["id"])
    client.post(
        f"/projects/{project['id']}/canon-facts/{fact['id']}/approve",
        headers=HUMAN,
        json={},
    )
    patched = client.patch(
        f"/projects/{project['id']}/canon-facts/{fact['id']}",
        headers=HUMAN,
        json={"value_json": {"text": "就地改写"}},
    )
    assert patched.status_code == 405
    listed = client.get(f"/projects/{project['id']}/canon-facts")
    assert listed.json()["facts"][0]["value_json"] == {"text": "烧痕"}


def test_story_spec_approve_is_unchanged() -> None:
    client, sink = _client()
    project = _create_project(client)
    spec = client.post(
        f"/projects/{project['id']}/specs",
        headers=HUMAN,
        json={
            "title": "青石夜祠",
            "language": "zh-CN",
            "must_write": ["只写林晚在青石镇的七日"],
            "must_not_write": ["禁止第二主角视角"],
            "created_by": "主编",
        },
    )
    assert spec.status_code == 201
    spec_id = spec.json()["id"]
    client.post(
        f"/projects/{project['id']}/specs/{spec_id}/submit",
        headers=HUMAN,
        json={},
    )
    approved = client.post(
        f"/projects/{project['id']}/specs/{spec_id}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "Effective"
    assert any(event.action == "story_spec.approve" for event in sink.events)
    listed = client.get(f"/projects/{project['id']}/canon-facts")
    assert listed.json()["facts"] == []


def test_canon_tables_migration_exists_without_replay_or_vector() -> None:
    versions = ROOT / "backend" / "alembic" / "versions"
    files = list(versions.glob("*canon*.py"))
    assert files, "expected a reviewable Canon Alembic revision"
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for table in (
        "CREATE TABLE entities",
        "CREATE TABLE canon_facts",
        "CREATE TABLE canon_fact_versions",
        "CREATE TABLE evidence_records",
        "CREATE TABLE canon_snapshots",
    ):
        assert table in text, table
    lowered = text.lower()
    assert "vector" not in lowered
    assert "embedding" not in lowered
    assert "replay" not in lowered
    assert "freeze" not in lowered or "node 2.3" in text.lower()
    audit = (versions / "001_create_audit_events.py").read_text(encoding="utf-8")
    assert "CREATE TABLE audit_events" in audit


def test_canon_package_has_no_llm_or_vector_imports() -> None:
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
