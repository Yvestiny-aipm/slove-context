"""Story Project / Story Spec APIs (node 2.1).

In-memory repository. No live Postgres. No model calls.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.story.repository import InMemoryStoryRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "主编"}
VALID_SPEC = {
    "title": "青石夜祠",
    "language": "zh-CN",
    "must_write": ["只写林晚在青石镇的七日"],
    "must_not_write": ["禁止第二主角视角"],
    "notes": "规格是编辑约束，不是 Canon。",
    "created_by": "主编",
}


def _client() -> tuple[TestClient, InMemoryAuditSink]:
    sink = InMemoryAuditSink()
    app = create_app(
        repository=InMemoryStoryRepository(),
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


def _create_draft(client: TestClient, project_id: str, payload: dict | None = None) -> dict:
    response = client.post(
        f"/projects/{project_id}/specs",
        headers=HUMAN,
        json=payload or VALID_SPEC,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_healthz_and_openapi_still_present() -> None:
    client, _ = _client()
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    version = client.get("/version")
    assert version.status_code == 200
    assert version.json().get("version")
    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    paths = openapi.json()["paths"]
    assert "/healthz" in paths
    assert "/version" in paths
    assert "/projects" in paths
    assert "/projects/{project_id}/specs" in paths
    assert "/projects/{project_id}/specs/{spec_id}/approve" in paths


def test_create_and_read_project() -> None:
    client, sink = _client()
    project = _create_project(client)
    assert project["status"] == "Active"
    assert project["language"] == "zh-CN"
    fetched = client.get(f"/projects/{project['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == project["id"]
    assert any(event.action == "story_project.create" for event in sink.events)


def test_second_project_is_rejected() -> None:
    client, _ = _client()
    _create_project(client)
    second = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": "另一部", "language": "zh-CN", "created_by": "主编"},
    )
    assert second.status_code == 409
    assert second.json()["detail"]["error"] == "second_project_not_supported"


def test_schema_validation_failure_is_rejected() -> None:
    client, sink = _client()
    project = _create_project(client)
    invalid = {
        **VALID_SPEC,
        "language": "en",
    }
    response = client.post(
        f"/projects/{project['id']}/specs",
        headers=HUMAN,
        json=invalid,
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "story_spec_schema_invalid"
    assert detail["errors"]
    assert not any(event.action == "story_spec.create_draft" for event in sink.events)


def test_create_read_submit_approve_and_list_versions() -> None:
    client, sink = _client()
    project = _create_project(client)
    created = _create_draft(client, project["id"])
    assert created["status"] == "Draft"
    assert created["spec"]["status"] == "Draft"
    spec_id = created["id"]

    current = client.get(f"/projects/{project['id']}/specs/current")
    assert current.status_code == 200
    assert current.json()["status"] == "Draft"

    submitted = client.post(
        f"/projects/{project['id']}/specs/{spec_id}/submit",
        headers=HUMAN,
        json={},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "Written"
    assert submitted.json()["spec"]["status"] == "Written"

    approved = client.post(
        f"/projects/{project['id']}/specs/{spec_id}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "Effective"
    assert approved.json()["spec"]["status"] == "Effective"

    versions = client.get(f"/projects/{project['id']}/specs/{spec_id}/versions")
    assert versions.status_code == 200
    body = versions.json()
    assert body["spec_id"] == spec_id
    assert len(body["versions"]) == 1
    assert body["versions"][0]["status"] == "Effective"
    assert body["versions"][0]["revision_number"] == 1

    actions = [event.action for event in sink.events]
    assert "story_spec.create_draft" in actions
    assert "story_spec.submit" in actions
    assert "story_spec.approve" in actions


def test_unapproved_spec_cannot_be_frozen_or_treated_as_approved() -> None:
    client, _ = _client()
    project = _create_project(client)
    created = _create_draft(client, project["id"])
    spec_id = created["id"]

    approve_draft = client.post(
        f"/projects/{project['id']}/specs/{spec_id}/approve",
        headers=HUMAN,
        json={},
    )
    assert approve_draft.status_code == 409
    assert approve_draft.json()["detail"]["error"] == "unapproved_spec_cannot_be_frozen"
    current = client.get(f"/projects/{project['id']}/specs/current")
    assert current.json()["status"] == "Draft"

    create_as_effective = client.post(
        f"/projects/{project['id']}/specs",
        headers=HUMAN,
        json={**VALID_SPEC, "status": "Effective"},
    )
    # First spec already exists; also reject treating create as approved.
    assert create_as_effective.status_code in {409, 422}

    client2, _ = _client()
    project2 = _create_project(client2)
    create_effective = client2.post(
        f"/projects/{project2['id']}/specs",
        headers=HUMAN,
        json={**VALID_SPEC, "status": "Effective"},
    )
    assert create_effective.status_code == 422
    assert create_effective.json()["detail"]["error"] == "unapproved_spec_cannot_be_frozen"
    missing = client2.get(f"/projects/{project2['id']}/specs/current")
    assert missing.status_code == 404


def test_non_human_actors_cannot_approve() -> None:
    client, sink = _client()
    project = _create_project(client)
    created = _create_draft(client, project["id"])
    spec_id = created["id"]
    submit = client.post(
        f"/projects/{project['id']}/specs/{spec_id}/submit",
        headers=HUMAN,
        json={},
    )
    assert submit.status_code == 200

    for actor_type in ("system", "generation_agent", "review_agent", "系统", "生成 Agent"):
        response = client.post(
            f"/projects/{project['id']}/specs/{spec_id}/approve",
            headers={"X-Actor-Type": actor_type, "X-Actor-Id": "bot"},
            json={},
        )
        assert response.status_code == 403, actor_type
        assert response.json()["detail"]["error"] == "human_editor_required"

    missing = client.post(
        f"/projects/{project['id']}/specs/{spec_id}/approve",
        json={},
    )
    assert missing.status_code == 403

    current = client.get(f"/projects/{project['id']}/specs/current")
    assert current.json()["status"] == "Written"
    assert not any(event.action == "story_spec.approve" for event in sink.events)


def test_patch_after_approval_is_rejected_and_new_draft_version_is_required() -> None:
    client, sink = _client()
    project = _create_project(client)
    created = _create_draft(client, project["id"])
    spec_id = created["id"]
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

    patched = client.patch(
        f"/projects/{project['id']}/specs/{spec_id}",
        headers=HUMAN,
        json={"title": "就地改写已批准规格"},
    )
    assert patched.status_code == 409
    assert patched.json()["detail"]["error"] == "approved_spec_immutable"

    still = client.get(f"/projects/{project['id']}/specs/current")
    assert still.json()["status"] == "Effective"
    assert still.json()["spec"]["title"] == "青石夜祠"

    next_draft = client.post(
        f"/projects/{project['id']}/specs/{spec_id}/drafts",
        headers=HUMAN,
        json={
            **VALID_SPEC,
            "title": "青石夜祠·修订",
            "must_write": ["只写林晚在青石镇的七日", "第一日得玉"],
        },
    )
    assert next_draft.status_code == 201
    body = next_draft.json()
    assert body["status"] == "Draft"
    assert body["revision_number"] == 2
    assert body["spec"]["status"] == "Draft"
    assert body["spec"]["title"] == "青石夜祠·修订"

    versions = client.get(f"/projects/{project['id']}/specs/{spec_id}/versions")
    numbers = [item["revision_number"] for item in versions.json()["versions"]]
    assert numbers == [1, 2]
    statuses = [item["status"] for item in versions.json()["versions"]]
    assert statuses == ["Effective", "Draft"]
    assert any(event.action == "story_spec.create_draft_revision" for event in sink.events)


def test_writes_are_audited_and_do_not_claim_canon() -> None:
    client, sink = _client()
    project = _create_project(client)
    created = _create_draft(client, project["id"])
    spec_id = created["id"]
    client.post(
        f"/projects/{project['id']}/specs/{spec_id}/submit",
        headers=HUMAN,
        json={},
    )
    client.post(
        f"/projects/{project['id']}/specs/{spec_id}/approve",
        headers=HUMAN,
        json={},
    )
    resource_types = {event.resource_type for event in sink.events}
    assert "story_project" in resource_types
    assert "story_spec" in resource_types
    assert "canon" not in resource_types
    assert "canon_fact" not in resource_types
    approve_events = [event for event in sink.events if event.action == "story_spec.approve"]
    assert approve_events
    assert approve_events[0].actor_type == "human_editor"
    assert approve_events[0].after_json is not None
    assert approve_events[0].after_json["status"] == "Effective"


def test_story_tables_migration_exists_without_canon() -> None:
    versions = ROOT / "backend" / "alembic" / "versions"
    files = list(versions.glob("*story_project*.py")) + list(
        versions.glob("*story_spec*.py")
    )
    assert files, "expected a reviewable story_projects / story_specs Alembic revision"
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "CREATE TABLE story_projects" in text
    assert "CREATE TABLE story_specs" in text
    assert "CREATE TABLE story_spec_versions" in text
    lowered = text.lower()
    assert "create table canon" not in lowered
    assert "create table canon_facts" not in lowered
    assert "create table canon_entities" not in lowered
    audit = (versions / "001_create_audit_events.py").read_text(encoding="utf-8")
    assert "CREATE TABLE audit_events" in audit
