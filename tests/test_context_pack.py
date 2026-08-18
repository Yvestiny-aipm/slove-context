"""Context Pack assembler (node 6.1).

In-memory repositories. No live Postgres. No network. No real models.
Generate / Validate only. Pack is not Canon. Freeze is not Approval.
No chapter-level pack. Failure / cancel keep records.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.canon.models import FACT_ACTIVE
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.context_pack.repository import InMemoryContextPackRepository
from slove_context.context_pack.validate import validate_context_pack
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_draft.context_pack import STATIC_CONTEXT_PACK_ID
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.scene_plan.repository import InMemoryScenePlanRepository
from slove_context.story.repository import InMemoryStoryRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}
SYSTEM = {"X-Actor-Type": "system", "X-Actor-Id": "sys-1"}
SPEC = {
    "title": "青石夜祠",
    "language": "zh-CN",
    "must_write": ["只写林晚在青石镇的七日"],
    "must_not_write": ["禁止第二主角视角"],
    "notes": "规格是编辑约束，不是 Canon。",
    "created_by": "主编",
}
SCENE_1 = "33333333-3333-4333-8333-333333333333"


def _client() -> tuple[
    TestClient,
    InMemoryAuditSink,
    InMemoryCanonRepository,
    InMemoryContextPackRepository,
]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    canon = InMemoryCanonRepository()
    packs = InMemoryContextPackRepository()
    app = create_app(
        repository=InMemoryStoryRepository(),
        canon_repository=canon,
        scene_repository=InMemorySceneRepository(),
        scene_plan_repository=InMemoryScenePlanRepository(),
        scene_draft_repository=InMemorySceneDraftRepository(),
        context_pack_repository=packs,
        audit_writer=writer,
        llm_gateway=LlmGateway(
            FakeProvider(),
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
    )
    return TestClient(app), sink, canon, packs


def _create_project(client: TestClient) -> dict:
    response = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": "青石夜祠", "language": "zh-CN", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _write_spec(client: TestClient, project_id: str, *, effective: bool = True) -> dict:
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
    if not effective:
        return submitted.json()
    approved = client.post(
        f"/projects/{project_id}/specs/{spec_id}/approve",
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
    return response.json()


def _approve_scene(client: TestClient, project_id: str, scene_id: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/approve",
        headers=HUMAN,
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_entity(client: TestClient, project_id: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/entities",
        headers=HUMAN,
        json={"name": "残玉", "entity_type": "item", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_evidence(client: TestClient, project_id: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/evidence",
        headers=HUMAN,
        json={
            "source_type": "editor",
            "quote": "主编已批准并提交：残玉只能由林晚触活",
            "scene_id": SCENE_1,
            "created_by": "主编",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_active_fact(
    client: TestClient, project_id: str, entity_id: str, evidence_id: str
) -> dict:
    created = client.post(
        f"/projects/{project_id}/canon-facts",
        headers=HUMAN,
        json={
            "entity_id": entity_id,
            "predicate": "只能由林晚触活",
            "value_json": {"text": "是"},
            "effective_story_time": "day-01",
            "valid_from_scene_id": SCENE_1,
            "source_type": "editor",
            "evidence_id": evidence_id,
            "created_by": "主编",
        },
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
    client: TestClient, project_id: str, *, freeze: bool = True
) -> dict:
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
    if not freeze:
        return created.json()
    frozen = client.post(
        f"/projects/{project_id}/canon-snapshots/{created.json()['id']}/freeze",
        headers=HUMAN,
        json={},
    )
    assert frozen.status_code == 200, frozen.text
    return frozen.json()


def _ready(
    client: TestClient,
    *,
    with_spec: bool = True,
    approve_scene: bool = True,
    with_fact: bool = True,
    freeze_snapshot: bool = True,
) -> tuple[dict, dict, dict | None]:
    project = _create_project(client)
    if with_spec:
        _write_spec(client, project["id"])
    chapter = _create_chapter(client, project["id"])
    scene = _create_scene(client, project["id"], chapter["id"])
    if approve_scene:
        scene = _approve_scene(client, project["id"], scene["id"])
    if with_fact:
        entity = _create_entity(client, project["id"])
        evidence = _create_evidence(client, project["id"])
        _create_active_fact(client, project["id"], entity["id"], evidence["id"])
    snapshot = _create_snapshot(client, project["id"], freeze=freeze_snapshot)
    return project, scene, snapshot


def _assemble(
    client: TestClient,
    project_id: str,
    scene_id: str,
    snapshot_id: str,
    *,
    purpose: str = "Generate",
    headers: dict[str, str] | None = None,
) -> object:
    return client.post(
        f"/projects/{project_id}/scenes/{scene_id}/context-packs",
        headers=headers or HUMAN,
        json={"snapshot_id": snapshot_id, "purpose": purpose},
    )


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


def test_healthz_and_prior_apis_remain_no_chapter_pack() -> None:
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
    assert "/projects/{project_id}/context-packs/{pack_id}" in paths
    assert "/projects/{project_id}/context-packs/{pack_id}/freeze" in paths
    assert "/projects/{project_id}/chapters/{chapter_id}/context-packs" not in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/outlines" not in paths
    assert (
        client.post("/projects/p/chapters/c/context-packs", json={}).status_code == 404
    )
    assert client.post("/projects/p/chapters/generate", json={}).status_code == 404


def test_generate_pack_validates_schema_and_is_read_only() -> None:
    client, sink, canon, _ = _client()
    project, scene, snapshot = _ready(client)
    before = _canon_fact_count(canon, project["id"])
    response = _assemble(
        client, project["id"], scene["id"], snapshot["id"], purpose="Generate"
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["purpose"] == "Generate"
    assert body["status"] == "Assembled"
    assert body["is_canon"] is False
    assert body["writes_canon"] is False
    assert body["auto_approved"] is False
    assert body["is_approval"] is False
    assert body["is_outline"] is False
    pack = body["pack"]
    validate_context_pack(pack)
    assert pack["purpose"] == "Generate"
    assert pack["scene_id"] == scene["id"]
    assert pack["scene_card_id"] == scene["scene_card_id"]
    assert pack["knowledge_boundaries"] == ["林晚不知残玉能开门"]
    assert pack["canon_excerpts"]
    excerpt = pack["canon_excerpts"][0]
    assert excerpt["effective_story_time"] == "day-01"
    assert excerpt["source_evidence"]
    assert "candidate_change_ids" not in pack
    assert _canon_fact_count(canon, project["id"]) == before
    assert any(
        event.action == "context_pack.assemble"
        and event.resource_type == "context_pack"
        for event in sink.events
    )


def test_validate_pack_includes_candidate_ids_and_does_not_approve() -> None:
    client, _, canon, _ = _client()
    project, scene, snapshot = _ready(client)
    before_active = _active_fact_count(canon, project["id"])
    response = _assemble(
        client, project["id"], scene["id"], snapshot["id"], purpose="Validate"
    )
    assert response.status_code == 201, response.text
    body = response.json()
    pack = body["pack"]
    validate_context_pack(pack)
    assert pack["purpose"] == "Validate"
    assert pack["candidate_change_ids"] == []
    assert body["is_approved"] is False
    assert body["auto_approved"] is False
    fetched = client.get(f"/projects/{project['id']}/context-packs/{body['id']}")
    assert fetched.status_code == 200, fetched.text
    validate_context_pack(fetched.json()["pack"])
    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/context-packs")
    assert listed.status_code == 200, listed.text
    assert listed.json()["is_canon"] is False
    assert len(listed.json()["items"]) == 1
    assert _active_fact_count(canon, project["id"]) == before_active


def test_missing_card_spec_snapshot_or_scene_rejected() -> None:
    client, _, _, packs = _client()
    project, draft_scene, snapshot = _ready(client, approve_scene=False)
    missing_card = _assemble(client, project["id"], draft_scene["id"], snapshot["id"])
    assert missing_card.status_code == 409
    assert missing_card.json()["detail"]["error"] == "scene_card_not_approved"
    assert packs.packs == {}

    no_spec_client, _, _, _ = _client()
    no_spec_project, scene, frozen = _ready(no_spec_client, with_spec=False)
    missing_spec = _assemble(
        no_spec_client, no_spec_project["id"], scene["id"], frozen["id"]
    )
    assert missing_spec.status_code == 409
    assert missing_spec.json()["detail"]["error"] == "story_spec_required"

    draft_client, _, _, _ = _client()
    draft_only = _create_project(draft_client)
    draft_spec = draft_client.post(
        f"/projects/{draft_only['id']}/specs",
        headers=HUMAN,
        json=SPEC,
    )
    assert draft_spec.status_code == 201, draft_spec.text
    chapter = _create_chapter(draft_client, draft_only["id"])
    draft_scene_2 = _create_scene(draft_client, draft_only["id"], chapter["id"])
    approved = _approve_scene(draft_client, draft_only["id"], draft_scene_2["id"])
    snap = _create_snapshot(draft_client, draft_only["id"])
    not_written = _assemble(draft_client, draft_only["id"], approved["id"], snap["id"])
    assert not_written.status_code == 409
    assert not_written.json()["detail"]["error"] == "story_spec_not_written"

    unfrozen_client, _, _, _ = _client()
    project_ok, scene_ok, unfrozen = _ready(unfrozen_client, freeze_snapshot=False)
    missing_freeze = _assemble(
        unfrozen_client, project_ok["id"], scene_ok["id"], unfrozen["id"]
    )
    assert missing_freeze.status_code == 409
    assert missing_freeze.json()["detail"]["error"] == "snapshot_not_frozen"

    missing_snapshot = _assemble(
        unfrozen_client,
        project_ok["id"],
        scene_ok["id"],
        "99999999-9999-4999-8999-999999999999",
    )
    assert missing_snapshot.status_code == 409
    assert missing_snapshot.json()["detail"]["error"] == "snapshot_required"

    missing_scene = _assemble(
        unfrozen_client,
        project_ok["id"],
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        unfrozen["id"],
    )
    assert missing_scene.status_code == 404
    assert missing_scene.json()["detail"]["error"] == "scene_not_found"


def test_invalid_purpose_rejected_and_no_outline() -> None:
    client, _, _, _ = _client()
    project, scene, snapshot = _ready(client)
    response = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/context-packs",
        headers=HUMAN,
        json={"snapshot_id": snapshot["id"], "purpose": "Outline"},
    )
    assert response.status_code == 422
    assert client.get("/projects/{}/outlines".format(project["id"])).status_code == 404


def test_freeze_makes_pack_immutable_reassemble_is_new_revision() -> None:
    client, sink, canon, packs = _client()
    project, scene, snapshot = _ready(client)
    first = _assemble(client, project["id"], scene["id"], snapshot["id"])
    assert first.status_code == 201, first.text
    pack_id = first.json()["id"]
    first_payload = first.json()["pack"]
    frozen = client.post(
        f"/projects/{project['id']}/context-packs/{pack_id}/freeze",
        headers=SYSTEM,
        json={},
    )
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["status"] == "Frozen"
    assert frozen.json()["immutable"] is True
    assert frozen.json()["is_approval"] is False
    assert frozen.json()["writes_canon"] is False
    again = client.post(
        f"/projects/{project['id']}/context-packs/{pack_id}/freeze",
        headers=HUMAN,
        json={},
    )
    assert again.status_code == 409
    assert again.json()["detail"]["error"] == "pack_already_frozen"
    second = _assemble(client, project["id"], scene["id"], snapshot["id"])
    assert second.status_code == 201, second.text
    assert second.json()["id"] != pack_id
    assert second.json()["revision"] == 2
    stored = packs.get(pack_id)
    assert stored is not None
    assert stored.status == "Frozen"
    assert stored.payload == first_payload
    fetched = client.get(f"/projects/{project['id']}/context-packs/{pack_id}")
    assert fetched.json()["pack"] == first_payload
    assert _canon_fact_count(canon, project["id"]) == _active_fact_count(
        canon, project["id"]
    )
    assert any(event.action == "context_pack.freeze" for event in sink.events)


def test_cancel_and_fail_keep_records_and_do_not_write_canon() -> None:
    client, sink, canon, packs = _client()
    project, scene, snapshot = _ready(client)
    before = _canon_fact_count(canon, project["id"])
    created = _assemble(client, project["id"], scene["id"], snapshot["id"])
    assert created.status_code == 201, created.text
    pack_id = created.json()["id"]
    blocked = client.post(
        f"/projects/{project['id']}/context-packs/{pack_id}/cancel",
        headers=GENERATE,
        json={},
    )
    assert blocked.status_code == 403
    cancelled = client.post(
        f"/projects/{project['id']}/context-packs/{pack_id}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "Cancelled"
    kept = client.get(f"/projects/{project['id']}/context-packs/{pack_id}")
    assert kept.status_code == 200
    assert kept.json()["status"] == "Cancelled"
    assert packs.get(pack_id) is not None

    packs.force_fail = True
    failed = _assemble(client, project["id"], scene["id"], snapshot["id"])
    assert failed.status_code == 201, failed.text
    assert failed.json()["status"] == "Failed"
    failed_id = failed.json()["id"]
    assert packs.get(failed_id) is not None
    assert packs.get(failed_id).failure_reason == "forced_assemble_fail"
    still_there = client.get(f"/projects/{project['id']}/context-packs/{failed_id}")
    assert still_there.status_code == 200
    assert still_there.json()["status"] == "Failed"
    assert _canon_fact_count(canon, project["id"]) == before
    assert any(event.action == "context_pack.cancel" for event in sink.events)
    assert any(event.action == "context_pack.failed" for event in sink.events)


def test_audit_redacts_prose_and_does_not_store_excerpts() -> None:
    client, sink, _, _ = _client()
    project, scene, snapshot = _ready(client)
    response = _assemble(client, project["id"], scene["id"], snapshot["id"])
    assert response.status_code == 201, response.text
    events = [
        event
        for event in sink.events
        if event.resource_type == "context_pack"
        and event.action == "context_pack.assemble"
    ]
    assert events
    after = events[-1].after_json or {}
    blob = str(after)
    assert "残玉只能由林晚触活" not in blob
    assert "林晚不知残玉能开门" not in blob
    assert "scene_draft_excerpt" not in after
    assert "canon_excerpts" not in after
    assert after["writes_canon"] is False
    assert after["is_approval"] is False


def test_static_fixture_and_frozen_pack_both_work_for_scene_draft() -> None:
    client, _, _, _ = _client()
    project, scene, snapshot = _ready(client, with_fact=False)
    plan_job = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot["id"]},
    )
    assert plan_job.status_code == 201, plan_job.text
    plan = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/plans/current")
    assert plan.status_code == 200, plan.text
    static_job = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json={
            "snapshot_id": snapshot["id"],
            "plan_id": plan.json()["plan"]["id"],
            "context_pack_id": STATIC_CONTEXT_PACK_ID,
        },
    )
    assert static_job.status_code == 201, static_job.text
    assembled = _assemble(client, project["id"], scene["id"], snapshot["id"])
    assert assembled.status_code == 201, assembled.text
    frozen = client.post(
        f"/projects/{project['id']}/context-packs/{assembled.json()['id']}/freeze",
        headers=HUMAN,
        json={},
    )
    assert frozen.status_code == 200, frozen.text
    assembled_job = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json={
            "snapshot_id": snapshot["id"],
            "plan_id": plan.json()["plan"]["id"],
            "context_pack_id": frozen.json()["id"],
        },
    )
    assert assembled_job.status_code == 201, assembled_job.text
    assert assembled_job.json()["context_pack_id"] == frozen.json()["id"]


def test_migration_adds_context_packs_without_rebuilding_prior_tables() -> None:
    versions = ROOT / "backend" / "alembic" / "versions"
    create = (versions / "013_create_context_packs.py").read_text(encoding="utf-8")
    assert "CREATE TABLE context_packs" in create
    assert "CREATE TABLE repair_tasks" not in create
    assert "CREATE TABLE validation_runs" not in create
    assert "CREATE TABLE scene_drafts" not in create
    assert "CREATE TABLE outlines" not in create
    assert 'down_revision: str | None = "012_repair_tasks"' in create
    upgrade = create.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    lowered = upgrade.lower()
    assert "vector(" not in lowered
    assert "embedding" not in lowered
    assert "openai" not in lowered
