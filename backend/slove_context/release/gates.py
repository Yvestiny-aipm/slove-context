"""Eight pre-release gates. Read-only over existing artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from slove_context.audit import AuditEvent, AuditWriter
from slove_context.candidate_change.models import (
    CANDIDATE_APPROVED,
    CANDIDATE_AWAITING_VERDICT,
    CANDIDATE_FAILED_VALIDATION,
    CANDIDATE_REJECTED,
    CANDIDATE_SUBMITTED,
    CandidateChange,
)
from slove_context.canon.models import SNAPSHOT_FROZEN, CanonSnapshot
from slove_context.release.models import (
    DUE_STATUS_DUE,
    GATE_AUDIT_COMPLETE,
    GATE_CANDIDATES_RESOLVED,
    GATE_CHAPTER_SUMMARIES,
    GATE_DRAFTS_APPROVED,
    GATE_FORESHADOWING,
    GATE_IDS,
    GATE_NO_UNHANDLED_BLOCKERS,
    GATE_SNAPSHOT_FROZEN,
    GATE_STYLE_AND_SAFETY,
    DueItem,
    GateFailure,
    GateResult,
    SafetyCheck,
)
from slove_context.repair.models import TASK_RECHECK_PASSED, RepairTask
from slove_context.review_queue.models import (
    OPEN_STATES,
    STATUS_APPROVED,
    SUBJECT_SCENE_DRAFT,
    ReviewQueueItem,
)
from slove_context.scene.models import Chapter, Scene
from slove_context.scene_draft.models import (
    DRAFT_EXTRACTED,
    DRAFT_GENERATED,
    SceneDraft,
)
from slove_context.style_validation.models import RUN_SUCCEEDED, StyleValidation
from slove_context.summary.models import ChapterSummary
from slove_context.validation.models import (
    SEVERITY_BLOCKING,
    ValidationReport,
    ValidationRun,
)

CURRENT_DRAFT_STATUSES = frozenset({DRAFT_GENERATED, DRAFT_EXTRACTED})
RESOLVED_CANDIDATE_STATUSES = frozenset({CANDIDATE_SUBMITTED, CANDIDATE_REJECTED})
HANDLED_CANDIDATE_STATUSES = frozenset(
    {
        CANDIDATE_REJECTED,
        CANDIDATE_SUBMITTED,
        CANDIDATE_AWAITING_VERDICT,
        CANDIDATE_APPROVED,
    }
)
ERROR_SEVERITIES = frozenset(
    {SEVERITY_BLOCKING, "blocker", "Blocker", "error", "Error", "error-level"}
)


@dataclass
class GateContext:
    project_id: str
    snapshot: CanonSnapshot | None
    scenes: list[Scene]
    chapters: list[Chapter]
    drafts: list[SceneDraft]
    candidates: list[CandidateChange]
    reports: list[ValidationReport]
    runs: list[ValidationRun]
    repairs: list[RepairTask]
    review_items: list[ReviewQueueItem]
    chapter_summaries: list[ChapterSummary]
    style_runs: list[StyleValidation]
    due_items: list[DueItem]
    safety_checks: list[SafetyCheck]
    audit_writer: AuditWriter


def run_all_gates(ctx: GateContext) -> list[GateResult]:
    runners = (
        check_drafts_human_approved,
        check_no_unhandled_blockers,
        check_candidates_resolved,
        check_snapshot_frozen,
        check_chapter_summaries,
        check_foreshadowing,
        check_style_and_safety,
        check_audit_complete,
    )
    results = [runner(ctx) for runner in runners]
    seen = [item.gate_id for item in results]
    if list(seen) != list(GATE_IDS):
        results.append(
            GateResult(
                gate_id="gates_incomplete",
                passed=False,
                failures=[
                    GateFailure(
                        gate_id="gates_incomplete",
                        code="missing_gate",
                        message="Not all eight pre-release gates ran.",
                        refs=list(seen),
                    )
                ],
            )
        )
    return results


def check_drafts_human_approved(ctx: GateContext) -> GateResult:
    failures: list[GateFailure] = []
    if not ctx.drafts:
        failures.append(
            GateFailure(
                gate_id=GATE_DRAFTS_APPROVED,
                code="no_target_drafts",
                message="No current Scene Drafts exist for the target scenes.",
                refs=[item.id for item in ctx.scenes],
            )
        )
        return GateResult(GATE_DRAFTS_APPROVED, False, failures)
    approved_ids = _approved_draft_ids(ctx.review_items)
    for draft in ctx.drafts:
        if draft.id not in approved_ids:
            failures.append(
                GateFailure(
                    gate_id=GATE_DRAFTS_APPROVED,
                    code="draft_not_human_approved",
                    message=(
                        "Target Scene Draft is not human-approved on the "
                        "review queue. Release does not auto-approve drafts."
                    ),
                    refs=[draft.id, draft.scene_id],
                )
            )
    return _result(GATE_DRAFTS_APPROVED, failures)


def check_no_unhandled_blockers(ctx: GateContext) -> GateResult:
    failures: list[GateFailure] = []
    scene_ids = {item.id for item in ctx.scenes}
    latest_by_scene = _latest_report_by_scene(ctx.reports, scene_ids)
    for scene_id, report in latest_by_scene.items():
        blocking = [
            item for item in report.violations if item.severity in ERROR_SEVERITIES
        ]
        if not blocking:
            continue
        if _violations_handled(ctx, report):
            continue
        failures.append(
            GateFailure(
                gate_id=GATE_NO_UNHANDLED_BLOCKERS,
                code="unhandled_blocking_violation",
                message=(
                    "Unhandled blocker/error-level Validation Violation "
                    "remains. Release does not repair or approve."
                ),
                refs=[report.id, scene_id, *report.candidate_change_ids],
            )
        )
    for item in ctx.review_items:
        if item.scene_id not in scene_ids and item.scene_id is not None:
            continue
        if item.is_blocker and item.status in OPEN_STATES:
            failures.append(
                GateFailure(
                    gate_id=GATE_NO_UNHANDLED_BLOCKERS,
                    code="open_review_blocker",
                    message="An open review-queue blocker remains.",
                    refs=[item.id, item.subject_id],
                )
            )
    open_repairs = [
        item
        for item in ctx.repairs
        if item.scene_id in scene_ids
        and item.state != TASK_RECHECK_PASSED
        and item.state not in {"Cancelled"}
        and _repair_still_open(item, ctx)
    ]
    for task in open_repairs:
        failures.append(
            GateFailure(
                gate_id=GATE_NO_UNHANDLED_BLOCKERS,
                code="open_repair_task",
                message="A Repair Task for a blocker has not reached RecheckPassed.",
                refs=[task.id, task.scene_id],
            )
        )
    return _result(GATE_NO_UNHANDLED_BLOCKERS, failures)


def check_candidates_resolved(ctx: GateContext) -> GateResult:
    failures: list[GateFailure] = []
    for candidate in ctx.candidates:
        if candidate.status == CANDIDATE_APPROVED:
            failures.append(
                GateFailure(
                    gate_id=GATE_CANDIDATES_RESOLVED,
                    code="approved_not_submitted",
                    message=(
                        "Approved Candidate Change is neither Submitted nor "
                        "explicitly Rejected. Release does not submit Canon."
                    ),
                    refs=[candidate.id, candidate.scene_id],
                )
            )
    return _result(GATE_CANDIDATES_RESOLVED, failures)


def check_snapshot_frozen(ctx: GateContext) -> GateResult:
    failures: list[GateFailure] = []
    if ctx.snapshot is None:
        failures.append(
            GateFailure(
                gate_id=GATE_SNAPSHOT_FROZEN,
                code="snapshot_missing",
                message="Canon Snapshot is missing.",
                refs=[],
            )
        )
        return GateResult(GATE_SNAPSHOT_FROZEN, False, failures)
    if ctx.snapshot.status != SNAPSHOT_FROZEN:
        failures.append(
            GateFailure(
                gate_id=GATE_SNAPSHOT_FROZEN,
                code="snapshot_not_frozen",
                message="Canon Snapshot is not frozen.",
                refs=[ctx.snapshot.id, ctx.snapshot.status],
            )
        )
    return _result(GATE_SNAPSHOT_FROZEN, failures)


def check_chapter_summaries(ctx: GateContext) -> GateResult:
    failures: list[GateFailure] = []
    if not ctx.chapters:
        failures.append(
            GateFailure(
                gate_id=GATE_CHAPTER_SUMMARIES,
                code="no_target_chapters",
                message="No target chapters were resolved for chapter summaries.",
                refs=[],
            )
        )
        return GateResult(GATE_CHAPTER_SUMMARIES, False, failures)
    present = {item.chapter_id for item in ctx.chapter_summaries}
    for chapter in ctx.chapters:
        if chapter.id not in present:
            failures.append(
                GateFailure(
                    gate_id=GATE_CHAPTER_SUMMARIES,
                    code="chapter_summary_missing",
                    message="Target chapter has no generated Chapter Summary.",
                    refs=[chapter.id],
                )
            )
    return _result(GATE_CHAPTER_SUMMARIES, failures)


def check_foreshadowing(ctx: GateContext) -> GateResult:
    failures: list[GateFailure] = []
    scene_ids = {item.id for item in ctx.scenes}
    chapter_ids = {item.id for item in ctx.chapters}
    for item in ctx.due_items:
        in_target = (
            (item.scene_id is None and item.chapter_id is None)
            or (item.scene_id in scene_ids)
            or (item.chapter_id in chapter_ids)
        )
        if not in_target:
            continue
        if item.status == DUE_STATUS_DUE:
            failures.append(
                GateFailure(
                    gate_id=GATE_FORESHADOWING,
                    code="due_foreshadowing_unhandled",
                    message=(
                        "Due foreshadowing item is neither handled nor "
                        "covered by a human waiver."
                    ),
                    refs=[item.id],
                )
            )
    return _result(GATE_FORESHADOWING, failures)


def check_style_and_safety(ctx: GateContext) -> GateResult:
    failures: list[GateFailure] = []
    style_by_draft = {
        item.draft_revision_id
        for item in ctx.style_runs
        if item.status == RUN_SUCCEEDED
    }
    for draft in ctx.drafts:
        if draft.id not in style_by_draft:
            failures.append(
                GateFailure(
                    gate_id=GATE_STYLE_AND_SAFETY,
                    code="style_check_missing",
                    message="Target Scene Draft has no recorded Style Validation result.",
                    refs=[draft.id, draft.scene_id],
                )
            )
    if not ctx.safety_checks:
        failures.append(
            GateFailure(
                gate_id=GATE_STYLE_AND_SAFETY,
                code="safety_check_missing",
                message=(
                    "No recorded safety-check result or human safety waiver. "
                    "No real safety vendor is called."
                ),
                refs=[],
            )
        )
    return _result(GATE_STYLE_AND_SAFETY, failures)


def check_audit_complete(ctx: GateContext) -> GateResult:
    failures: list[GateFailure] = []
    sink = getattr(ctx.audit_writer, "_sink", None)
    events = getattr(sink, "events", None)
    if sink is None or events is None:
        failures.append(
            GateFailure(
                gate_id=GATE_AUDIT_COMPLETE,
                code="audit_not_replayable",
                message="Audit trail is not replayable for this project.",
                refs=[],
            )
        )
        return GateResult(GATE_AUDIT_COMPLETE, False, failures)
    matching = [
        event
        for event in events
        if isinstance(event, AuditEvent)
        and _event_mentions_project(event, ctx.project_id)
    ]
    if not matching:
        failures.append(
            GateFailure(
                gate_id=GATE_AUDIT_COMPLETE,
                code="audit_trail_empty",
                message=(
                    "No replayable audit events exist for this project. "
                    "Release-related writes must go through AuditWriter."
                ),
                refs=[ctx.project_id],
            )
        )
    return _result(GATE_AUDIT_COMPLETE, failures)


def current_drafts_for_scenes(
    drafts_by_scene: dict[str, list[SceneDraft]], scene_ids: list[str]
) -> list[SceneDraft]:
    current: list[SceneDraft] = []
    for scene_id in scene_ids:
        items = [
            item
            for item in drafts_by_scene.get(scene_id, [])
            if item.status in CURRENT_DRAFT_STATUSES
        ]
        items.sort(key=lambda item: item.revision, reverse=True)
        if items:
            current.append(items[0])
    return current


def _approved_draft_ids(items: list[ReviewQueueItem]) -> set[str]:
    return {
        item.subject_id
        for item in items
        if item.subject_type == SUBJECT_SCENE_DRAFT and item.status == STATUS_APPROVED
    }


def _latest_report_by_scene(
    reports: list[ValidationReport], scene_ids: set[str]
) -> dict[str, ValidationReport]:
    latest: dict[str, ValidationReport] = {}
    ordered = sorted(reports, key=lambda item: (item.created_at, item.id))
    for report in ordered:
        if report.scene_id in scene_ids:
            latest[report.scene_id] = report
    return latest


def _violations_handled(ctx: GateContext, report: ValidationReport) -> bool:
    related = [
        item for item in ctx.candidates if item.id in set(report.candidate_change_ids)
    ]
    if related and all(item.status in HANDLED_CANDIDATE_STATUSES for item in related):
        if all(item.status in RESOLVED_CANDIDATE_STATUSES for item in related):
            return True
        if all(item.status != CANDIDATE_FAILED_VALIDATION for item in related):
            return True
    repairs = [
        item
        for item in ctx.repairs
        if item.report_id == report.id or item.validation_run_id == report.run_id
    ]
    if any(item.state == TASK_RECHECK_PASSED for item in repairs):
        return True
    return bool(related) and all(item.status == CANDIDATE_REJECTED for item in related)


def _repair_still_open(task: RepairTask, ctx: GateContext) -> bool:
    if task.state == TASK_RECHECK_PASSED:
        return False
    if task.rejected_candidate_ids:
        return False
    report = next((item for item in ctx.reports if item.id == task.report_id), None)
    if report is not None and _violations_handled(ctx, report):
        return False
    return task.state in {
        "Opened",
        "InProgress",
        "Completed",
        "Rechecking",
        "Failed",
        "Rework",
    }


def _event_mentions_project(event: AuditEvent, project_id: str) -> bool:
    if event.resource_id == project_id:
        return True
    for blob in (event.before_json, event.after_json):
        if isinstance(blob, dict) and blob.get("project_id") == project_id:
            return True
    return False


def _result(gate_id: str, failures: list[GateFailure]) -> GateResult:
    return GateResult(gate_id=gate_id, passed=not failures, failures=failures)


def flatten_failures(results: list[GateResult]) -> list[GateFailure]:
    items: list[GateFailure] = []
    for result in results:
        items.extend(result.failures)
    return items


def gate_stats(results: list[GateResult]) -> dict[str, Any]:
    return {
        "gates_required": list(GATE_IDS),
        "gates_run": [item.gate_id for item in results],
        "gates_passed": [item.gate_id for item in results if item.passed],
        "gates_failed": [item.gate_id for item in results if not item.passed],
        "all_passed": all(item.passed for item in results) and len(results) >= 8,
    }
