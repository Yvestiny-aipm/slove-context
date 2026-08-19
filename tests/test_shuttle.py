"""Human shuttle (node UI.2).

Copy prompt out / paste result back. In-memory repositories.
No live Postgres. No network. No real model HTTP.
Shuttle import does not write Canon and does not approve.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.scene_plan.repository import InMemoryScenePlanRepository
from slove_context.story.repository import InMemoryStoryRepository

HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}
SYSTEM = {"X-Actor-Type": "system", "X-Actor-Id": "sys-1"}
SHUTTLE_PROSE = (
    "河滩风冷，林晚看见一点光，伸手拾起残玉。"
    "她把玉握在掌心，没有追问来历，只记住这一夜的潮声。"
    "风从芦苇里穿过，她把残玉收进袖中，继续沿河走下去。"
)
EVIDENCE_QUOTE = "伸手拾起残玉"


def _client() -> tuple[
    TestClient, InMemoryAuditSink, FakeProvider, InMemoryCanonRepository
]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    fake = FakeProvider()
    canon = InMemoryCanonRepository()
    app = create_app(
        repository=InMemoryStoryRepository(),
        canon_repository=canon,
        scene_repository=InMemorySceneRepository(),
        scene_plan_repository=InMemoryScenePlanRepository(),
        scene_draft_repository=InMemorySceneDraftRepository(),
        audit_writer=writer,
        llm_gateway=LlmGateway(
            fake,
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
    )
    return TestClient(app), sink, fake, canon


def _create_project(client: TestClient) -> dict:
    response = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": "青石夜祠", "language": "zh-CN", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_spec(client: TestClient, project_id: str) -> dict:
    created = client.post(
        f"/projects/{project_id}/specs",
        headers=HUMAN,
        json={
            "title": "青石夜祠",
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


def _ready(client: TestClient) -> tuple[dict, dict, dict, dict]:
    project = _create_project(client)
    _create_spec(client, project["id"])
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"])
    snapshot = _create_snapshot(client, project["id"])
    plan = _create_plan(client, project["id"], scene["id"], snapshot["id"])
    return project, scene, snapshot, plan


def _draft_prompt_url(project_id: str, scene_id: str) -> str:
    return f"/projects/{project_id}/scenes/{scene_id}/shuttle/draft-prompt"


def _draft_import_url(project_id: str, scene_id: str) -> str:
    return f"/projects/{project_id}/scenes/{scene_id}/shuttle/drafts"


def _extract_prompt_url(project_id: str, scene_id: str, revision_id: str) -> str:
    return (
        f"/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}"
        "/shuttle/extract-prompt"
    )


def _extract_import_url(project_id: str, scene_id: str, revision_id: str) -> str:
    return f"/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/shuttle/extracts"


def _candidate_payload() -> dict:
    return {
        "subject": "林晚",
        "predicate": "持有",
        "object": "残玉",
        "value": "残玉",
        "effective_story_time": "第一日黄昏",
        "evidence_quote": EVIDENCE_QUOTE,
        "confidence": 0.9,
    }


def test_healthz_and_shuttle_paths_present_without_seed_status() -> None:
    client, _, _, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok"}
    paths = client.get("/openapi.json").json()["paths"]
    assert "/projects/{project_id}/scenes/{scene_id}/shuttle/draft-prompt" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/shuttle/drafts" in paths
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/shuttle/extract-prompt"
        in paths
    )
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/shuttle/extracts"
        in paths
    )
    assert "/projects/{project_id}/scenes/{scene_id}/drafts/jobs" in paths
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/extract-jobs"
        in paths
    )
    assert not any("seed-status" in path for path in paths)


def test_draft_prompt_contains_goal_forbid_knowledge_and_makes_no_model_http() -> None:
    client, _, fake, _ = _client()
    project, scene, _, _ = _ready(client)
    calls_before = fake.calls
    denied = client.get(_draft_prompt_url(project["id"], scene["id"]), headers=GENERATE)
    assert denied.status_code == 403
    assert denied.json()["detail"]["error"] == "human_editor_required"

    response = client.get(_draft_prompt_url(project["id"], scene["id"]), headers=HUMAN)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["purpose"] == "scene_draft"
    assert payload["scene_id"] == scene["id"]
    assert payload["is_canon"] is False
    prompt = payload["prompt"]
    assert "目标" in prompt
    assert "禁止" in prompt
    assert "知识边界" in prompt
    assert "不得写 Canon" in prompt
    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/drafts")
    assert listed.json()["items"] == []
    assert fake.calls == calls_before


def test_paste_draft_creates_external_subscribed_revision_without_model_http() -> None:
    client, sink, fake, canon = _client()
    project, scene, snapshot, plan = _ready(client)
    calls_before = fake.calls
    facts_before = len(canon.facts)

    short = client.post(
        _draft_import_url(project["id"], scene["id"]),
        headers=HUMAN,
        json={"body": "太短了", "snapshot_id": snapshot["id"]},
    )
    assert short.status_code == 400
    assert short.json()["detail"]["error"] == "draft_body_too_short"

    denied = client.post(
        _draft_import_url(project["id"], scene["id"]),
        headers=SYSTEM,
        json={"body": SHUTTLE_PROSE, "snapshot_id": snapshot["id"]},
    )
    assert denied.status_code == 403

    created = client.post(
        _draft_import_url(project["id"], scene["id"]),
        headers=HUMAN,
        json={
            "body": SHUTTLE_PROSE,
            "snapshot_id": snapshot["id"],
            "plan_id": plan["id"],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["is_canon"] is False
    assert body["auto_approved"] is False
    assert body["writes_canon"] is False
    draft = body["draft"]
    assert draft["generation_model"] == "external-subscribed"
    assert draft["prompt_version"] == "scene_draft.shuttle.v1"
    assert draft["status"] == "Generated"
    assert draft["body"] == SHUTTLE_PROSE
    fetched = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft['id']}"
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["generation_model"] == "external-subscribed"
    assert fetched.json()["status"] == "Generated"
    assert fake.calls == calls_before
    assert len(canon.facts) == facts_before
    audit_blob = " ".join(str(event.after_json) for event in sink.events)
    assert SHUTTLE_PROSE not in audit_blob


def test_extract_prompt_and_invalid_evidence_quote_persists_nothing() -> None:
    client, sink, fake, canon = _client()
    project, scene, snapshot, _ = _ready(client)
    created = client.post(
        _draft_import_url(project["id"], scene["id"]),
        headers=HUMAN,
        json={"body": SHUTTLE_PROSE, "snapshot_id": snapshot["id"]},
    )
    draft_id = created.json()["draft"]["id"]
    calls_before = fake.calls
    facts_before = len(canon.facts)

    prompt_resp = client.get(
        _extract_prompt_url(project["id"], scene["id"], draft_id),
        headers=HUMAN,
    )
    assert prompt_resp.status_code == 200, prompt_resp.text
    payload = prompt_resp.json()
    assert payload["purpose"] == "extract"
    assert payload["draft_id"] == draft_id
    assert payload["is_canon"] is False
    prompt = payload["prompt"]
    assert "目标" in prompt
    assert "禁止" in prompt
    assert "JSON 数组" in prompt
    assert "evidence_quote" in prompt
    assert "不得写 Canon" in prompt

    bad = client.post(
        _extract_import_url(project["id"], scene["id"], draft_id),
        headers=HUMAN,
        json={
            "candidates": [
                {**_candidate_payload(), "evidence_quote": "这段话不在正文里"}
            ]
        },
    )
    assert bad.status_code == 400, bad.text
    assert bad.json()["detail"]["error"] == "evidence_quote_not_in_draft"
    listed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/candidate-changes"
    )
    assert listed.json()["items"] == []
    assert len(canon.facts) == facts_before
    assert fake.calls == calls_before
    audit_blob = " ".join(
        f"{event.before_json} {event.after_json}" for event in sink.events
    )
    assert "这段话不在正文里" not in audit_blob


def test_valid_extract_paste_is_extracted_and_does_not_write_canon() -> None:
    client, sink, fake, canon = _client()
    project, scene, snapshot, _ = _ready(client)
    created = client.post(
        _draft_import_url(project["id"], scene["id"]),
        headers=HUMAN,
        json={"body": SHUTTLE_PROSE, "snapshot_id": snapshot["id"]},
    )
    draft_id = created.json()["draft"]["id"]
    calls_before = fake.calls
    facts_before = len(canon.facts)

    denied = client.post(
        _extract_import_url(project["id"], scene["id"], draft_id),
        headers=GENERATE,
        json={"candidates": [_candidate_payload()]},
    )
    assert denied.status_code == 403

    imported = client.post(
        _extract_import_url(project["id"], scene["id"], draft_id),
        headers=HUMAN,
        json={"candidates": [_candidate_payload()]},
    )
    assert imported.status_code == 201, imported.text
    body = imported.json()
    assert body["is_canon"] is False
    assert body["auto_approved"] is False
    assert body["writes_canon"] is False
    assert body["items"][0]["status"] == "Extracted"
    listed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/candidate-changes"
    )
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "Extracted"
    assert items[0]["evidence_quote"] == EVIDENCE_QUOTE
    assert items[0]["is_canon"] is False
    draft = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft_id}"
    )
    assert draft.json()["status"] == "Extracted"
    assert draft.json()["body"] == SHUTTLE_PROSE
    assert len(canon.facts) == facts_before
    assert fake.calls == calls_before
    audit_blob = " ".join(str(event.after_json) for event in sink.events)
    assert EVIDENCE_QUOTE not in audit_blob
    assert "candidate_change.approve" not in [event.action for event in sink.events]
    assert "candidate_change.submit" not in [event.action for event in sink.events]
