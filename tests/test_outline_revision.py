"""Outline Revision (node 6.2).

In-memory repositories. No live Postgres. No network. No real models.
Draft / propose / confirm-usable. Confirm is not Canon approval.
Confirmed cannot be edited in place. Fail / cancel keep records.
Outline is not a generation unit: no chapter- or book-level generate.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.canon.models import FACT_ACTIVE
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.outline.repository import InMemoryOutlineRepository
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.story.repository import InMemoryStoryRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}
REVIEW = {"X-Actor-Type": "review_agent", "X-Actor-Id": "rev-1"}
SYSTEM = {"X-Actor-Type": "system", "X-Actor-Id": "sys-1"}


def _client() -> tuple[
    TestClient,
    InMemoryAuditSink,
    InMemoryCanonRepository,
    InMemoryOutlineRepository,
]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    canon = InMemoryCanonRepository()
    outlines = InMemoryOutlineRepository()
    app = create_app(
        repository=InMemoryStoryRepository(),
        canon_repository=canon,
        scene_repository=InMemorySceneRepository(),
        outline_repository=outlines,
        audit_writer=writer,
        llm_gateway=LlmGateway(
            FakeProvider(),
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
    )
    return TestClient(app), sink, canon, outlines


def _create_project(client: TestClient) -> dict:
    response = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": "青石夜祠", "language": "zh-CN", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_structure(client: TestClient, project_id: str) -> tuple[dict, dict, dict]:
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
    return arc.json(), chapter.json(), scene.json()


def _nodes(arc: dict, chapter: dict, scene: dict) -> list[dict]:
    return [
        {
            "node_type": "arc",
            "title": "七日寻祠",
            "arc_id": arc["id"],
            "sort_order": 1,
            "goal": "七日之内寻到夜祠",
            "conflict": "残玉尚未显灵",
            "turning_point": "第一日拾玉",
            "start_state": "林晚空手入镇",
            "end_state": "林晚持玉立于祠外",
            "constraints": ["禁止第二主角视角"],
            "children": [
                {
                    "node_type": "chapter",
                    "title": "得玉",
                    "chapter_id": chapter["id"],
                    "arc_id": arc["id"],
                    "sort_order": 1,
                    "goal": "得残玉",
                    "conflict": "夜色将至",
                    "turning_point": "河滩见光",
                    "start_state": "空手走河滩",
                    "end_state": "持有残玉",
                    "constraints": ["不写整章散文"],
                    "children": [
                        {
                            "node_type": "scene",
                            "title": "河边拾玉",
                            "scene_id": scene["id"],
                            "chapter_id": chapter["id"],
                            "sort_order": 1,
                            "goal": "拾得残玉",
                            "conflict": "河风几乎让她错过",
                            "turning_point": "泥里露出同形缺口",
                            "start_state": "林晚空手走在河滩",
                            "end_state": "林晚持有残玉",
                            "constraints": ["禁止写出残玉来历"],
                        }
                    ],
                }
            ],
        }
    ]


def _create_draft(
    client: TestClient, project_id: str, nodes: list[dict] | None = None
) -> dict:
    response = client.post(
        f"/projects/{project_id}/outline-revisions",
        headers=HUMAN,
        json={"nodes": nodes or [], "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _ready(client: TestClient) -> tuple[dict, dict, dict, dict, dict]:
    project = _create_project(client)
    arc, chapter, scene = _create_structure(client, project["id"])
    draft = _create_draft(client, project["id"], _nodes(arc, chapter, scene))
    return project, arc, chapter, scene, draft


def _canon_fact_count(canon: InMemoryCanonRepository, project_id: str) -> int:
    return len([item for item in canon.facts.values() if item.project_id == project_id])


def _active_fact_count(canon: InMemoryCanonRepository, project_id: str) -> int:
    return len(
        [
            item
            for item in canon.facts.values()
            if item.project_id == project_id and item.status == FACT_ACTIVE
        ]
    )


def test_healthz_and_prior_apis_remain_no_chapter_generate() -> None:
    client, _, _, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/version").json().get("version")
    paths = client.get("/openapi.json").json()["paths"]
    assert "/healthz" in paths
    assert "/version" in paths
    assert "/projects/{project_id}/specs/{spec_id}/approve" in paths
    assert "/projects/{project_id}/canon-facts" in paths
    assert "/projects/{project_id}/canon-snapshots/{snapshot_id}/freeze" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/approve" in paths
    assert "/projects/{project_id}/validation-runs" in paths
    assert "/projects/{project_id}/repair-tasks" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/context-packs" in paths
    assert "/projects/{project_id}/outline-revisions" in paths
    assert "/projects/{project_id}/outline-revisions/{revision_id}" in paths
    assert "/projects/{project_id}/outline-revisions/{revision_id}/propose" in paths
    assert "/projects/{project_id}/outline-revisions/{revision_id}/confirm" in paths
    assert "/projects/{project_id}/outline-revisions/{revision_id}/revise" in paths
    assert "/projects/{project_id}/outline-revisions/{revision_id}/cancel" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/chapters/{chapter_id}/generate" not in paths
    assert "/projects/{project_id}/books/generate" not in paths
    assert "/projects/{project_id}/generate" not in paths
    assert "/projects/{project_id}/auto-approve" not in paths
    assert not any("seed-status" in path for path in paths)
    assert client.post("/projects/p/chapters/generate", json={}).status_code == 404
    assert client.post("/projects/p/chapters/c/generate", json={}).status_code == 404
    assert client.post("/projects/p/books/generate", json={}).status_code == 404


def test_draft_propose_confirm_usable_is_not_canon_approval() -> None:
    client, sink, canon, outlines = _client()
    project, _arc, _chapter, scene, draft = _ready(client)
    before = _canon_fact_count(canon, project["id"])
    assert draft["status"] == "Drafting"
    assert draft["is_generation_unit"] is False
    assert draft["writes_canon"] is False
    assert draft["is_approval"] is False
    assert draft["nodes"][0]["children"][0]["children"][0]["scene_id"] == scene["id"]

    proposed = client.post(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}/propose",
        headers=HUMAN,
        json={},
    )
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["status"] == "Proposed"

    confirmed = client.post(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}/confirm",
        headers=HUMAN,
        json={},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "Confirmed"
    assert body["confirm_usable"] is True
    assert body["current"] is True
    assert body["immutable"] is True
    assert body["is_approval"] is False
    assert body["is_canon_approval"] is False
    assert body["writes_canon"] is False
    assert body["is_canon"] is False
    assert body["auto_approved"] is False
    assert body["is_generation_unit"] is False
    assert _canon_fact_count(canon, project["id"]) == before
    assert _active_fact_count(canon, project["id"]) == 0
    assert outlines.get(draft["id"]) is not None
    actions = [event.action for event in sink.events]
    assert "outline_revision.create" in actions
    assert "outline_revision.propose" in actions
    assert "outline_revision.confirm" in actions
    assert "canon_fact.create" not in actions
    assert "canon_fact.approve" not in actions
    assert "candidate_change.approve" not in actions
    assert "candidate_change.submit" not in actions
    for event in sink.events:
        if event.resource_type == "outline_revision":
            assert event.after_json is not None
            assert "goal" not in event.after_json
            assert event.after_json.get("writes_canon") is False
            after = str(event.after_json)
            assert "api_key" not in after or "[REDACTED]" in after


def test_only_human_editor_can_confirm() -> None:
    client, _, canon, _ = _client()
    project, _arc, _chapter, _scene, draft = _ready(client)
    propose = client.post(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}/propose",
        headers=HUMAN,
        json={},
    )
    assert propose.status_code == 200, propose.text
    for headers in (SYSTEM, GENERATE, REVIEW):
        blocked = client.post(
            f"/projects/{project['id']}/outline-revisions/{draft['id']}/confirm",
            headers=headers,
            json={},
        )
        assert blocked.status_code == 403, blocked.text
        assert blocked.json()["detail"]["error"] == "human_editor_required"
        assert blocked.json()["detail"]["writes_canon"] is False
    still = client.get(f"/projects/{project['id']}/outline-revisions/{draft['id']}")
    assert still.json()["status"] == "Proposed"
    assert _canon_fact_count(canon, project["id"]) == 0


def test_confirmed_cannot_be_edited_in_place_revise_creates_new_id() -> None:
    client, sink, canon, outlines = _client()
    project, arc, chapter, scene, draft = _ready(client)
    client.post(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}/propose",
        headers=HUMAN,
        json={},
    )
    confirmed = client.post(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}/confirm",
        headers=HUMAN,
        json={},
    )
    assert confirmed.json()["status"] == "Confirmed"
    patched = client.patch(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}",
        headers=HUMAN,
        json={"nodes": _nodes(arc, chapter, scene)},
    )
    assert patched.status_code == 409, patched.text
    assert patched.json()["detail"]["error"] == "confirmed_not_editable_in_place"
    create_again = client.post(
        f"/projects/{project['id']}/outline-revisions",
        headers=HUMAN,
        json={"nodes": _nodes(arc, chapter, scene)},
    )
    assert create_again.status_code == 409

    revised = client.post(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}/revise",
        headers=HUMAN,
        json={},
    )
    assert revised.status_code == 200, revised.text
    body = revised.json()
    assert body["id"] != draft["id"]
    assert body["lineage_id"] == draft["lineage_id"]
    assert body["status"] == "Revising"
    assert body["parent_revision_id"] == draft["id"]
    assert body["revision"] == 2
    old = client.get(f"/projects/{project['id']}/outline-revisions/{draft['id']}")
    assert old.json()["status"] == "Confirmed"
    assert outlines.get(draft["id"]) is not None
    assert outlines.get(body["id"]) is not None

    proposed = client.post(
        f"/projects/{project['id']}/outline-revisions/{body['id']}/propose",
        headers=HUMAN,
        json={},
    )
    assert proposed.status_code == 200, proposed.text
    new_confirmed = client.post(
        f"/projects/{project['id']}/outline-revisions/{body['id']}/confirm",
        headers=HUMAN,
        json={},
    )
    assert new_confirmed.status_code == 200, new_confirmed.text
    assert new_confirmed.json()["status"] == "Confirmed"
    superseded = client.get(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}"
    )
    assert superseded.json()["status"] == "Superseded"
    assert superseded.json()["superseded_by_id"] == body["id"]
    assert superseded.json()["immutable"] is True
    listed = client.get(f"/projects/{project['id']}/outline-revisions")
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["items"]}
    assert draft["id"] in ids
    assert body["id"] in ids
    assert _canon_fact_count(canon, project["id"]) == 0
    assert "outline_revision.revise" in [event.action for event in sink.events]
    assert "outline_revision.supersede" in [event.action for event in sink.events]


def test_fail_and_cancel_keep_records() -> None:
    client, sink, canon, outlines = _client()
    project, arc, chapter, scene, draft = _ready(client)
    cancelled = client.post(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "Cancelled"
    still = client.get(f"/projects/{project['id']}/outline-revisions/{draft['id']}")
    assert still.status_code == 200
    assert still.json()["status"] == "Cancelled"
    assert outlines.get(draft["id"]) is not None

    reworked = client.post(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}/rework",
        headers=HUMAN,
        json={},
    )
    assert reworked.json()["status"] == "Rework"
    resumed = client.post(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}/resume",
        headers=HUMAN,
        json={},
    )
    assert resumed.json()["status"] == "Drafting"

    failed = client.post(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}/fail",
        headers=SYSTEM,
        json={"reason": "save_or_draft_failed"},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "Failed"
    assert failed.json()["failure_reason"] == "save_or_draft_failed"
    kept = client.get(f"/projects/{project['id']}/outline-revisions/{draft['id']}")
    assert kept.status_code == 200
    assert kept.json()["status"] == "Failed"
    assert outlines.get(draft["id"]) is not None
    assert _canon_fact_count(canon, project["id"]) == 0

    outlines.force_fail = True
    second = client.post(
        f"/projects/{project['id']}/outline-revisions",
        headers=HUMAN,
        json={"nodes": _nodes(arc, chapter, scene), "created_by": "主编"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["status"] == "Failed"
    assert outlines.get(second.json()["id"]) is not None
    actions = [event.action for event in sink.events]
    assert "outline_revision.cancel" in actions
    assert "outline_revision.failed" in actions
    assert "outline_revision.rework" in actions


def test_no_chapter_or_book_generate_and_no_extract() -> None:
    client, _, _, _ = _client()
    project, _arc, _chapter, scene, _draft = _ready(client)
    assert (
        client.post(f"/projects/{project['id']}/chapters/generate", json={}).status_code
        == 404
    )
    assert (
        client.post(
            f"/projects/{project['id']}/chapters/{scene['chapter_id']}/generate",
            json={},
        ).status_code
        == 404
    )
    assert (
        client.post(f"/projects/{project['id']}/books/generate", json={}).status_code
        == 404
    )
    assert (
        client.post(f"/projects/{project['id']}/generate", json={}).status_code == 404
    )
    assert (
        client.post(
            f"/projects/{project['id']}/outline-revisions/extract", json={}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/projects/{project['id']}/candidate-changes/seed-status", json={}
        ).status_code
        == 404
    )
    package = ROOT / "backend" / "slove_context" / "outline"
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in ("openai", "anthropic", "langchain", "chromadb", "pgvector"):
            assert f"import {name}" not in text
            assert f"from {name}" not in text
        assert "chapters/generate" not in text
        assert "books/generate" not in text
        assert "seed-status" not in text
        assert "auto_approve" not in text or "False" in text


def test_scene_nodes_must_reference_existing_scenes() -> None:
    client, _, _, _ = _client()
    project = _create_project(client)
    arc, chapter, _scene = _create_structure(client, project["id"])
    missing = client.post(
        f"/projects/{project['id']}/outline-revisions",
        headers=HUMAN,
        json={
            "nodes": [
                {
                    "node_type": "arc",
                    "title": "七日寻祠",
                    "goal": "寻祠",
                    "conflict": "未知",
                    "turning_point": "拾玉",
                    "start_state": "入镇",
                    "end_state": "到祠",
                    "constraints": ["仅中文"],
                    "children": [
                        {
                            "node_type": "chapter",
                            "title": "得玉",
                            "chapter_id": chapter["id"],
                            "goal": "得玉",
                            "conflict": "夜色",
                            "turning_point": "见光",
                            "start_state": "空手",
                            "end_state": "持玉",
                            "constraints": ["不写整章"],
                            "children": [
                                {
                                    "node_type": "scene",
                                    "title": "河边拾玉",
                                    "goal": "拾玉",
                                    "conflict": "河风",
                                    "turning_point": "缺口",
                                    "start_state": "空手",
                                    "end_state": "持玉",
                                    "constraints": ["禁止来历"],
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )
    assert missing.status_code == 422, missing.text
    assert missing.json()["detail"]["error"] == "scene_id_required"
    unknown = client.post(
        f"/projects/{project['id']}/outline-revisions",
        headers=HUMAN,
        json={
            "nodes": [
                {
                    "node_type": "arc",
                    "title": "七日寻祠",
                    "arc_id": arc["id"],
                    "goal": "寻祠",
                    "conflict": "未知",
                    "turning_point": "拾玉",
                    "start_state": "入镇",
                    "end_state": "到祠",
                    "constraints": ["仅中文"],
                    "children": [
                        {
                            "node_type": "chapter",
                            "title": "得玉",
                            "chapter_id": chapter["id"],
                            "goal": "得玉",
                            "conflict": "夜色",
                            "turning_point": "见光",
                            "start_state": "空手",
                            "end_state": "持玉",
                            "constraints": ["不写整章"],
                            "children": [
                                {
                                    "node_type": "scene",
                                    "title": "河边拾玉",
                                    "scene_id": "99999999-9999-4999-8999-999999999999",
                                    "goal": "拾玉",
                                    "conflict": "河风",
                                    "turning_point": "缺口",
                                    "start_state": "空手",
                                    "end_state": "持玉",
                                    "constraints": ["禁止来历"],
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )
    assert unknown.status_code == 422, unknown.text
    assert unknown.json()["detail"]["error"] == "scene_not_found"


def test_empty_draft_cannot_be_proposed() -> None:
    client, _, _, _ = _client()
    project = _create_project(client)
    draft = _create_draft(client, project["id"])
    proposed = client.post(
        f"/projects/{project['id']}/outline-revisions/{draft['id']}/propose",
        headers=HUMAN,
        json={},
    )
    assert proposed.status_code == 409
    assert proposed.json()["detail"]["error"] == "outline_not_written"


def test_migration_adds_outline_revisions_without_rebuilding_prior_tables() -> None:
    versions = ROOT / "backend" / "alembic" / "versions"
    create = (versions / "014_create_outline_revisions.py").read_text(encoding="utf-8")
    assert "CREATE TABLE outline_revisions" in create
    assert "CREATE TABLE context_packs" not in create
    assert "CREATE TABLE repair_tasks" not in create
    assert "CREATE TABLE validation_runs" not in create
    assert "CREATE TABLE scene_drafts" not in create
    assert "CREATE TABLE scenes" not in create
    assert 'down_revision: str | None = "013_context_packs"' in create
    assert "Drafting" in create
    assert "Confirmed" in create
    assert "Superseded" in create
    upgrade = create.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    lowered = upgrade.lower()
    assert "vector(" not in lowered
    assert "embedding" not in lowered
    assert "openai" not in lowered
    assert "chapters/generate" not in create
