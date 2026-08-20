"""Local book snapshot (node P.1).

In-process restart only. No live Demo / no 127.0.0.1 HTTP.
No live Postgres. No real model. Persist does not approve or write Canon.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.demo.seed import seed_demo
from slove_context.story.repository import InMemoryStoryRepository

HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}

DRAFT_BODY = (
    "河滩风冷，林晚看见一点光，伸手拾起残玉。"
    "她把玉握在掌心，没有追问来历，只记住这一夜的潮声。"
    "风从芦苇里穿过，她把残玉收进袖中，继续沿河走下去。"
)
EVIDENCE_QUOTE = "伸手拾起残玉"
HARD_FACTS = (
    ("林晚", "持有", "残玉"),
    ("残玉", "所在", "青石镇河滩"),
    ("夜祠", "状态", "未开"),
    ("青石镇", "规则", "夜祠不可擅入"),
)


def _client(path: Path) -> TestClient:
    return TestClient(create_app(persist_path=path))


def _create_project(client: TestClient, *, title: str = "进口残卷") -> dict:
    response = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": title, "language": "zh-CN", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_spec(client: TestClient, project_id: str) -> dict:
    created = client.post(
        f"/projects/{project_id}/specs",
        headers=HUMAN,
        json={
            "title": "进口残卷",
            "language": "zh-CN",
            "must_write": ["只写林晚在青石镇的七日"],
            "must_not_write": ["禁止第二主角视角"],
            "created_by": "主编",
        },
    )
    assert created.status_code == 201, created.text
    spec = created.json()
    submitted = client.post(
        f"/projects/{project_id}/specs/{spec['id']}/submit",
        headers=HUMAN,
        json={},
    )
    assert submitted.status_code == 200, submitted.text
    approved = client.post(
        f"/projects/{project_id}/specs/{spec['id']}/approve",
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
    approved = client.post(
        f"/projects/{project_id}/scenes/{response.json()['id']}/approve",
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


def _create_plan(
    client: TestClient, project_id: str, scene_id: str, snapshot_id: str
) -> dict:
    created = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot_id},
    )
    assert created.status_code == 201, created.text
    current = client.get(f"/projects/{project_id}/scenes/{scene_id}/plans/current")
    assert current.status_code == 200, current.text
    return current.json()["plan"]


def _import_draft(
    client: TestClient, project_id: str, scene_id: str, snapshot_id: str
) -> dict:
    created = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/shuttle/drafts",
        headers=HUMAN,
        json={"body": DRAFT_BODY, "snapshot_id": snapshot_id},
    )
    assert created.status_code == 201, created.text
    return created.json()["draft"]


def _import_candidate(
    client: TestClient, project_id: str, scene_id: str, draft_id: str
) -> dict:
    imported = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/drafts/{draft_id}/shuttle/extracts",
        headers=HUMAN,
        json={
            "candidates": [
                {
                    "subject": "林晚",
                    "predicate": "持有",
                    "object": "残玉",
                    "value": "残玉",
                    "effective_story_time": "第一日黄昏",
                    "evidence_quote": EVIDENCE_QUOTE,
                    "confidence": 0.9,
                }
            ]
        },
    )
    assert imported.status_code == 201, imported.text
    return imported.json()["items"][0]


def _approve_four_facts(
    client: TestClient, project_id: str, scene_id: str
) -> list[str]:
    fact_ids: list[str] = []
    for name, predicate, value in HARD_FACTS:
        entity = client.post(
            f"/projects/{project_id}/entities",
            headers=HUMAN,
            json={"name": name, "entity_type": "角色", "created_by": "主编"},
        )
        assert entity.status_code == 201, entity.text
        evidence = client.post(
            f"/projects/{project_id}/evidence",
            headers=HUMAN,
            json={
                "source_type": "editor",
                "quote": f"{name}{predicate}{value}",
                "scene_id": scene_id,
                "created_by": "主编",
            },
        )
        assert evidence.status_code == 201, evidence.text
        fact = client.post(
            f"/projects/{project_id}/canon-facts",
            headers=HUMAN,
            json={
                "entity_id": entity.json()["id"],
                "predicate": predicate,
                "value_json": {"text": value},
                "effective_story_time": "day-01",
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
        assert approved.json()["status"] == "Active"
        fact_ids.append(approved.json()["id"])
    return fact_ids


def _write_imported_book(client: TestClient) -> dict[str, object]:
    project = _create_project(client)
    _create_spec(client, project["id"])
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"])
    snapshot = _create_snapshot(client, project["id"])
    _create_plan(client, project["id"], scene["id"], snapshot["id"])
    draft = _import_draft(client, project["id"], scene["id"], snapshot["id"])
    candidate = _import_candidate(client, project["id"], scene["id"], draft["id"])
    fact_ids = _approve_four_facts(client, project["id"], scene["id"])
    facts_before = client.get(f"/projects/{project['id']}/canon-facts").json()["facts"]
    return {
        "project_id": project["id"],
        "project_title": project["title"],
        "chapter_id": chapter["id"],
        "scene_id": scene["id"],
        "draft_id": draft["id"],
        "draft_body": draft["body"],
        "candidate_id": candidate["id"],
        "candidate_status": candidate["status"],
        "fact_ids": fact_ids,
        "fact_count": len(facts_before),
    }


def test_pytest_create_app_does_not_auto_persist() -> None:
    app = create_app()
    assert app.state.persist_path is None
    assert app.state.book_store is None


def test_injected_repositories_stay_unpersisted(tmp_path: Path) -> None:
    leftover = tmp_path / "book.json"
    leftover.write_text("this-should-not-be-loaded", encoding="utf-8")
    app = create_app(repository=InMemoryStoryRepository())
    assert app.state.persist_path is None
    client = TestClient(app)
    assert client.get("/projects").json()["items"] == []


def test_empty_dir_starts_empty_then_reload_after_save(tmp_path: Path) -> None:
    first = _client(tmp_path)
    assert first.get("/projects").json()["items"] == []
    assert not (tmp_path / "book.json").exists()

    created = _create_project(first, title="空目录后写入")
    assert (tmp_path / "book.json").is_file()

    second = _client(tmp_path)
    items = second.get("/projects").json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == created["id"]
    assert items[0]["title"] == "空目录后写入"

    third = _client(tmp_path)
    again = third.get("/projects").json()["items"]
    assert len(again) == 1
    assert again[0]["id"] == created["id"]


def test_restart_keeps_book_draft_facts_and_hanging_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "should-never-be-persisted")
    first = _client(tmp_path)
    saved = _write_imported_book(first)
    snapshot_text = (tmp_path / "book.json").read_text(encoding="utf-8")
    assert "should-never-be-persisted" not in snapshot_text
    assert "DEEPSEEK_API_KEY" not in snapshot_text
    payload = json.loads(snapshot_text)
    assert payload["version"] == 1
    assert saved["project_id"] in payload["story"]["projects"]

    first.close()
    restarted = _client(tmp_path)
    project_id = str(saved["project_id"])
    scene_id = str(saved["scene_id"])

    projects = restarted.get("/projects").json()["items"]
    assert len(projects) == 1
    assert projects[0]["id"] == project_id
    assert projects[0]["title"] == saved["project_title"]

    scenes = restarted.get(f"/projects/{project_id}/scenes").json()["scenes"]
    assert len(scenes) == 1
    assert scenes[0]["id"] == scene_id
    assert scenes[0]["chapter_id"] == saved["chapter_id"]
    assert saved["chapter_id"] in restarted.app.state.scene_repository.chapters

    drafts = restarted.get(f"/projects/{project_id}/scenes/{scene_id}/drafts")
    assert drafts.status_code == 200, drafts.text
    draft_items = drafts.json()["items"]
    assert draft_items
    latest = draft_items[0]
    assert latest["id"] == saved["draft_id"]
    assert latest["body"] == DRAFT_BODY
    assert latest["body"] == saved["draft_body"]

    facts = restarted.get(f"/projects/{project_id}/canon-facts").json()["facts"]
    assert len(facts) == 4
    assert {item["id"] for item in facts} == set(saved["fact_ids"])
    assert all(item["status"] == "Active" for item in facts)
    assert all(item["status"] != "Extracted" for item in facts)

    candidates = restarted.get(
        f"/projects/{project_id}/scenes/{scene_id}/candidate-changes"
    ).json()["items"]
    assert len(candidates) == 1
    hanging = candidates[0]
    assert hanging["id"] == saved["candidate_id"]
    assert hanging["status"] == "Extracted"
    assert hanging["status"] == saved["candidate_status"]
    assert hanging["is_canon"] is False
    assert hanging["is_canon_fact"] is False
    assert hanging["submitted_canon_fact_id"] is None
    fact_ids = {item["id"] for item in facts}
    assert hanging["id"] not in fact_ids


def test_seed_demo_does_not_overwrite_saved_imported_book(tmp_path: Path) -> None:
    first = _client(tmp_path)
    saved = _write_imported_book(first)
    first.close()

    second_app = create_app(persist_path=tmp_path)
    result = seed_demo(second_app)
    assert result.get("already_seeded") is True
    assert result["project_id"] == saved["project_id"]

    client = TestClient(second_app)
    project = client.get("/projects").json()["items"][0]
    assert project["title"] == "进口残卷"
    assert project["title"] != "青石夜祠（Demo）"
    facts = client.get(f"/projects/{project['id']}/canon-facts").json()["facts"]
    assert len(facts) == 4
    scene_id = str(saved["scene_id"])
    drafts = client.get(f"/projects/{project['id']}/scenes/{scene_id}/drafts")
    assert drafts.json()["items"][0]["body"] == DRAFT_BODY
    candidates = client.get(
        f"/projects/{project['id']}/scenes/{scene_id}/candidate-changes"
    ).json()["items"]
    assert candidates[0]["status"] == "Extracted"


def test_persist_path_false_disables_file(tmp_path: Path) -> None:
    app = create_app(persist_path=False)
    assert app.state.persist_path is None
    client = TestClient(app)
    _create_project(client, title="不落盘")
    assert list(tmp_path.iterdir()) == []
