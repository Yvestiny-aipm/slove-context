"""Human summary shuttle (node UI.3).

Copy scene / chapter summary prompts out; paste short summaries back.
In-memory repositories. No live Postgres. No network. No real model HTTP.
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
from slove_context.summary.repository import InMemorySummaryRepository

HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}
SYSTEM = {"X-Actor-Type": "system", "X-Actor-Id": "sys-1"}
SHUTTLE_PROSE = (
    "河滩风冷，林晚看见一点光，伸手拾起残玉。"
    "她把玉握在掌心，没有追问来历，只记住这一夜的潮声。"
    "风从芦苇里穿过，她把残玉收进袖中，继续沿河走下去。"
)
SHUTTLE_SCENE_SUMMARY = (
    "林晚在河滩拾得残玉，未追问来历，只把潮声、夜风和掌心的凉意记在心里。"
    "这场只记她得玉，不写来历，也不写成整章。"
)
SHUTTLE_CHAPTER_SUMMARY = (
    "本章汇总各场场景摘要：林晚得玉，未写来历，潮声仍在。"
    "各场短摘要已齐，此处只做章级汇总，不生成整章散文。"
)


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
        summary_repository=InMemorySummaryRepository(),
        audit_writer=writer,
        llm_gateway=LlmGateway(
            fake,
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
    )
    return TestClient(app), sink, fake, canon


def _spy_gateway(client: TestClient) -> list[str]:
    gateway = client.app.state.llm_gateway
    seen: list[str] = []
    original_text = gateway.generate_text
    original_structured = gateway.generate_structured

    def text(request):  # type: ignore[no-untyped-def]
        seen.append("generate_text")
        return original_text(request)

    def structured(request):  # type: ignore[no-untyped-def]
        seen.append("generate_structured")
        return original_structured(request)

    gateway.generate_text = text
    gateway.generate_structured = structured
    return seen


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


def _scene_payload(chapter_id: str, story_order: int) -> dict:
    return {
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


def _create_scene(
    client: TestClient, project_id: str, chapter_id: str, story_order: int = 1
) -> dict:
    response = client.post(
        f"/projects/{project_id}/scenes",
        headers=HUMAN,
        json=_scene_payload(chapter_id, story_order),
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
        json={"body": SHUTTLE_PROSE, "snapshot_id": snapshot_id},
    )
    assert created.status_code == 201, created.text
    return created.json()["draft"]


def _ready_one(
    client: TestClient,
) -> tuple[dict, dict, dict, dict]:
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"], 1)
    snapshot = _create_snapshot(client, project["id"])
    _create_plan(client, project["id"], scene["id"], snapshot["id"])
    draft = _import_draft(client, project["id"], scene["id"], snapshot["id"])
    return project, chapter, scene, draft


def _scene_prompt_url(project_id: str, scene_id: str, draft_id: str) -> str:
    return (
        f"/projects/{project_id}/scenes/{scene_id}/shuttle/summary-prompt"
        f"?draft_revision_id={draft_id}"
    )


def _scene_import_url(project_id: str, scene_id: str) -> str:
    return f"/projects/{project_id}/scenes/{scene_id}/shuttle/summaries"


def _chapter_prompt_url(project_id: str, chapter_id: str) -> str:
    return f"/projects/{project_id}/chapters/{chapter_id}/shuttle/summary-prompt"


def _chapter_import_url(project_id: str, chapter_id: str) -> str:
    return f"/projects/{project_id}/chapters/{chapter_id}/shuttle/summaries"


def test_healthz_and_summary_shuttle_paths_present_without_seed_status() -> None:
    client, _, _, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok"}
    paths = client.get("/openapi.json").json()["paths"]
    assert "/projects/{project_id}/scenes/{scene_id}/shuttle/summary-prompt" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/shuttle/summaries" in paths
    assert (
        "/projects/{project_id}/chapters/{chapter_id}/shuttle/summary-prompt" in paths
    )
    assert "/projects/{project_id}/chapters/{chapter_id}/shuttle/summaries" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/summaries/jobs" in paths
    assert "/projects/{project_id}/chapters/{chapter_id}/summaries/jobs" in paths
    assert not any("seed-status" in path for path in paths)


def test_scene_summary_paste_back_succeeds_without_gateway_or_canon() -> None:
    client, sink, fake, canon = _client()
    project, _, scene, draft = _ready_one(client)
    calls_before = fake.calls
    facts_before = len(canon.facts)
    gateway_calls = _spy_gateway(client)

    denied = client.get(
        _scene_prompt_url(project["id"], scene["id"], draft["id"]),
        headers=GENERATE,
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["error"] == "human_editor_required"

    prompt_resp = client.get(
        _scene_prompt_url(project["id"], scene["id"], draft["id"]),
        headers=HUMAN,
    )
    assert prompt_resp.status_code == 200, prompt_resp.text
    prompt_body = prompt_resp.json()
    assert prompt_body["purpose"] == "scene_summary"
    assert prompt_body["draft_revision_id"] == draft["id"]
    assert prompt_body["is_canon"] is False
    prompt = prompt_body["prompt"]
    assert "只输出这一场的短摘要" in prompt
    assert "不得写 Canon" in prompt
    assert draft["body"] in prompt
    assert "scene_summary.v1" in prompt

    short = client.post(
        _scene_import_url(project["id"], scene["id"]),
        headers=HUMAN,
        json={"draft_revision_id": draft["id"], "body": "太短了"},
    )
    assert short.status_code == 422
    assert short.json()["detail"]["error"] == "scene_summary_body_too_short"

    denied_post = client.post(
        _scene_import_url(project["id"], scene["id"]),
        headers=SYSTEM,
        json={"draft_revision_id": draft["id"], "body": SHUTTLE_SCENE_SUMMARY},
    )
    assert denied_post.status_code == 403

    missing = client.post(
        _scene_import_url(project["id"], scene["id"]),
        headers=HUMAN,
        json={
            "draft_revision_id": "missing-draft",
            "body": SHUTTLE_SCENE_SUMMARY,
        },
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["error"] == "scene_draft_not_found"

    created = client.post(
        _scene_import_url(project["id"], scene["id"]),
        headers=HUMAN,
        json={"draft_revision_id": draft["id"], "body": SHUTTLE_SCENE_SUMMARY},
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["is_canon"] is False
    assert payload["auto_approved"] is False
    assert payload["writes_canon"] is False
    summary = payload["summary"]
    assert summary["generation_model"] == "external-subscribed"
    assert summary["prompt_version"] == "scene_summary.shuttle.v1"
    assert summary["status"] == "Generated"
    assert summary["body"] == SHUTTLE_SCENE_SUMMARY
    assert summary["source_draft_revision_id"] == draft["id"]
    assert summary["is_canon"] is False
    assert summary["is_scene_draft"] is False
    assert summary["is_candidate_change"] is False

    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/summaries")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == summary["id"]
    assert items[0]["status"] == "Generated"
    assert fake.calls == calls_before
    assert gateway_calls == []
    assert len(canon.facts) == facts_before
    audit_blob = " ".join(
        f"{event.before_json} {event.after_json}" for event in sink.events
    )
    assert SHUTTLE_SCENE_SUMMARY not in audit_blob
    assert SHUTTLE_PROSE not in audit_blob
    assert prompt not in audit_blob


def test_scene_summary_idempotency_and_supersede_old_revision() -> None:
    client, _, fake, canon = _client()
    project, _, scene, draft = _ready_one(client)
    facts_before = len(canon.facts)

    first = client.post(
        _scene_import_url(project["id"], scene["id"]),
        headers=HUMAN,
        json={
            "draft_revision_id": draft["id"],
            "body": SHUTTLE_SCENE_SUMMARY,
            "idempotency_key": "sum-1",
        },
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["summary"]["id"]
    calls_before = fake.calls
    gateway_calls = _spy_gateway(client)

    again = client.post(
        _scene_import_url(project["id"], scene["id"]),
        headers=HUMAN,
        json={
            "draft_revision_id": draft["id"],
            "body": SHUTTLE_SCENE_SUMMARY + "又写一遍。",
            "idempotency_key": "sum-1",
        },
    )
    assert again.status_code == 201, again.text
    assert again.json()["summary"]["id"] == first_id
    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/summaries")
    assert len(listed.json()["items"]) == 1
    assert fake.calls == calls_before
    assert gateway_calls == []

    second = client.post(
        _scene_import_url(project["id"], scene["id"]),
        headers=HUMAN,
        json={
            "draft_revision_id": draft["id"],
            "body": SHUTTLE_SCENE_SUMMARY + "修订后仍是短摘要。",
            "idempotency_key": "sum-2",
        },
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["summary"]["id"]
    assert second_id != first_id
    items = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries"
    ).json()["items"]
    by_id = {item["id"]: item for item in items}
    assert by_id[first_id]["status"] == "Superseded"
    assert by_id[second_id]["status"] == "Generated"
    assert by_id[first_id]["body"] == SHUTTLE_SCENE_SUMMARY
    assert len(canon.facts) == facts_before


def test_fake_summary_jobs_still_work_and_are_superseded_by_shuttle() -> None:
    client, _, fake, canon = _client()
    project, _, scene, draft = _ready_one(client)
    facts_before = len(canon.facts)

    fake_job = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/jobs",
        headers=GENERATE,
        json={"draft_revision_id": draft["id"]},
    )
    assert fake_job.status_code == 201, fake_job.text
    assert fake_job.json()["state"] == "succeeded"
    fake_summary_id = fake_job.json()["summary_id"]
    fetched = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/{fake_summary_id}"
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["status"] == "Generated"
    assert fetched.json()["prompt_version"] == "scene_summary.v1"
    assert fetched.json()["generation_model"] != "external-subscribed"
    assert fake.calls >= 1

    calls_before = fake.calls
    gateway_calls = _spy_gateway(client)
    pasted = client.post(
        _scene_import_url(project["id"], scene["id"]),
        headers=HUMAN,
        json={"draft_revision_id": draft["id"], "body": SHUTTLE_SCENE_SUMMARY},
    )
    assert pasted.status_code == 201, pasted.text
    assert pasted.json()["summary"]["generation_model"] == "external-subscribed"
    old = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/{fake_summary_id}"
    )
    assert old.json()["status"] == "Superseded"
    assert fake.calls == calls_before
    assert gateway_calls == []
    assert len(canon.facts) == facts_before

    later_fake = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/summaries/jobs",
        headers=GENERATE,
        json={"draft_revision_id": draft["id"], "idempotency_key": "fake-retry"},
    )
    assert later_fake.status_code == 201, later_fake.text
    assert later_fake.json()["state"] == "succeeded"
    later = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}"
        f"/summaries/{later_fake.json()['summary_id']}"
    )
    assert later.json()["status"] == "Generated"
    assert later.json()["prompt_version"] == "scene_summary.v1"


def test_chapter_summary_missing_scene_is_409_and_complete_paste_works() -> None:
    client, sink, fake, canon = _client()
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    scene_a = _create_scene(client, project["id"], chapter["id"], 1)
    scene_b = _create_scene(client, project["id"], chapter["id"], 2)
    snapshot = _create_snapshot(client, project["id"])
    _create_plan(client, project["id"], scene_a["id"], snapshot["id"])
    _create_plan(client, project["id"], scene_b["id"], snapshot["id"])
    draft_a = _import_draft(client, project["id"], scene_a["id"], snapshot["id"])
    draft_b = _import_draft(client, project["id"], scene_b["id"], snapshot["id"])

    first = client.post(
        _scene_import_url(project["id"], scene_a["id"]),
        headers=HUMAN,
        json={"draft_revision_id": draft_a["id"], "body": SHUTTLE_SCENE_SUMMARY},
    )
    assert first.status_code == 201, first.text
    calls_before = fake.calls
    facts_before = len(canon.facts)
    gateway_calls = _spy_gateway(client)

    missing_prompt = client.get(
        _chapter_prompt_url(project["id"], chapter["id"]),
        headers=HUMAN,
    )
    assert missing_prompt.status_code == 409, missing_prompt.text
    assert missing_prompt.json()["detail"]["error"] == "scene_summaries_missing"
    assert scene_b["id"] in missing_prompt.json()["detail"]["missing_scene_ids"]

    missing_paste = client.post(
        _chapter_import_url(project["id"], chapter["id"]),
        headers=HUMAN,
        json={
            "body": SHUTTLE_CHAPTER_SUMMARY,
            "source_scene_summary_revision_ids": [first.json()["summary"]["id"]],
        },
    )
    assert missing_paste.status_code == 409, missing_paste.text
    assert missing_paste.json()["detail"]["error"] == "scene_summaries_missing"

    second = client.post(
        _scene_import_url(project["id"], scene_b["id"]),
        headers=HUMAN,
        json={
            "draft_revision_id": draft_b["id"],
            "body": SHUTTLE_SCENE_SUMMARY + "第二场同样只记潮声。",
        },
    )
    assert second.status_code == 201, second.text
    source_ids = [first.json()["summary"]["id"], second.json()["summary"]["id"]]

    incomplete = client.post(
        _chapter_import_url(project["id"], chapter["id"]),
        headers=HUMAN,
        json={
            "body": SHUTTLE_CHAPTER_SUMMARY,
            "source_scene_summary_revision_ids": [source_ids[0]],
        },
    )
    assert incomplete.status_code == 409, incomplete.text
    assert (
        incomplete.json()["detail"]["error"]
        == "source_scene_summary_revision_ids_incomplete"
    )

    denied = client.post(
        _chapter_import_url(project["id"], chapter["id"]),
        headers=GENERATE,
        json={
            "body": SHUTTLE_CHAPTER_SUMMARY,
            "source_scene_summary_revision_ids": source_ids,
        },
    )
    assert denied.status_code == 403

    prompt_resp = client.get(
        _chapter_prompt_url(project["id"], chapter["id"]),
        headers=HUMAN,
    )
    assert prompt_resp.status_code == 200, prompt_resp.text
    chapter_prompt = prompt_resp.json()["prompt"]
    assert "不得生成整章散文" in chapter_prompt
    assert "chapter_summary.v1" in chapter_prompt
    assert first.json()["summary"]["body"] in chapter_prompt

    created = client.post(
        _chapter_import_url(project["id"], chapter["id"]),
        headers=HUMAN,
        json={
            "body": SHUTTLE_CHAPTER_SUMMARY,
            "source_scene_summary_revision_ids": source_ids,
            "idempotency_key": "ch-1",
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["writes_canon"] is False
    summary = payload["summary"]
    assert summary["generation_model"] == "external-subscribed"
    assert summary["prompt_version"] == "chapter_summary.shuttle.v1"
    assert summary["status"] == "Generated"
    assert set(summary["source_scene_summary_revision_ids"]) == set(source_ids)

    again = client.post(
        _chapter_import_url(project["id"], chapter["id"]),
        headers=HUMAN,
        json={
            "body": SHUTTLE_CHAPTER_SUMMARY + "重复贴回。",
            "source_scene_summary_revision_ids": source_ids,
            "idempotency_key": "ch-1",
        },
    )
    assert again.status_code == 201, again.text
    assert again.json()["summary"]["id"] == summary["id"]
    assert fake.calls == calls_before
    assert gateway_calls == []
    assert len(canon.facts) == facts_before
    audit_blob = " ".join(str(event.after_json) for event in sink.events)
    assert SHUTTLE_CHAPTER_SUMMARY not in audit_blob
    assert chapter_prompt not in audit_blob
    listed = client.get(f"/projects/{project['id']}/chapters/{chapter['id']}/summaries")
    assert listed.json()["items"][0]["status"] == "Generated"
