"""Scene Card, in-story order, and dependencies (node 3.1).

In-memory repository. No live Postgres. No model calls.
No Scene Plan / Scene Draft generation and no model gateway.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.story.repository import InMemoryStoryRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}


def _client() -> tuple[TestClient, InMemoryAuditSink]:
    sink = InMemoryAuditSink()
    app = create_app(
        repository=InMemoryStoryRepository(),
        scene_repository=InMemorySceneRepository(),
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
    assert chapter.json()["is_generation_unit"] is False
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


def _approve(client: TestClient, project_id: str, scene_id: str):
    return client.post(
        f"/projects/{project_id}/scenes/{scene_id}/approve",
        headers=HUMAN,
        json={},
    )


def test_healthz_and_prior_apis_still_present() -> None:
    client, _ = _client()
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
    assert "/projects/{project_id}/scenes/generatable" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/generate" not in paths


def test_create_scene_records_required_fields_and_validates_card() -> None:
    client, sink = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"], 1)
    assert scene["status"] == "draft"
    assert scene["scene_status"] == "CardReady"
    assert scene["generatable"] is False
    assert scene["story_order"] == 1
    assert scene["pov"] == "林晚"
    assert scene["story_time"] == "第一日黄昏"
    assert scene["location"] == "青石镇河滩"
    assert scene["appearing_entities"] == ["林晚", "残玉"]
    assert scene["starting_state"]
    assert scene["goal"]
    assert scene["conflict"]
    assert scene["expected_end_state"]
    assert "禁止写出残玉来历" in scene["forbidden"]
    card = scene["scene_card"]
    assert card["status"] == "Written"
    assert card["scene_id"] == scene["id"]
    assert card["project_id"] == project["id"]
    listed = client.get(f"/projects/{project['id']}/scenes")
    assert listed.status_code == 200
    assert [item["story_order"] for item in listed.json()["scenes"]] == [1]
    assert any(event.action == "scene.create" for event in sink.events)
    assert not any(event.resource_type.startswith("canon") for event in sink.events)


def test_schema_validation_failure_is_rejected() -> None:
    client, sink = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    invalid = _scene_payload(chapter["id"], 1)
    del invalid["location"]
    invalid["present_entities"] = []
    response = client.post(
        f"/projects/{project['id']}/scenes",
        headers=HUMAN,
        json=invalid,
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "scene_card_schema_invalid"
    assert detail["errors"]
    assert not any(event.action == "scene.create" for event in sink.events)


def test_cannot_create_scene_as_approved() -> None:
    client, _ = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    response = client.post(
        f"/projects/{project['id']}/scenes",
        headers=HUMAN,
        json=_scene_payload(chapter["id"], 1, status="approved"),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "unapproved_scene_cannot_be_frozen"


def test_patch_draft_then_reject_after_approve() -> None:
    client, sink = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"], 1)
    patched = client.patch(
        f"/projects/{project['id']}/scenes/{scene['id']}",
        headers=HUMAN,
        json={
            "goal": "确认残玉在手",
            "forbidden_items": ["禁止写出残玉来历", "禁止第二视角"],
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["goal"] == "确认残玉在手"
    assert "禁止第二视角" in patched.json()["forbidden"]
    approved = _approve(client, project["id"], scene["id"])
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["generatable"] is True
    blocked = client.patch(
        f"/projects/{project['id']}/scenes/{scene['id']}",
        headers=HUMAN,
        json={"goal": "就地改写已批准场景卡"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error"] == "approved_scene_immutable"
    assert any(event.action == "scene.approve" for event in sink.events)
    assert not any("canon" in event.resource_type for event in sink.events)


def test_non_human_actors_cannot_approve_scene_card() -> None:
    client, sink = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"], 1)

    for actor_type in ("system", "generation_agent", "review_agent"):
        response = client.post(
            f"/projects/{project['id']}/scenes/{scene['id']}/approve",
            headers={"X-Actor-Type": actor_type, "X-Actor-Id": "bot"},
            json={},
        )
        assert response.status_code == 403, actor_type
        assert response.json()["detail"]["error"] == "human_editor_required"

    for actor_type in ("系统", "生成 Agent", "审校 Agent"):
        response = client.post(
            f"/projects/{project['id']}/scenes/{scene['id']}/approve",
            json={"actor_type": actor_type, "actor_id": "bot"},
        )
        assert response.status_code == 403, actor_type
        assert response.json()["detail"]["error"] == "human_editor_required"

    missing = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/approve",
        json={},
    )
    assert missing.status_code == 403
    current = client.get(f"/projects/{project['id']}/scenes/{scene['id']}")
    assert current.json()["status"] == "draft"
    assert not any(event.action == "scene.approve" for event in sink.events)


def test_dependency_blocking_prevents_generatable() -> None:
    client, _ = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    first = _create_scene(client, project["id"], chapter["id"], 1)
    second = _create_scene(
        client,
        project["id"],
        chapter["id"],
        2,
        story_time="第二日清晨",
        starting_state="林晚已持有残玉",
        goal="试祠门",
        location="青石镇祠堂",
        generation_boundary="只写林晚试门这一场，不写整章。",
    )
    deps = client.put(
        f"/projects/{project['id']}/scenes/{second['id']}/dependencies",
        headers=HUMAN,
        json={"depends_on": [first["id"]]},
    )
    assert deps.status_code == 200, deps.text
    assert deps.json()["generatable"] is False

    approved_second = _approve(client, project["id"], second["id"])
    assert approved_second.status_code == 200
    assert approved_second.json()["generatable"] is False
    listed = client.get(f"/projects/{project['id']}/scenes/{second['id']}/dependencies")
    assert listed.json()["generatable"] is False
    assert listed.json()["depends_on"][0]["satisfies"] is False
    generatable = client.get(f"/projects/{project['id']}/scenes/generatable")
    assert generatable.status_code == 200
    assert generatable.json()["scenes"] == []

    approved_first = _approve(client, project["id"], first["id"])
    assert approved_first.status_code == 200
    assert approved_first.json()["generatable"] is True
    ready = client.get(f"/projects/{project['id']}/scenes/{second['id']}")
    assert ready.json()["generatable"] is True
    generatable = client.get(f"/projects/{project['id']}/scenes/generatable")
    ids = {item["id"] for item in generatable.json()["scenes"]}
    assert ids == {first["id"], second["id"]}


def test_cycle_dependency_is_rejected() -> None:
    client, sink = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    first = _create_scene(client, project["id"], chapter["id"], 1)
    second = _create_scene(client, project["id"], chapter["id"], 2, story_time="第二日")
    ok = client.put(
        f"/projects/{project['id']}/scenes/{second['id']}/dependencies",
        headers=HUMAN,
        json={"depends_on": [first["id"]]},
    )
    assert ok.status_code == 200, ok.text
    cycle = client.put(
        f"/projects/{project['id']}/scenes/{first['id']}/dependencies",
        headers=HUMAN,
        json={"depends_on": [second["id"]]},
    )
    assert cycle.status_code == 409
    assert cycle.json()["detail"]["error"] == "cycle_dependency"
    self_cycle = client.put(
        f"/projects/{project['id']}/scenes/{first['id']}/dependencies",
        headers=HUMAN,
        json={"depends_on": [first["id"]]},
    )
    assert self_cycle.status_code == 409
    assert self_cycle.json()["detail"]["error"] == "cycle_dependency"
    current = client.get(f"/projects/{project['id']}/scenes/{first['id']}/dependencies")
    assert current.json()["depends_on"] == []
    assert not any(
        event.action == "scene.set_dependencies" and event.resource_id == first["id"]
        for event in sink.events
    )


def test_story_order_conflict_duplicate_and_before_dependency() -> None:
    client, _ = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    first = _create_scene(client, project["id"], chapter["id"], 1)
    duplicate = client.post(
        f"/projects/{project['id']}/scenes",
        headers=HUMAN,
        json=_scene_payload(chapter["id"], 1, goal="另一场"),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["error"] == "story_order_conflict"

    earlier = _create_scene(
        client, project["id"], chapter["id"], 3, story_time="第三日"
    )
    later = _create_scene(client, project["id"], chapter["id"], 4, story_time="第四日")
    before_dep = client.put(
        f"/projects/{project['id']}/scenes/{earlier['id']}/dependencies",
        headers=HUMAN,
        json={"depends_on": [later["id"]]},
    )
    assert before_dep.status_code == 409
    assert before_dep.json()["detail"]["error"] == "story_order_conflict"

    listed = client.get(f"/projects/{project['id']}/scenes")
    orders = [item["story_order"] for item in listed.json()["scenes"]]
    assert orders == [1, 3, 4]
    assert listed.json()["scenes"][0]["id"] == first["id"]


def test_arcs_and_chapters_are_not_generation_units() -> None:
    client, _ = _client()
    project = _create_project(client)
    arc = client.post(
        f"/projects/{project['id']}/arcs",
        headers=HUMAN,
        json={"title": "七日寻祠", "created_by": "主编"},
    )
    assert arc.status_code == 201
    assert arc.json()["is_generation_unit"] is False
    generate = client.post(f"/projects/{project['id']}/chapters/generate", json={})
    assert generate.status_code == 404


def test_scene_tables_migration_exists_without_recreating_canon() -> None:
    versions = ROOT / "backend" / "alembic" / "versions"
    files = list(versions.glob("*scene*"))
    assert files, "expected a reviewable arcs / scenes Alembic revision"
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "CREATE TABLE arcs" in text
    assert "CREATE TABLE chapters" in text
    assert "CREATE TABLE scenes" in text
    assert "CREATE TABLE scene_dependencies" in text
    assert "CREATE TABLE story_projects" not in text
    assert "CREATE TABLE canon_facts" not in text
    assert "CREATE TABLE entities" not in text
    assert "scene_plans" not in text
    assert "scene_drafts" not in text
    assert "model_gateway" not in text


def test_scene_package_has_no_llm_or_gateway() -> None:
    scene_dir = ROOT / "backend" / "slove_context" / "scene"
    forbidden = (
        "openai",
        "anthropic",
        "langchain",
        "chromadb",
        "pgvector",
        "faiss",
        "httpx",
    )
    for path in scene_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in text
            assert f"from {name}" not in text
        assert "def generate" not in text
