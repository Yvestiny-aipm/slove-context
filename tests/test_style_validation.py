"""Style Validation v1 (node 7.2).

In-memory repositories. No live Postgres. No network. No real models.
Seven deterministic checks each have a unit test. Thresholds are
configurable. LLM check is Fake Provider only and requires an approved
Style Guide. Unauthorized samples and living-author imitation are
refused. Style findings do not write Canon and do not block Canon
submit. 2.1–7.1 APIs and /healthz remain. No review queue (7.3).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.candidate_change.models import (
    CANDIDATE_APPROVED,
    CANDIDATE_SUBMITTED,
)
from slove_context.candidate_change.repository import InMemoryCandidateChangeRepository
from slove_context.canon.models import FACT_ACTIVE
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_draft.context_pack import STATIC_CONTEXT_PACK_ID
from slove_context.scene_draft.models import DRAFT_GENERATED, SceneDraft
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.story.repository import InMemoryStoryRepository
from slove_context.style.models import StyleGuide
from slove_context.style.repository import InMemoryStyleRepository
from slove_context.style_validation.checks import (
    check_dialogue_ratio,
    check_forbidden,
    check_long_sentence_ratio,
    check_paragraph_length,
    check_person,
    check_repeated_ngram,
    check_tense,
    run_deterministic_checks,
)
from slove_context.style_validation.models import (
    LLM_SKIPPED_NO_GUIDE,
    RULE_DIALOGUE,
    RULE_FORBIDDEN,
    RULE_LONG_SENTENCE,
    RULE_NGRAM,
    RULE_PARAGRAPH,
    RULE_PERSON,
    RULE_TENSE,
    RULE_VERSION,
    SEVERITY_WARNING,
    StyleThresholds,
)
from slove_context.style_validation.repository import InMemoryStyleValidationRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}

POSITIVE_EXAMPLE = "她把残玉握进掌心，河风贴着腕骨过去。"
NEGATIVE_EXAMPLE = "哇塞这玉也太酷了吧路人也能触活！"
SAMPLE_BODY = "河滩泥凉。林晚蹲下去，指节碰到一点冷光。"
DRAFT_OK = "河滩风冷，林晚看见一点光。她已经拾起残玉。"
DRAFT_DRIFT = (
    "我走在河滩上将要推开祠门。哇塞这玉也太酷了。"
    + "河风贴着腕骨" * 5
    + "。"
    + "「你好吗？你看见了吗？你也来吗？」" * 4
)


def _client(
    *, auto_run: bool = True
) -> tuple[
    TestClient,
    InMemoryAuditSink,
    InMemoryCanonRepository,
    InMemoryStyleRepository,
    InMemorySceneDraftRepository,
    InMemoryStyleValidationRepository,
]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    canon = InMemoryCanonRepository()
    styles = InMemoryStyleRepository()
    drafts = InMemorySceneDraftRepository()
    validations = InMemoryStyleValidationRepository()
    app = create_app(
        repository=InMemoryStoryRepository(),
        canon_repository=canon,
        scene_repository=InMemorySceneRepository(),
        scene_draft_repository=drafts,
        candidate_change_repository=InMemoryCandidateChangeRepository(),
        style_repository=styles,
        style_validation_repository=validations,
        audit_writer=writer,
        llm_gateway=LlmGateway(
            FakeProvider(),
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
        style_validation_auto_run=auto_run,
    )
    return TestClient(app), sink, canon, styles, drafts, validations


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


def _seed_draft(
    drafts: InMemorySceneDraftRepository,
    *,
    project_id: str,
    scene_id: str,
    body: str = DRAFT_OK,
) -> SceneDraft:
    draft = SceneDraft(
        id=str(uuid4()),
        project_id=project_id,
        scene_id=scene_id,
        job_id=str(uuid4()),
        revision=1,
        status=DRAFT_GENERATED,
        body=body,
        content_hash="hash-ref",
        character_count=len(body),
        word_count_estimate=max(1, len(body) // 2),
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


def _trigger_url(project_id: str, scene_id: str, revision_id: str) -> str:
    return (
        f"/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}"
        "/style-validations"
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


def _guide() -> StyleGuide:
    return StyleGuide(
        id="guide-1",
        project_id="project-1",
        lineage_id="line-1",
        revision=1,
        status="Approved",
        created_at="2026-08-18T00:00:00.000000Z",
        created_by="主编",
        actor_type="human_editor",
        person="第三人称限制",
        tense="过去进行",
        forbidden_expressions=["哇塞", "太酷了"],
        positive_examples=[POSITIVE_EXAMPLE],
        negative_examples=[NEGATIVE_EXAMPLE],
    )


def test_person_detects_narrative_drift() -> None:
    finding = check_person("我走在河滩上，风很冷。", "第三人称限制")
    assert finding is not None
    assert finding.rule_id == RULE_PERSON
    assert finding.severity == SEVERITY_WARNING
    assert finding.problem
    assert "我" in finding.text_evidence
    assert finding.minimal_fix
    assert check_person("她走在河滩上，风很冷。", "第三人称限制") is None
    assert check_person("她停住。「我走在河滩上。」河风过去。", "第三人称限制") is None


def test_tense_detects_marker_drift() -> None:
    finding = check_tense("她将要拾起残玉，即将推开祠门。", "过去进行")
    assert finding is not None
    assert finding.rule_id == RULE_TENSE
    assert finding.severity == SEVERITY_WARNING
    assert finding.problem
    assert finding.text_evidence
    assert finding.minimal_fix
    assert check_tense("她已经拾起残玉，那时河风正冷。", "过去进行") is None


def test_forbidden_literal_and_normalized_match() -> None:
    findings = check_forbidden("哇塞这玉也太酷了", ["哇塞", "太酷了"])
    assert {item.rule_id for item in findings} == {RULE_FORBIDDEN}
    assert {item.text_evidence for item in findings} == {"哇塞", "太酷了"}
    assert all(item.severity == SEVERITY_WARNING for item in findings)
    assert all(item.minimal_fix and item.problem for item in findings)
    spaced = check_forbidden("哇 塞 这玉发亮", ["哇塞"])
    assert len(spaced) == 1
    assert check_forbidden("河滩风冷。", ["哇塞"]) == []


def test_long_sentence_ratio_threshold_is_configurable() -> None:
    short = "她走了。风很冷。残玉发光。"
    long = "她" + "走" * 100 + "。"
    mixed = "短。" + "她" + "走" * 100 + "。"
    tight = StyleThresholds(long_sentence_chars=20, long_sentence_ratio=0.3)
    loose = StyleThresholds(long_sentence_chars=20, long_sentence_ratio=0.99)
    assert check_long_sentence_ratio(short, tight) is None
    finding = check_long_sentence_ratio(long, tight)
    assert finding is not None
    assert finding.rule_id == RULE_LONG_SENTENCE
    assert finding.severity == SEVERITY_WARNING
    assert finding.minimal_fix
    assert check_long_sentence_ratio(mixed, loose) is None
    assert check_long_sentence_ratio(mixed, tight) is not None


def test_paragraph_length_threshold_is_configurable() -> None:
    long_p = "她" * 300
    short_p = "她走了。\n风很冷。"
    tight = StyleThresholds(max_paragraph_chars=80, long_paragraph_ratio=0.0)
    loose = StyleThresholds(max_paragraph_chars=80, long_paragraph_ratio=0.8)
    mixed = "短段。\n" + ("她" * 300)
    finding = check_paragraph_length(long_p, tight)
    assert finding is not None
    assert finding.rule_id == RULE_PARAGRAPH
    assert finding.severity == SEVERITY_WARNING
    assert finding.minimal_fix
    assert check_paragraph_length(short_p, tight) is None
    assert check_paragraph_length(mixed, loose) is None
    assert check_paragraph_length(mixed, tight) is not None


def test_dialogue_ratio_threshold_is_configurable() -> None:
    heavy = "「你好吗？」" * 6
    narrative = "她走在河滩上，风很冷，残玉发光。"
    tight = StyleThresholds(max_dialogue_ratio=0.3)
    loose = StyleThresholds(max_dialogue_ratio=0.95)
    finding = check_dialogue_ratio(heavy, tight)
    assert finding is not None
    assert finding.rule_id == RULE_DIALOGUE
    assert finding.severity == SEVERITY_WARNING
    assert finding.minimal_fix
    assert check_dialogue_ratio(narrative, tight) is None
    assert check_dialogue_ratio(heavy, loose) is None


def test_repeated_ngram_threshold_is_configurable() -> None:
    repeated = "河风贴着腕骨" * 5
    unique = "河风贴着腕骨她低头看见一点冷光。"
    tight = StyleThresholds(ngram_n=4, ngram_repeat_threshold=3)
    loose = StyleThresholds(ngram_n=4, ngram_repeat_threshold=20)
    finding = check_repeated_ngram(repeated, tight)
    assert finding is not None
    assert finding.rule_id == RULE_NGRAM
    assert finding.severity == SEVERITY_WARNING
    assert finding.minimal_fix
    assert "河风" in finding.text_evidence or finding.text_evidence
    assert check_repeated_ngram(unique, tight) is None
    assert check_repeated_ngram(repeated, loose) is None


def test_run_deterministic_checks_do_not_default_to_blocker() -> None:
    findings = run_deterministic_checks(DRAFT_DRIFT, guide=_guide())
    assert findings
    assert all(item.severity == SEVERITY_WARNING for item in findings)
    assert {item.rule_id for item in findings} >= {
        RULE_PERSON,
        RULE_TENSE,
        RULE_FORBIDDEN,
    }


def test_healthz_and_prior_apis_remain() -> None:
    client, _, _, _, _, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/version").json().get("version")
    paths = client.get("/openapi.json").json()["paths"]
    assert "/healthz" in paths
    assert "/version" in paths
    assert "/projects/{project_id}/specs/{spec_id}/approve" in paths
    assert "/projects/{project_id}/canon-facts" in paths
    assert "/projects/{project_id}/canon-snapshots/{snapshot_id}/freeze" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/approve" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/drafts/jobs" in paths
    assert "/projects/{project_id}/validation-runs" in paths
    assert "/projects/{project_id}/repair-tasks" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/context-packs" in paths
    assert "/projects/{project_id}/outline-revisions" in paths
    assert "/projects/{project_id}/style-guides" in paths
    assert "/projects/{project_id}/style-samples" in paths
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/style" in paths
    )
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}"
        "/style-validations" in paths
    )
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/style-score" not in paths
    assert "/projects/{project_id}/review-queue" not in paths
    assert "/projects/{project_id}/auto-approve" not in paths
    assert not any("seed-status" in path for path in paths)
    assert not any("review-queue" in path for path in paths)


def test_report_persists_versions_and_does_not_write_canon() -> None:
    client, sink, canon, _, drafts, validations = _client()
    project = _create_project(client)
    scene = _create_scene(client, project["id"])
    guide = _approve_guide(
        client, project["id"], _create_guide(client, project["id"])["id"]
    )
    draft = _seed_draft(
        drafts, project_id=project["id"], scene_id=scene["id"], body=DRAFT_DRIFT
    )
    before = _canon_fact_count(canon, project["id"])
    response = client.post(
        _trigger_url(project["id"], scene["id"], draft.id),
        headers=HUMAN,
        json={
            "style_guide_revision_id": guide["id"],
            "include_llm": True,
            "created_by": "主编",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "Succeeded"
    assert body["rule_version"] == RULE_VERSION
    assert body["llm_score_version"] == "style-llm.v1"
    assert body["llm_status"] == "ran"
    assert body["blocks_canon_submit"] is False
    assert body["writes_canon"] is False
    assert body["is_canon"] is False
    assert body["is_validation_run"] is False
    assert body["is_review_queue"] is False
    assert body["report"]["rule_version"] == RULE_VERSION
    assert body["report"]["blocks_canon_submit"] is False
    assert body["findings"]
    for finding in body["findings"]:
        assert finding["problem"]
        assert "text_evidence" in finding
        assert finding["severity"] in {"warning", "info"}
        assert finding["minimal_fix"]
        assert finding["blocks_canon_submit"] is False
        assert finding["severity"] != "blocker"
    fetched = client.get(
        _trigger_url(project["id"], scene["id"], draft.id) + f"/{body['id']}"
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == body["id"]
    assert fetched.json()["report"]["findings"]
    listed = client.get(_trigger_url(project["id"], scene["id"], draft.id))
    assert listed.status_code == 200
    assert any(item["id"] == body["id"] for item in listed.json()["items"])
    assert validations.get(body["id"]) is not None
    assert _canon_fact_count(canon, project["id"]) == before
    assert _active_fact_count(canon, project["id"]) == 0
    actions = [event.action for event in sink.events]
    assert "style_validation.create" in actions
    assert "style_validation.succeeded" in actions
    assert "canon_fact.create" not in actions
    assert "canon_fact.approve" not in actions
    assert "candidate_change.submit" not in actions
    for event in sink.events:
        if event.resource_type == "style_validation":
            dumped = str(event.after_json)
            assert DRAFT_DRIFT not in dumped
            assert POSITIVE_EXAMPLE not in dumped
            assert NEGATIVE_EXAMPLE not in dumped
            assert SAMPLE_BODY not in dumped
            assert "哇塞" not in dumped
            assert event.after_json is not None
            assert "findings" not in event.after_json
            assert event.after_json["blocks_canon_submit"] is False
            assert event.after_json["writes_canon"] is False


def test_unapproved_guide_cannot_be_used_for_llm_check() -> None:
    client, _, canon, _, drafts, _ = _client()
    project = _create_project(client)
    scene = _create_scene(client, project["id"])
    draft = _seed_draft(drafts, project_id=project["id"], scene_id=scene["id"])
    guide = _create_guide(client, project["id"])
    before = _canon_fact_count(canon, project["id"])
    response = client.post(
        _trigger_url(project["id"], scene["id"], draft.id),
        headers=HUMAN,
        json={
            "style_guide_revision_id": guide["id"],
            "include_llm": True,
        },
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "style_guide_unapproved"
    assert detail["llm_status"] == "refused_unapproved_guide"
    assert _canon_fact_count(canon, project["id"]) == before


def test_unauthorized_sample_cannot_be_used() -> None:
    client, _, canon, _, drafts, _ = _client()
    project = _create_project(client)
    scene = _create_scene(client, project["id"])
    draft = _seed_draft(drafts, project_id=project["id"], scene_id=scene["id"])
    sample = _create_sample(client, project["id"])
    response = client.post(
        _trigger_url(project["id"], scene["id"], draft.id),
        headers=HUMAN,
        json={"style_sample_ids": [sample["id"]], "include_llm": True},
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "style_sample_unauthorized"
    assert detail["llm_status"] == "refused_unauthorized_sample"
    assert _canon_fact_count(canon, project["id"]) == 0


def test_living_author_imitation_is_refused() -> None:
    client, _, _, _, drafts, _ = _client()
    project = _create_project(client)
    scene = _create_scene(client, project["id"])
    draft = _seed_draft(drafts, project_id=project["id"], scene_id=scene["id"])
    response = client.post(
        _trigger_url(project["id"], scene["id"], draft.id),
        headers=HUMAN,
        json={"include_llm": True, "living_author": "某在世作家"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "living_author_imitation_forbidden"
    sample = _create_sample(
        client,
        project["id"],
        source="仿写在世作家样本",
        copyright_mark="未授权",
        scope_of_use="模仿在世名家",
    )
    # Unauthorized first; living-author sample is also refused after authorize.
    authorize = client.post(
        f"/projects/{project['id']}/style-samples/{sample['id']}/authorize",
        headers=HUMAN,
        json={},
    )
    assert authorize.status_code == 200, authorize.text
    living = client.post(
        _trigger_url(project["id"], scene["id"], draft.id),
        headers=HUMAN,
        json={"style_sample_ids": [sample["id"]], "include_llm": True},
    )
    assert living.status_code == 409, living.text
    assert living.json()["detail"]["error"] == "living_author_imitation_forbidden"


def test_llm_skips_without_approved_guide() -> None:
    client, _, canon, _, drafts, _ = _client()
    project = _create_project(client)
    scene = _create_scene(client, project["id"])
    draft = _seed_draft(drafts, project_id=project["id"], scene_id=scene["id"])
    response = client.post(
        _trigger_url(project["id"], scene["id"], draft.id),
        headers=HUMAN,
        json={"include_llm": True},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "Succeeded"
    assert body["llm_status"] == LLM_SKIPPED_NO_GUIDE
    assert body["llm_score_version"] is None
    assert body["blocks_canon_submit"] is False
    assert _canon_fact_count(canon, project["id"]) == 0


def test_fail_and_cancel_keep_records() -> None:
    client, sink, canon, _, drafts, validations = _client(auto_run=False)
    project = _create_project(client)
    scene = _create_scene(client, project["id"])
    draft = _seed_draft(drafts, project_id=project["id"], scene_id=scene["id"])
    queued = client.post(
        _trigger_url(project["id"], scene["id"], draft.id),
        headers=HUMAN,
        json={"include_llm": False},
    )
    assert queued.status_code == 201, queued.text
    assert queued.json()["status"] == "Queued"
    cancelled = client.post(
        _trigger_url(project["id"], scene["id"], draft.id)
        + f"/{queued.json()['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "Cancelled"
    kept = client.get(
        _trigger_url(project["id"], scene["id"], draft.id) + f"/{queued.json()['id']}"
    )
    assert kept.status_code == 200
    assert kept.json()["status"] == "Cancelled"
    assert validations.get(queued.json()["id"]) is not None
    assert _canon_fact_count(canon, project["id"]) == 0
    assert "style_validation.cancel" in [event.action for event in sink.events]

    fail_client, fail_sink, fail_canon, _, fail_drafts, fail_repo = _client()
    fail_project = _create_project(fail_client)
    fail_scene = _create_scene(fail_client, fail_project["id"])
    fail_draft = _seed_draft(
        fail_drafts, project_id=fail_project["id"], scene_id=fail_scene["id"]
    )
    fail_repo.force_fail = True
    failed = fail_client.post(
        _trigger_url(fail_project["id"], fail_scene["id"], fail_draft.id),
        headers=HUMAN,
        json={"include_llm": False},
    )
    assert failed.status_code == 201, failed.text
    assert failed.json()["status"] == "Failed"
    assert failed.json()["failure_reason"]
    assert fail_repo.get(failed.json()["id"]) is not None
    listed = fail_client.get(
        _trigger_url(fail_project["id"], fail_scene["id"], fail_draft.id)
    )
    ids = [item["id"] for item in listed.json()["items"]]
    assert failed.json()["id"] in ids
    assert _canon_fact_count(fail_canon, fail_project["id"]) == 0
    assert "style_validation.failed" in [event.action for event in fail_sink.events]


def test_style_findings_do_not_block_canon_submit() -> None:
    client, sink, canon, _, drafts, _ = _client()
    project = _create_project(client)
    scene = _create_scene(client, project["id"])
    approved_scene = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved_scene.status_code == 200, approved_scene.text
    guide = _approve_guide(
        client, project["id"], _create_guide(client, project["id"])["id"]
    )
    style_draft = _seed_draft(
        drafts, project_id=project["id"], scene_id=scene["id"], body=DRAFT_DRIFT
    )
    style_run = client.post(
        _trigger_url(project["id"], scene["id"], style_draft.id),
        headers=HUMAN,
        json={"style_guide_revision_id": guide["id"], "include_llm": False},
    )
    assert style_run.status_code == 201, style_run.text
    assert style_run.json()["findings"]
    assert style_run.json()["blocks_canon_submit"] is False
    assert style_run.json()["is_validation_run"] is False

    snapshot = client.post(
        f"/projects/{project['id']}/canon-snapshots",
        headers=HUMAN,
        json={
            "as_of_scene_seq": 1,
            "as_of_story_time": "day-01",
            "created_by": "主编",
        },
    )
    assert snapshot.status_code == 201, snapshot.text
    plan_job = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot.json()["id"]},
    )
    assert plan_job.status_code == 201, plan_job.text
    plan = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/plans/current")
    assert plan.status_code == 200, plan.text
    draft_job = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json={
            "snapshot_id": snapshot.json()["id"],
            "plan_id": plan.json()["plan"]["id"],
            "context_pack_id": STATIC_CONTEXT_PACK_ID,
        },
    )
    assert draft_job.status_code == 201, draft_job.text
    extracted = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts"
        f"/{draft_job.json()['draft_id']}/extract-jobs",
        headers=GENERATE,
        json={},
    )
    assert extracted.status_code == 201, extracted.text
    listed = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/candidate-changes"
    )
    assert listed.status_code == 200, listed.text
    candidate = listed.json()["items"][0]
    repo = client.app.state.candidate_change_repository
    item = repo.get_candidate(candidate["id"])
    assert item is not None
    assert item.status not in {CANDIDATE_APPROVED, CANDIDATE_SUBMITTED}
    item.status = "AwaitingVerdict"
    item.payload["status"] = "AwaitingVerdict"
    repo.save_candidate(item)
    approved = client.post(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}/approve",
        headers=HUMAN,
        json={
            "created_by": "主编",
            "reason": "风格发现默认不阻断提交；仍须主编提交才写 Canon。",
        },
    )
    assert approved.status_code == 200, approved.text
    facts_before = _canon_fact_count(canon, project["id"])
    submitted = client.post(
        f"/projects/{project['id']}/candidate-changes/{candidate['id']}/submit",
        headers=HUMAN,
        json={"created_by": "主编"},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["candidate"]["status"] == "Submitted"
    assert _canon_fact_count(canon, project["id"]) == facts_before + 1
    reread = client.get(
        _trigger_url(project["id"], scene["id"], style_draft.id)
        + f"/{style_run.json()['id']}"
    )
    assert reread.json()["blocks_canon_submit"] is False
    assert reread.json()["writes_canon"] is False
    assert "candidate_change.submit" in [event.action for event in sink.events]


def test_does_not_change_hard_validation_or_generate_job() -> None:
    validation_rules = (
        ROOT / "backend" / "slove_context" / "validation" / "rules.py"
    ).read_text(encoding="utf-8")
    assert "style_validation" not in validation_rules
    assert "blocks_canon_submit" not in validation_rules
    draft_service = (
        ROOT / "backend" / "slove_context" / "scene_draft" / "service.py"
    ).read_text(encoding="utf-8")
    assert "style_validation" not in draft_service
    package = ROOT / "backend" / "slove_context" / "style_validation"
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in ("openai", "anthropic", "langchain", "chromadb", "pgvector"):
            assert f"import {name}" not in text
            assert f"from {name}" not in text
        assert "auto_approve" not in text or "False" in text


def test_migration_adds_style_validations_without_rebuilding_prior_tables() -> None:
    versions = ROOT / "backend" / "alembic" / "versions"
    create = (versions / "016_create_style_validations.py").read_text(encoding="utf-8")
    assert "CREATE TABLE style_validations" in create
    assert "blocks_canon_submit" in create
    assert "rule_version" in create
    assert "CREATE TABLE style_guides" not in create
    assert "CREATE TABLE scene_drafts" not in create
    assert "CREATE TABLE validation_runs" not in create
    assert "CREATE TABLE outline_revisions" not in create
    assert 'down_revision: str | None = "015_style"' in create
    upgrade = create.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    lowered = upgrade.lower()
    assert "vector(" not in lowered
    assert "embedding" not in lowered
    assert "openai" not in lowered
    assert "review_queue" not in lowered
