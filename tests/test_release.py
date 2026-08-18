"""Release gates and formal book export (node 9.3).

In-memory repositories. No live Postgres. No network. No real models.
Eight read-only gates. Formal export only when all pass. Manifest is
immutable. Release does not write Canon or approve. 2.1–9.2 APIs remain.
No production seed-status. 9.1 expected files and 9.2 history stay
unchanged.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditEvent, AuditWriter, InMemoryAuditSink
from slove_context.candidate_change.models import (
    CANDIDATE_APPROVED,
    CANDIDATE_EXTRACTED,
    CANDIDATE_FAILED_VALIDATION,
    CANDIDATE_REJECTED,
    CANDIDATE_SUBMITTED,
    CandidateChange,
)
from slove_context.candidate_change.repository import InMemoryCandidateChangeRepository
from slove_context.canon.models import SNAPSHOT_FROZEN, SNAPSHOT_UNFROZEN, CanonSnapshot
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.release.models import (
    GATE_AUDIT_COMPLETE,
    GATE_CANDIDATES_RESOLVED,
    GATE_CHAPTER_SUMMARIES,
    GATE_DRAFTS_APPROVED,
    GATE_FORESHADOWING,
    GATE_IDS,
    GATE_NO_UNHANDLED_BLOCKERS,
    GATE_SNAPSHOT_FROZEN,
    GATE_STYLE_AND_SAFETY,
    stable_hash,
)
from slove_context.release.repository import InMemoryReleaseRepository
from slove_context.repair.repository import InMemoryRepairRepository
from slove_context.review_queue.models import (
    STATUS_APPROVED,
    SUBJECT_SCENE_DRAFT,
    ReviewQueueItem,
)
from slove_context.review_queue.repository import InMemoryReviewQueueRepository
from slove_context.scene.models import (
    SCENE_APPROVED,
    SCENE_CARD_READY,
    Arc,
    Chapter,
    Scene,
)
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_draft.models import DRAFT_GENERATED, SceneDraft
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.story.models import PROJECT_ACTIVE, StoryProject
from slove_context.story.repository import InMemoryStoryRepository
from slove_context.style_validation.models import RUN_SUCCEEDED, StyleValidation
from slove_context.style_validation.repository import InMemoryStyleValidationRepository
from slove_context.summary.models import SUMMARY_GENERATED, ChapterSummary
from slove_context.summary.repository import InMemorySummaryRepository
from slove_context.validation.models import (
    ACTION_HUMAN_REJECT,
    OUTCOME_RULE_FAILED,
    SEVERITY_BLOCKING,
    ValidationReport,
    Violation,
)
from slove_context.validation.repository import InMemoryValidationRepository

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
SYSTEM = {"X-Actor-Type": "system", "X-Actor-Id": "sys-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}
NOW = "2026-08-18T00:00:00Z"
PROSE = "河滩风冷，林晚看见一点光，伸手拾起残玉。"


class DropSink:
    """Writes are discarded. The trail cannot be replayed."""

    def write(self, event: AuditEvent) -> None:
        del event


def _client(
    *,
    sink: InMemoryAuditSink | DropSink | None = None,
    writer: AuditWriter | None = None,
    story: InMemoryStoryRepository | None = None,
    canon: InMemoryCanonRepository | None = None,
    scenes: InMemorySceneRepository | None = None,
    drafts: InMemorySceneDraftRepository | None = None,
    candidates: InMemoryCandidateChangeRepository | None = None,
    validations: InMemoryValidationRepository | None = None,
    repairs: InMemoryRepairRepository | None = None,
    summaries: InMemorySummaryRepository | None = None,
    styles: InMemoryStyleValidationRepository | None = None,
    reviews: InMemoryReviewQueueRepository | None = None,
    release: InMemoryReleaseRepository | None = None,
) -> tuple[TestClient, Any, InMemoryCanonRepository, InMemoryReleaseRepository]:
    audit_sink: Any = sink if sink is not None else InMemoryAuditSink()
    audit = writer or AuditWriter(audit_sink)
    canon_repo = canon or InMemoryCanonRepository()
    release_repo = release or InMemoryReleaseRepository()
    app = create_app(
        repository=story or InMemoryStoryRepository(),
        canon_repository=canon_repo,
        scene_repository=scenes or InMemorySceneRepository(),
        scene_draft_repository=drafts or InMemorySceneDraftRepository(),
        candidate_change_repository=candidates or InMemoryCandidateChangeRepository(),
        validation_repository=validations or InMemoryValidationRepository(),
        repair_repository=repairs or InMemoryRepairRepository(),
        summary_repository=summaries or InMemorySummaryRepository(),
        style_validation_repository=styles or InMemoryStyleValidationRepository(),
        review_queue_repository=reviews or InMemoryReviewQueueRepository(),
        release_repository=release_repo,
        audit_writer=audit,
    )
    return TestClient(app), audit_sink, canon_repo, release_repo


def _world(
    *,
    approve_draft: bool = True,
    snapshot_frozen: bool = True,
    chapter_summary: bool = True,
    style: bool = True,
    safety: bool = True,
    leftover_approved: bool = False,
    blocking: bool = False,
    due_open: bool = False,
    audit: bool = True,
    drop_audit: bool = False,
) -> dict[str, Any]:
    story = InMemoryStoryRepository()
    canon = InMemoryCanonRepository()
    scenes = InMemorySceneRepository()
    drafts = InMemorySceneDraftRepository()
    candidates = InMemoryCandidateChangeRepository()
    validations = InMemoryValidationRepository()
    repairs = InMemoryRepairRepository()
    summaries = InMemorySummaryRepository()
    styles = InMemoryStyleValidationRepository()
    reviews = InMemoryReviewQueueRepository()
    release = InMemoryReleaseRepository()
    sink: Any = DropSink() if drop_audit else InMemoryAuditSink()
    writer = AuditWriter(sink)

    project = StoryProject(
        id=str(uuid4()),
        title="青石夜祠",
        language="zh-CN",
        status=PROJECT_ACTIVE,
        created_at=NOW,
        created_by="editor-1",
    )
    story.add_project(project)
    arc = Arc(
        id=str(uuid4()),
        project_id=project.id,
        title="七日寻祠",
        sort_order=1,
        created_at=NOW,
        created_by="editor-1",
    )
    scenes.add_arc(arc)
    chapter = Chapter(
        id=str(uuid4()),
        project_id=project.id,
        arc_id=arc.id,
        title="得玉",
        sort_order=1,
        created_at=NOW,
        created_by="editor-1",
    )
    scenes.add_chapter(chapter)
    scene = Scene(
        id=str(uuid4()),
        project_id=project.id,
        chapter_id=chapter.id,
        scene_card_id=str(uuid4()),
        story_order=1,
        status=SCENE_APPROVED,
        scene_status=SCENE_CARD_READY,
        pov="林晚",
        story_time="第一日黄昏",
        location="青石镇河滩",
        present_entities=["林晚"],
        starting_state="空手",
        goal="拾玉",
        conflict="夜色",
        expected_end_state="持玉",
        forbidden=["禁止写出残玉来历"],
        knowledge_boundaries=["林晚不知残玉能开门"],
        generation_boundary="只写这一场",
        scene_card={"schema_version": "0.4.0"},
        created_at=NOW,
        created_by="editor-1",
    )
    scenes.add_scene(scene)
    snapshot = CanonSnapshot(
        id=str(uuid4()),
        project_id=project.id,
        created_at=NOW,
        created_by="editor-1",
        fact_ids=[],
        status=SNAPSHOT_FROZEN if snapshot_frozen else SNAPSHOT_UNFROZEN,
        frozen_at=NOW if snapshot_frozen else None,
    )
    canon.add_snapshot(snapshot)
    draft = SceneDraft(
        id=str(uuid4()),
        project_id=project.id,
        scene_id=scene.id,
        job_id=str(uuid4()),
        revision=1,
        status=DRAFT_GENERATED,
        body=PROSE,
        content_hash="draft-hash-1",
        character_count=len(PROSE),
        word_count_estimate=12,
        generation_model="fake-model",
        prompt_version="scene_draft.v1",
        generated_at=NOW,
        scene_card_id=scene.scene_card_id,
        plan_id=str(uuid4()),
        snapshot_id=snapshot.id,
        context_pack_id="static-context-pack",
        created_at=NOW,
        created_by="editor-1",
    )
    drafts.add_draft(draft)
    if approve_draft:
        reviews.add_item(
            ReviewQueueItem(
                id=str(uuid4()),
                project_id=project.id,
                subject_type=SUBJECT_SCENE_DRAFT,
                subject_id=draft.id,
                status=STATUS_APPROVED,
                created_at=NOW,
                updated_at=NOW,
                created_by="editor-1",
                actor_type="human_editor",
                scene_id=scene.id,
                chapter_id=chapter.id,
            )
        )
    candidate_status = CANDIDATE_APPROVED if leftover_approved else CANDIDATE_SUBMITTED
    if blocking:
        candidate_status = CANDIDATE_FAILED_VALIDATION
    candidate = CandidateChange(
        id=str(uuid4()),
        project_id=project.id,
        scene_id=scene.id,
        draft_id=draft.id,
        job_id=str(uuid4()),
        extract_batch=1,
        schema_version="0.4.0",
        subject="林晚",
        predicate="holds",
        object="残玉",
        value="残玉",
        effective_story_time="第一日黄昏",
        source_scene_id=scene.id,
        evidence_quote="伸手拾起残玉",
        confidence=0.9,
        status=candidate_status,
        created_at=NOW,
        created_by="editor-1",
        payload={"id": "cand-1", "schema_version": "0.4.0"},
    )
    if leftover_approved:
        candidate.status = CANDIDATE_APPROVED
    candidates.add_candidate(candidate)
    if blocking:
        report = ValidationReport(
            id=str(uuid4()),
            project_id=project.id,
            scene_id=scene.id,
            candidate_change_ids=[candidate.id],
            outcome=OUTCOME_RULE_FAILED,
            violations=[
                Violation(
                    rule_id="canon-active-conflict",
                    severity=SEVERITY_BLOCKING,
                    entity_ids=["ent-1"],
                    source_evidence="quote",
                    canon_evidence="canon",
                    recommended_action=ACTION_HUMAN_REJECT,
                )
            ],
            schema_version="0.4.0",
            created_at=NOW,
            created_by="editor-1",
            payload={"outcome": OUTCOME_RULE_FAILED},
            run_id=str(uuid4()),
        )
        validations.add_report(report)
    if chapter_summary:
        summaries.add_chapter_summary(
            ChapterSummary(
                id=str(uuid4()),
                project_id=project.id,
                chapter_id=chapter.id,
                job_id=str(uuid4()),
                revision=1,
                status=SUMMARY_GENERATED,
                body="本章林晚得玉。",
                content_hash="chapter-hash-1",
                source_scene_summary_revision_ids=[],
                prompt_version="chapter_summary.v1",
                generated_at=NOW,
                generation_model="fake-model",
                created_at=NOW,
                created_by="editor-1",
            )
        )
    if style:
        styles.add(
            StyleValidation(
                id=str(uuid4()),
                project_id=project.id,
                scene_id=scene.id,
                draft_revision_id=draft.id,
                status=RUN_SUCCEEDED,
                created_at=NOW,
                updated_at=NOW,
                created_by="editor-1",
                actor_type="human_editor",
            )
        )
    if audit and not drop_audit:
        writer.write(
            actor_type="human_editor",
            actor_id="editor-1",
            action="story_project.create",
            resource_type="story_project",
            resource_id=project.id,
            after_json={"project_id": project.id, "title": "青石夜祠"},
        )
    client, used_sink, _, used_release = _client(
        sink=sink,
        writer=writer,
        story=story,
        canon=canon,
        scenes=scenes,
        drafts=drafts,
        candidates=candidates,
        validations=validations,
        repairs=repairs,
        summaries=summaries,
        styles=styles,
        reviews=reviews,
        release=release,
    )
    if safety:
        recorded = client.post(
            f"/projects/{project.id}/release-safety-checks",
            headers=HUMAN,
            json={"result": "placeholder_ok"},
        )
        assert recorded.status_code == 201, recorded.text
    if due_open:
        due = client.post(
            f"/projects/{project.id}/release-due-items",
            headers=HUMAN,
            json={"title": "河滩缺口须在后文回收", "scene_id": scene.id},
        )
        assert due.status_code == 201, due.text
    return {
        "client": client,
        "sink": used_sink,
        "canon": canon,
        "release": used_release,
        "project_id": project.id,
        "scene_id": scene.id,
        "chapter_id": chapter.id,
        "snapshot_id": snapshot.id,
        "draft_id": draft.id,
        "candidate_id": candidate.id,
        "writer": writer,
    }


def _run_check(world: dict[str, Any], **overrides: object) -> Any:
    payload = {
        "snapshot_id": world["snapshot_id"],
        "scene_ids": [world["scene_id"]],
        "chapter_ids": [world["chapter_id"]],
        "created_by": "editor-1",
    }
    payload.update(overrides)
    return world["client"].post(
        f"/projects/{world['project_id']}/release-checks",
        headers=HUMAN,
        json=payload,
    )


def _failed_gate(body: dict[str, Any], gate_id: str) -> dict[str, Any] | None:
    for item in body.get("failures", []):
        if item.get("gate_id") == gate_id:
            return item
    return None


def test_each_gate_fails_in_isolation() -> None:
    cases = (
        ({"approve_draft": False}, GATE_DRAFTS_APPROVED, "draft_not_human_approved"),
        (
            {"blocking": True},
            GATE_NO_UNHANDLED_BLOCKERS,
            "unhandled_blocking_violation",
        ),
        (
            {"leftover_approved": True},
            GATE_CANDIDATES_RESOLVED,
            "approved_not_submitted",
        ),
        ({"snapshot_frozen": False}, GATE_SNAPSHOT_FROZEN, "snapshot_not_frozen"),
        ({"chapter_summary": False}, GATE_CHAPTER_SUMMARIES, "chapter_summary_missing"),
        ({"due_open": True}, GATE_FORESHADOWING, "due_foreshadowing_unhandled"),
        ({"style": False}, GATE_STYLE_AND_SAFETY, "style_check_missing"),
        ({"safety": False}, GATE_STYLE_AND_SAFETY, "safety_check_missing"),
        ({"drop_audit": True}, GATE_AUDIT_COMPLETE, "audit_not_replayable"),
    )
    for overrides, gate_id, code in cases:
        world = _world(**overrides)
        response = _run_check(world)
        assert response.status_code == 201, (overrides, response.text)
        body = response.json()
        assert body["status"] == "failed"
        assert body["passed"] is False
        assert body["is_formal_release"] is False
        assert body["writes_canon"] is False
        assert [item["gate_id"] for item in body["gates"]] == list(GATE_IDS)
        failure = _failed_gate(body, gate_id)
        assert failure is not None, (overrides, body["failures"])
        assert failure["code"] == code
        failed_ids = {item["gate_id"] for item in body["failures"]}
        assert failed_ids == {gate_id}, (overrides, body["failures"])
        blocked = world["client"].post(
            f"/projects/{world['project_id']}/release-checks/{body['id']}/export",
            headers=HUMAN,
            json={"format": "json"},
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["error"] == "formal_export_blocked"
        assert blocked.json()["detail"]["failures"]
        manifest = world["client"].get(
            f"/projects/{world['project_id']}/release-checks/{body['id']}/manifest"
        )
        assert manifest.status_code == 409
        assert world["release"].get_check(body["id"]) is not None


def test_export_only_when_all_eight_pass() -> None:
    world = _world()
    response = _run_check(world)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "passed"
    assert body["passed"] is True
    assert body["is_formal_release"] is True
    assert body["manifest_id"]
    assert all(item["passed"] for item in body["gates"])
    assert body["failures"] == []
    markdown = world["client"].post(
        f"/projects/{world['project_id']}/release-checks/{body['id']}/export",
        headers=HUMAN,
        json={"format": "markdown"},
    )
    assert markdown.status_code == 201, markdown.text
    md = markdown.json()
    assert md["is_formal_release"] is True
    assert md["generates_prose"] is False
    assert PROSE in md["markdown"]
    json_export = world["client"].post(
        f"/projects/{world['project_id']}/release-checks/{body['id']}/export",
        headers=HUMAN,
        json={"format": "json"},
    )
    assert json_export.status_code == 201, json_export.text
    packed = json_export.json()["json"]
    assert packed["drafts"][0]["body"] == PROSE
    assert packed["generates_prose"] is False
    review = world["client"].post(
        f"/projects/{world['project_id']}/release-checks/{body['id']}/export",
        headers=HUMAN,
        json={"format": "review_pack"},
    )
    assert review.status_code == 201, review.text
    pack = review.json()["review_pack"]
    assert pack["schema"] == "release-review-pack.v1"
    assert pack["human_approval_records"]
    assert pack["writes_canon"] is False


def test_manifest_is_immutable_and_tamper_evident() -> None:
    world = _world()
    created = _run_check(world).json()
    response = world["client"].get(
        f"/projects/{world['project_id']}/release-checks/{created['id']}/manifest"
    )
    assert response.status_code == 200, response.text
    manifest = response.json()
    assert manifest["immutable"] is True
    assert manifest["content_hash"]
    assert manifest["version_refs"]["snapshot_id"] == world["snapshot_id"]
    assert manifest["model_prompt_versions"]
    assert manifest["human_approval_records"]
    assert manifest["summary_stats"]["all_passed"] is True
    stored = world["release"].get_manifest(manifest["id"])
    assert stored is not None
    recomputed = stable_hash(stored.hash_payload())
    assert recomputed == manifest["content_hash"]
    stored.payload["summary_stats"]["scene_count"] = 99
    assert stable_hash(stored.hash_payload()) != manifest["content_hash"]
    patched = world["client"].patch(
        f"/projects/{world['project_id']}/release-checks/{created['id']}/manifest",
        headers=HUMAN,
        json={},
    )
    assert patched.status_code == 409
    assert patched.json()["detail"]["error"] == "release_manifest_immutable"


def test_failure_list_is_machine_readable() -> None:
    world = _world(approve_draft=False, leftover_approved=True)
    body = _run_check(world).json()
    assert body["status"] == "failed"
    assert len(body["failures"]) >= 2
    for item in body["failures"]:
        assert set(item) >= {"gate_id", "code", "message", "refs"}
        assert item["gate_id"] in GATE_IDS
        assert item["code"]
        assert item["message"]


def test_release_does_not_write_canon_or_approve() -> None:
    world = _world()
    before = len(world["canon"].facts)
    created = _run_check(world).json()
    assert created["writes_canon"] is False
    assert created["auto_approved"] is False
    assert created["is_canon_approval"] is False
    assert len(world["canon"].facts) == before
    approve = world["client"].post(
        f"/projects/{world['project_id']}/release-checks/{created['id']}/approve-canon",
        headers=HUMAN,
        json={},
    )
    assert approve.status_code == 403
    assert approve.json()["detail"]["error"] == "release_cannot_write_canon"
    submit = world["client"].post(
        f"/projects/{world['project_id']}/release-checks/{created['id']}/submit-canon",
        headers=HUMAN,
        json={},
    )
    assert submit.status_code == 403
    assert submit.json()["detail"]["error"] == "release_cannot_write_canon"
    system = world["client"].post(
        f"/projects/{world['project_id']}/release-checks/{created['id']}/approve-canon",
        headers=SYSTEM,
        json={},
    )
    assert system.status_code == 403
    assert len(world["canon"].facts) == before


def test_human_waiver_covers_due_item_and_safety() -> None:
    world = _world(safety=False)
    due = world["client"].post(
        f"/projects/{world['project_id']}/release-due-items",
        headers=HUMAN,
        json={"title": "缺口须回收", "scene_id": world["scene_id"]},
    )
    assert due.status_code == 201, due.text
    denied = world["client"].post(
        f"/projects/{world['project_id']}/release-due-items/{due.json()['id']}/waive",
        headers=GENERATE,
        json={"reason_code": "editor_ok"},
    )
    assert denied.status_code == 403
    waived = world["client"].post(
        f"/projects/{world['project_id']}/release-due-items/{due.json()['id']}/waive",
        headers=HUMAN,
        json={"reason_code": "editor_ok"},
    )
    assert waived.status_code == 200, waived.text
    safety = world["client"].post(
        f"/projects/{world['project_id']}/release-waivers",
        headers=HUMAN,
        json={"kind": "safety", "subject_id": "", "reason_code": "placeholder_ok"},
    )
    assert safety.status_code == 201, safety.text
    passed = _run_check(world)
    assert passed.status_code == 201, passed.text
    assert passed.json()["status"] == "passed"


def test_rejected_candidate_is_not_leftover_approved() -> None:
    world = _world()
    stored = world["client"].app.state.candidate_change_repository
    candidate = stored.get_candidate(world["candidate_id"])
    assert candidate is not None
    candidate.status = CANDIDATE_REJECTED
    stored.save_candidate(candidate)
    body = _run_check(world).json()
    assert body["status"] == "passed"
    assert _failed_gate(body, GATE_CANDIDATES_RESOLVED) is None


def test_extracted_candidate_does_not_fail_resolved_gate() -> None:
    world = _world()
    stored = world["client"].app.state.candidate_change_repository
    candidate = stored.get_candidate(world["candidate_id"])
    assert candidate is not None
    candidate.status = CANDIDATE_EXTRACTED
    stored.save_candidate(candidate)
    body = _run_check(world).json()
    assert _failed_gate(body, GATE_CANDIDATES_RESOLVED) is None
    assert body["status"] == "passed"


def test_writes_are_audited_and_redacted() -> None:
    world = _world()
    created = _run_check(world).json()
    world["client"].post(
        f"/projects/{world['project_id']}/release-checks/{created['id']}/export",
        headers=HUMAN,
        json={"format": "markdown"},
    )
    events = world["sink"].events
    actions = {event.action for event in events}
    assert "release_check.create" in actions
    assert "release_check.finish" in actions
    assert "release_manifest.create" in actions
    assert "release_export.create" in actions
    blob = str([event.after_json for event in events])
    assert PROSE not in blob
    assert "伸手拾起残玉" not in blob
    assert "api_key" not in blob.lower() or "[REDACTED]" in blob


def test_failed_check_is_kept_and_not_formal() -> None:
    world = _world(approve_draft=False)
    body = _run_check(world).json()
    assert world["release"].get_check(body["id"]) is not None
    assert body["is_formal_release"] is False
    listed = world["client"].get(f"/projects/{world['project_id']}/release-checks")
    assert listed.status_code == 200
    assert any(item["id"] == body["id"] for item in listed.json()["items"])


def test_healthz_and_prior_apis_remain() -> None:
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
    assert "/projects/{project_id}/scenes/{scene_id}/drafts/jobs" in paths
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/submit" in paths
    assert "/projects/{project_id}/validation-runs" in paths
    assert "/projects/{project_id}/repair-tasks" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/context-packs" in paths
    assert "/projects/{project_id}/outline-revisions" in paths
    assert "/projects/{project_id}/style-guides" in paths
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}"
        "/style-validations" in paths
    )
    assert "/projects/{project_id}/review-queue/items" in paths
    assert "/projects/{project_id}/jobs" in paths
    assert "/agents" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/dags" in paths
    assert "/projects/{project_id}/schedule/config" in paths
    assert "/experiments" in paths
    assert "/projects/{project_id}/release-checks" in paths
    assert "/projects/{project_id}/release-checks/{check_id}/export" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/book/generate" not in paths
    assert "/projects/{project_id}/auto-approve" not in paths
    assert not any("seed-status" in path for path in paths)
    assert not any("openai" in path for path in paths)


def test_no_production_seed_status() -> None:
    client, _, _, _ = _client()
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("seed-status" in path for path in paths)
    route_source = (ROOT / "backend/slove_context/release/routes.py").read_text(
        encoding="utf-8"
    )
    assert not any(
        line.lstrip().startswith("@router") and "seed-status" in line
        for line in route_source.splitlines()
    )


def test_9_1_and_9_2_artifacts_unchanged() -> None:
    status = subprocess.run(
        [
            "git",
            "diff",
            "--",
            "evals/expected",
            "evals/cases",
            "evals/fixtures",
            "backend/slove_context/experiments",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert status.returncode == 0
    assert status.stdout == ""
    porcelain = subprocess.run(
        ["git", "status", "--porcelain", "--", "evals/"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert porcelain.stdout == ""
    digest = hashlib.sha256()
    for path in sorted((ROOT / "evals" / "expected").rglob("*.json")):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    assert digest.hexdigest()
