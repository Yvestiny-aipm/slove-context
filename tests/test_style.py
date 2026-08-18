"""Style Guide / Style Sample (node 7.1).

In-memory repositories. No live Postgres. No network. No real models.
Create draft / human approve / authorize. Approve is not Canon approval.
Approved cannot be edited in place. Unapproved / unauthorized / version
mismatch cannot be referenced. Fail / cancel keep records.
No style scoring (7.2). 2.1–6.2 APIs and /healthz remain.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.canon.models import FACT_ACTIVE
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_draft.models import DRAFT_GENERATED, SceneDraft
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.story.repository import InMemoryStoryRepository
from slove_context.style.repository import InMemoryStyleRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}
REVIEW = {"X-Actor-Type": "review_agent", "X-Actor-Id": "rev-1"}
SYSTEM = {"X-Actor-Type": "system", "X-Actor-Id": "sys-1"}

POSITIVE_EXAMPLE = "她把残玉握进掌心，河风贴着腕骨过去。"
NEGATIVE_EXAMPLE = "哇塞这玉也太酷了吧路人也能触活！"
SAMPLE_BODY = "河滩泥凉。林晚蹲下去，指节碰到一点冷光。"


def _client() -> tuple[
    TestClient,
    InMemoryAuditSink,
    InMemoryCanonRepository,
    InMemoryStyleRepository,
    InMemorySceneDraftRepository,
]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    canon = InMemoryCanonRepository()
    styles = InMemoryStyleRepository()
    drafts = InMemorySceneDraftRepository()
    app = create_app(
        repository=InMemoryStoryRepository(),
        canon_repository=canon,
        scene_repository=InMemorySceneRepository(),
        scene_draft_repository=drafts,
        style_repository=styles,
        audit_writer=writer,
        llm_gateway=LlmGateway(
            FakeProvider(),
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
    )
    return TestClient(app), sink, canon, styles, drafts


def _create_project(client: TestClient) -> dict:
    response = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": "青石夜祠", "language": "zh-CN", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


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
    return scene.json()


def _guide_payload(**overrides: object) -> dict:
    payload: dict = {
        "pov": "林晚",
        "人称": "第三人称限制",
        "时态": "过去进行",
        "叙述距离": "中距，贴着感官",
        "语气": "克制、冷而干净",
        "节奏": "短句推进，少解释",
        "对话规则": ["少称呼全名", "不解释设定"],
        "词汇偏好": ["河风", "冷光", "腕骨"],
        "禁用表达": ["哇塞", "太酷了"],
        "正例": [POSITIVE_EXAMPLE],
        "反例": [NEGATIVE_EXAMPLE],
        "created_by": "主编",
    }
    payload.update(overrides)
    return payload


def _sample_payload(**overrides: object) -> dict:
    payload: dict = {
        "source": "主编自写样本",
        "copyright_mark": "已授权自有版权",
        "scope_of_use": "仅本故事项目风格参照，不得外发",
        "body": SAMPLE_BODY,
        "created_by": "主编",
    }
    payload.update(overrides)
    return payload


def _create_guide(client: TestClient, project_id: str, **overrides: object) -> dict:
    response = client.post(
        f"/projects/{project_id}/style-guides",
        headers=HUMAN,
        json=_guide_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _approve_guide(client: TestClient, project_id: str, guide_id: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/style-guides/{guide_id}/approve",
        headers=HUMAN,
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_sample(client: TestClient, project_id: str, **overrides: object) -> dict:
    response = client.post(
        f"/projects/{project_id}/style-samples",
        headers=HUMAN,
        json=_sample_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _authorize_sample(client: TestClient, project_id: str, sample_id: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/style-samples/{sample_id}/authorize",
        headers=HUMAN,
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_draft(
    drafts: InMemorySceneDraftRepository, *, project_id: str, scene_id: str
) -> SceneDraft:
    draft = SceneDraft(
        id=str(uuid4()),
        project_id=project_id,
        scene_id=scene_id,
        job_id=str(uuid4()),
        revision=1,
        status=DRAFT_GENERATED,
        body="河滩风冷，林晚看见一点光。",
        content_hash="hash-ref",
        character_count=12,
        word_count_estimate=6,
        generation_model="fake-model",
        prompt_version="scene_draft.v1",
        generated_at="2026-08-18T00:00:00.000000Z",
        scene_card_id=str(uuid4()),
        plan_id=str(uuid4()),
        snapshot_id=str(uuid4()),
        context_pack_id="static-context-pack",
        created_at="2026-08-18T00:00:00.000000Z",
        created_by="主编",
    )
    drafts.add_draft(draft)
    return draft


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


def test_healthz_and_prior_apis_remain() -> None:
    client, _, _, _, _ = _client()
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
    assert "/projects/{project_id}/style-guides" in paths
    assert "/projects/{project_id}/style-guides/{guide_id}/approve" in paths
    assert "/projects/{project_id}/style-samples" in paths
    assert "/projects/{project_id}/style-samples/{sample_id}/authorize" in paths
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/style" in paths
    )
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/style-score" not in paths
    assert "/projects/{project_id}/auto-approve" not in paths
    assert not any("seed-status" in path for path in paths)


def test_create_draft_and_human_approve_is_not_canon_write() -> None:
    client, sink, canon, styles, _ = _client()
    project = _create_project(client)
    before = _canon_fact_count(canon, project["id"])
    draft = _create_guide(client, project["id"])
    assert draft["status"] == "Draft"
    assert draft["POV"] == "林晚"
    assert draft["人称"] == "第三人称限制"
    assert draft["时态"] == "过去进行"
    assert draft["叙述距离"]
    assert draft["语气"]
    assert draft["节奏"]
    assert draft["对话规则"]
    assert draft["词汇偏好"]
    assert draft["禁用表达"]
    assert draft["正例"] == [POSITIVE_EXAMPLE]
    assert draft["反例"] == [NEGATIVE_EXAMPLE]
    assert draft["writes_canon"] is False
    assert draft["is_canon_approval"] is False

    approved = _approve_guide(client, project["id"], draft["id"])
    assert approved["status"] == "Approved"
    assert approved["immutable"] is True
    assert approved["usable"] is True
    assert approved["is_canon"] is False
    assert approved["is_approval"] is False
    assert approved["is_canon_approval"] is False
    assert approved["writes_canon"] is False
    assert approved["auto_approved"] is False
    assert _canon_fact_count(canon, project["id"]) == before
    assert _active_fact_count(canon, project["id"]) == 0
    assert styles.get_guide(draft["id"]) is not None
    actions = [event.action for event in sink.events]
    assert "style_guide.create" in actions
    assert "style_guide.approve" in actions
    assert "canon_fact.create" not in actions
    assert "canon_fact.approve" not in actions
    assert "candidate_change.approve" not in actions
    assert "candidate_change.submit" not in actions
    for event in sink.events:
        if event.resource_type == "style_guide":
            dumped = str(event.after_json)
            assert POSITIVE_EXAMPLE not in dumped
            assert NEGATIVE_EXAMPLE not in dumped
            assert "正例" not in dumped or "positive_example_count" in dumped
            assert event.after_json is not None
            assert "positive_examples" not in event.after_json
            assert "negative_examples" not in event.after_json


def test_non_human_cannot_approve_or_authorize() -> None:
    client, sink, canon, _, _ = _client()
    project = _create_project(client)
    guide = _create_guide(client, project["id"])
    sample = _create_sample(client, project["id"])
    before = _canon_fact_count(canon, project["id"])
    for headers in (GENERATE, REVIEW, SYSTEM):
        denied_guide = client.post(
            f"/projects/{project['id']}/style-guides/{guide['id']}/approve",
            headers=headers,
            json={},
        )
        assert denied_guide.status_code == 403, denied_guide.text
        assert denied_guide.json()["detail"]["error"] == "human_editor_required"
        assert denied_guide.json()["detail"]["writes_canon"] is False
        denied_sample = client.post(
            f"/projects/{project['id']}/style-samples/{sample['id']}/authorize",
            headers=headers,
            json={},
        )
        assert denied_sample.status_code == 403, denied_sample.text
        assert denied_sample.json()["detail"]["error"] == "human_editor_required"
    still_guide = client.get(f"/projects/{project['id']}/style-guides/{guide['id']}")
    assert still_guide.json()["status"] == "Draft"
    still_sample = client.get(f"/projects/{project['id']}/style-samples/{sample['id']}")
    assert still_sample.json()["status"] == "Draft"
    assert _canon_fact_count(canon, project["id"]) == before
    actions = [event.action for event in sink.events]
    assert "style_guide.approve" not in actions
    assert "style_sample.authorize" not in actions


def test_approved_cannot_be_edited_in_place_revise_makes_new_id() -> None:
    client, _, canon, styles, _ = _client()
    project = _create_project(client)
    guide = _approve_guide(
        client, project["id"], _create_guide(client, project["id"])["id"]
    )
    patched = client.patch(
        f"/projects/{project['id']}/style-guides/{guide['id']}",
        headers=HUMAN,
        json={"语气": "改成热情"},
    )
    assert patched.status_code == 409, patched.text
    assert patched.json()["detail"]["error"] == "approved_not_editable_in_place"
    revised = client.post(
        f"/projects/{project['id']}/style-guides/{guide['id']}/revise",
        headers=HUMAN,
        json={"语气": "更冷一层"},
    )
    assert revised.status_code == 200, revised.text
    body = revised.json()
    assert body["id"] != guide["id"]
    assert body["status"] == "Draft"
    assert body["parent_revision_id"] == guide["id"]
    assert body["revision"] == 2
    assert body["语气"] == "更冷一层"
    original = client.get(f"/projects/{project['id']}/style-guides/{guide['id']}")
    assert original.json()["status"] == "Approved"
    assert original.json()["语气"] == "克制、冷而干净"
    assert styles.get_guide(guide["id"]) is not None
    assert styles.get_guide(body["id"]) is not None
    assert _canon_fact_count(canon, project["id"]) == 0

    second_approved = _approve_guide(client, project["id"], body["id"])
    assert second_approved["status"] == "Approved"
    superseded = client.get(f"/projects/{project['id']}/style-guides/{guide['id']}")
    assert superseded.json()["status"] == "Superseded"
    assert superseded.json()["superseded_by_id"] == body["id"]


def test_unapproved_guide_and_unauthorized_sample_cannot_be_referenced() -> None:
    client, _, _, _, drafts = _client()
    project = _create_project(client)
    scene = _create_scene(client, project["id"])
    draft = _seed_draft(drafts, project_id=project["id"], scene_id=scene["id"])
    guide = _create_guide(client, project["id"])
    sample = _create_sample(client, project["id"])
    unapproved = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft.id}/style",
        headers=HUMAN,
        json={"style_guide_revision_id": guide["id"], "style_sample_ids": []},
    )
    assert unapproved.status_code == 409, unapproved.text
    assert unapproved.json()["detail"]["error"] == "style_guide_unapproved"
    unauthorized = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft.id}/style",
        headers=HUMAN,
        json={"style_sample_ids": [sample["id"]]},
    )
    assert unauthorized.status_code == 409, unauthorized.text
    assert unauthorized.json()["detail"]["error"] == "style_sample_unauthorized"
    assert drafts.get_draft(draft.id) is not None
    assert drafts.get_draft(draft.id).style_guide_revision_id is None


def test_version_mismatch_rejected_then_approved_can_be_associated() -> None:
    client, sink, canon, _, drafts = _client()
    project = _create_project(client)
    scene = _create_scene(client, project["id"])
    draft = _seed_draft(drafts, project_id=project["id"], scene_id=scene["id"])
    first = _approve_guide(
        client, project["id"], _create_guide(client, project["id"])["id"]
    )
    sample = _authorize_sample(
        client, project["id"], _create_sample(client, project["id"])["id"]
    )
    next_draft = client.post(
        f"/projects/{project['id']}/style-guides/{first['id']}/revise",
        headers=HUMAN,
        json={},
    ).json()
    second = _approve_guide(client, project["id"], next_draft["id"])

    superseded = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft.id}/style",
        headers=HUMAN,
        json={
            "style_guide_revision_id": first["id"],
            "style_sample_ids": [sample["id"]],
        },
    )
    assert superseded.status_code == 409, superseded.text
    assert superseded.json()["detail"]["error"] == "style_guide_version_mismatch"

    third_draft = client.post(
        f"/projects/{project['id']}/style-guides/{second['id']}/revise",
        headers=HUMAN,
        json={"语气": "再冷一点"},
    ).json()
    not_approved = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft.id}/style",
        headers=HUMAN,
        json={"style_guide_revision_id": third_draft["id"]},
    )
    assert not_approved.status_code == 409, not_approved.text
    assert not_approved.json()["detail"]["error"] == "style_guide_version_mismatch"

    ok = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft.id}/style",
        headers=HUMAN,
        json={
            "style_guide_revision_id": second["id"],
            "style_sample_ids": [sample["id"]],
        },
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["style_guide_revision_id"] == second["id"]
    assert body["style_sample_ids"] == [sample["id"]]
    assert body["writes_canon"] is False
    stored = drafts.get_draft(draft.id)
    assert stored is not None
    assert stored.style_guide_revision_id == second["id"]
    assert stored.body == draft.body
    assert _canon_fact_count(canon, project["id"]) == 0
    actions = [event.action for event in sink.events]
    assert "scene_draft.associate_style" in actions
    for event in sink.events:
        dumped = str(event.after_json)
        assert SAMPLE_BODY not in dumped
        assert POSITIVE_EXAMPLE not in dumped


def test_authorize_sample_and_cannot_edit_authorized_in_place() -> None:
    client, sink, canon, styles, _ = _client()
    project = _create_project(client)
    sample = _create_sample(client, project["id"])
    assert sample["source"] == "主编自写样本"
    assert sample["copyright_mark"] == "已授权自有版权"
    assert sample["scope_of_use"]
    assert sample["approval_status"] == "Draft"
    authorized = _authorize_sample(client, project["id"], sample["id"])
    assert authorized["status"] == "Authorized"
    assert authorized["immutable"] is True
    assert authorized["is_canon_approval"] is False
    assert authorized["writes_canon"] is False
    patched = client.patch(
        f"/projects/{project['id']}/style-samples/{sample['id']}",
        headers=HUMAN,
        json={"body": "试图覆盖已授权样本"},
    )
    assert patched.status_code == 409, patched.text
    assert patched.json()["detail"]["error"] == "authorized_not_editable_in_place"
    revised = client.post(
        f"/projects/{project['id']}/style-samples/{sample['id']}/revise",
        headers=HUMAN,
        json={"body": "新一版样本，河风更冷。"},
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["id"] != sample["id"]
    assert revised.json()["status"] == "Draft"
    assert styles.get_sample(sample["id"]) is not None
    assert styles.get_sample(revised.json()["id"]) is not None
    assert _canon_fact_count(canon, project["id"]) == 0
    for event in sink.events:
        if event.resource_type == "style_sample":
            dumped = str(event.after_json)
            assert SAMPLE_BODY not in dumped
            assert "试图覆盖" not in dumped
            assert "新一版样本" not in dumped
            assert event.after_json is not None
            assert "body" not in event.after_json


def test_fail_and_cancel_keep_records() -> None:
    client, sink, canon, styles, _ = _client()
    project = _create_project(client)
    guide = _create_guide(client, project["id"])
    cancelled = client.post(
        f"/projects/{project['id']}/style-guides/{guide['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "Cancelled"
    kept = client.get(f"/projects/{project['id']}/style-guides/{guide['id']}")
    assert kept.status_code == 200
    assert kept.json()["status"] == "Cancelled"
    assert styles.get_guide(guide["id"]) is not None

    sample = _create_sample(client, project["id"])
    failed = client.post(
        f"/projects/{project['id']}/style-samples/{sample['id']}/fail",
        headers=SYSTEM,
        json={"reason": "save_or_draft_failed"},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "Failed"
    assert styles.get_sample(sample["id"]) is not None
    listed = client.get(f"/projects/{project['id']}/style-samples")
    ids = [item["id"] for item in listed.json()["items"]]
    assert sample["id"] in ids
    assert _canon_fact_count(canon, project["id"]) == 0
    actions = [event.action for event in sink.events]
    assert "style_guide.cancel" in actions
    assert "style_sample.failed" in actions


def test_no_style_scoring_or_extract_or_real_model() -> None:
    client, _, _, _, _ = _client()
    project = _create_project(client)
    assert (
        client.post(f"/projects/{project['id']}/style-score", json={}).status_code
        == 404
    )
    assert client.post(
        f"/projects/{project['id']}/style-guides/extract", json={}
    ).status_code in {404, 405}
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("seed-status" in path for path in paths)
    assert not any("style-score" in path for path in paths)
    package = ROOT / "backend" / "slove_context" / "style"
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in ("openai", "anthropic", "langchain", "chromadb", "pgvector"):
            assert f"import {name}" not in text
            assert f"from {name}" not in text
        assert "auto_approve" not in text or "False" in text
        assert "style_score" not in text
        assert "duplication" not in text


def test_migration_adds_style_tables_without_rebuilding_prior_tables() -> None:
    versions = ROOT / "backend" / "alembic" / "versions"
    create = (versions / "015_create_style_tables.py").read_text(encoding="utf-8")
    assert "CREATE TABLE style_guides" in create
    assert "CREATE TABLE style_samples" in create
    assert "CREATE TABLE outline_revisions" not in create
    assert "CREATE TABLE context_packs" not in create
    assert "CREATE TABLE scene_drafts" not in create
    assert "CREATE TABLE scenes" not in create
    assert "ALTER TABLE scene_drafts" in create
    assert "style_guide_revision_id" in create
    assert 'down_revision: str | None = "014_outline_revisions"' in create
    assert "Approved" in create
    assert "Authorized" in create
    upgrade = create.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    lowered = upgrade.lower()
    assert "vector(" not in lowered
    assert "embedding" not in lowered
    assert "openai" not in lowered
    assert "style_score" not in lowered
