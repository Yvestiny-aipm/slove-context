"""Validation Run write path (node 5.1).

Input: Extracted candidates that already bind Evidence, current Canon
(or a specified Snapshot), and a written / effective Story Spec.

Output: a Validation Report that matches
contracts/validation-report.schema.json.

Candidate transitions:
- Extracted → Validating when the run starts
- Validating → AwaitingVerdict on Passed
- Validating → FailedValidation on RuleFailed
- Validating → Failed on ExecFailed
- Validating → Extracted on Cancelled (run kept; candidates reusable)

Passed is not Approval and does not write Canon. RuleFailed /
ExecFailed cannot enter approval. Failure and cancel keep records.

No Repair Task. No real model. Deterministic rules only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.candidate_change.models import (
    CANDIDATE_AWAITING_VERDICT,
    CANDIDATE_EXTRACTED,
    CANDIDATE_FAILED,
    CANDIDATE_FAILED_VALIDATION,
    CANDIDATE_VALIDATING,
    CandidateChange,
)
from slove_context.candidate_change.repository import CandidateChangeRepository
from slove_context.canon.models import SNAPSHOT_FROZEN, CanonFact, Entity
from slove_context.canon.service import CanonService, CanonServiceError
from slove_context.logging import get_request_id
from slove_context.scene.service import SceneService, SceneServiceError
from slove_context.story.actors import (
    HUMAN_EDITOR,
    REVIEW_AGENT,
    SYSTEM,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.models import SPEC_DRAFT, StorySpecVersion
from slove_context.story.repository import StoryRepository
from slove_context.validation.models import (
    DEFAULT_SCHEMA_VERSION,
    OUTCOME_EXEC_FAILED,
    OUTCOME_PASSED,
    OUTCOME_RULE_FAILED,
    RUN_CANCELLABLE_STATES,
    RUN_CANCELLED,
    RUN_EXEC_FAILED,
    RUN_PASSED,
    RUN_QUEUED,
    RUN_RULE_FAILED,
    RUN_RUNNING,
    SPEC_USABLE_STATUSES,
    ValidationReport,
    ValidationRun,
    Violation,
)
from slove_context.validation.repository import ValidationRepository
from slove_context.validation.rules import DeterministicRuleEngine, RuleEngine
from slove_context.validation.validate import (
    ValidationReportSchemaError,
    validate_validation_report,
)

ALLOWED_TRIGGER_ACTORS = frozenset({HUMAN_EDITOR, REVIEW_AGENT, SYSTEM})


class ValidationServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class ValidationService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        scene_service: SceneService,
        extract_repository: CandidateChangeRepository,
        canon_service: CanonService,
        validation_repository: ValidationRepository,
        audit_writer: AuditWriter,
        rule_engine: RuleEngine | None = None,
        auto_run: bool = True,
    ) -> None:
        self._story = story_repository
        self._scenes = scene_service
        self._candidates = extract_repository
        self._canon = canon_service
        self._repo = validation_repository
        self._audit = audit_writer
        self._rules = rule_engine or DeterministicRuleEngine()
        self._auto_run = auto_run

    def trigger_run(
        self,
        *,
        project_id: str,
        actor: Actor,
        scene_id: str | None = None,
        candidate_ids: list[str] | None = None,
        snapshot_id: str | None = None,
    ) -> ValidationRun:
        self._require_project(project_id)
        trigger = _require_trigger_actor(actor)
        spec = self._require_usable_spec(project_id)
        candidates = self._require_extracted_candidates(
            project_id, scene_id=scene_id, candidate_ids=candidate_ids
        )
        scene = self._require_scene(project_id, candidates[0].scene_id)
        if scene_id is not None and scene.id != scene_id:
            raise ValidationServiceError(
                422,
                {
                    "error": "scene_id_mismatch",
                    "message": "All candidates must belong to the requested scene.",
                },
            )
        snapshot = self._require_snapshot(project_id, snapshot_id)
        created_by = _report_created_by(trigger, spec, project_id, self._story)
        now = _utc_now_z()
        run = ValidationRun(
            id=str(uuid4()),
            project_id=project_id,
            scene_id=scene.id,
            candidate_ids=[item.id for item in candidates],
            snapshot_id=snapshot,
            spec_id=spec.spec_id,
            state=RUN_QUEUED,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            actor_type=trigger.actor_type,
        )
        self._repo.add_run(run)
        self._write_audit(
            actor=trigger,
            action="validation_run.create",
            resource_type="validation_run",
            resource_id=run.id,
            before_json=None,
            after_json=run.to_audit_dict(),
        )
        self._move_candidates(
            candidates,
            CANDIDATE_VALIDATING,
            actor=Actor(actor_type=SYSTEM, actor_id=None),
            action="candidate_change.validating",
        )
        if self._auto_run:
            self._run(run, candidates=candidates, spec=spec)
        return run

    def get_run(self, project_id: str, run_id: str) -> ValidationRun:
        self._require_project(project_id)
        run = self._repo.get_run(run_id)
        if run is None or run.project_id != project_id:
            raise ValidationServiceError(404, {"error": "validation_run_not_found"})
        return run

    def get_report(self, project_id: str, run_id: str) -> ValidationReport:
        run = self.get_run(project_id, run_id)
        report = None
        if run.report_id is not None:
            report = self._repo.get_report(run.report_id)
        if report is None:
            report = self._repo.get_report_for_run(run.id)
        if report is None:
            raise ValidationServiceError(404, {"error": "validation_report_not_found"})
        return report

    def cancel_run(
        self, project_id: str, run_id: str, *, actor: Actor
    ) -> ValidationRun:
        try:
            editor = require_human_editor(
                actor, action="cancel", resource="Validation Run"
            )
        except ActorError as exc:
            raise ValidationServiceError(
                403,
                {
                    "error": "actor_not_allowed",
                    "message": str(exc),
                },
            ) from exc
        run = self.get_run(project_id, run_id)
        if run.state not in RUN_CANCELLABLE_STATES:
            raise ValidationServiceError(
                409,
                {
                    "error": "run_not_cancellable",
                    "message": (
                        "Cancel only applies to Queued or Running runs. "
                        "Passed / RuleFailed / ExecFailed / Cancelled are "
                        "kept and are not deleted."
                    ),
                    "state": run.state,
                },
            )
        candidates = self._load_candidates(run)
        self._transition(run, RUN_CANCELLED, actor_type=editor.actor_type)
        self._move_candidates(
            [item for item in candidates if item.status == CANDIDATE_VALIDATING],
            CANDIDATE_EXTRACTED,
            actor=editor,
            action="candidate_change.validation_cancelled",
        )
        return run

    def _run(
        self,
        run: ValidationRun,
        *,
        candidates: list[CandidateChange],
        spec: StorySpecVersion,
    ) -> None:
        self._transition(run, RUN_RUNNING, actor_type=REVIEW_AGENT)
        try:
            if getattr(self._repo, "force_exec_fail", False):
                raise RuntimeError("forced_exec_fail")
            facts, entities = self._load_canon(run)
            violations = self._rules.evaluate(
                candidates=candidates,
                facts=facts,
                entities=entities,
                spec=spec,
            )
        except ValidationServiceError as exc:
            self._fail_exec(run, candidates, reason=str(exc.detail))
            return
        except Exception as exc:  # noqa: BLE001 — ExecFailed must keep records
            self._fail_exec(run, candidates, reason=type(exc).__name__)
            return

        blocking = [item for item in violations if item.severity == "Blocking"]
        if blocking:
            report = self._persist_report(
                run, candidates, OUTCOME_RULE_FAILED, blocking
            )
            self._transition(
                run, RUN_RULE_FAILED, actor_type=REVIEW_AGENT, report=report
            )
            self._move_candidates(
                candidates,
                CANDIDATE_FAILED_VALIDATION,
                actor=Actor(actor_type=REVIEW_AGENT, actor_id=None),
                action="candidate_change.failed_validation",
            )
            return

        report = self._persist_report(run, candidates, OUTCOME_PASSED, [])
        self._transition(run, RUN_PASSED, actor_type=REVIEW_AGENT, report=report)
        self._move_candidates(
            candidates,
            CANDIDATE_AWAITING_VERDICT,
            actor=Actor(actor_type=REVIEW_AGENT, actor_id=None),
            action="candidate_change.awaiting_verdict",
        )

    def _fail_exec(
        self,
        run: ValidationRun,
        candidates: list[CandidateChange],
        *,
        reason: str,
    ) -> None:
        run.failure_reason = reason
        report = self._persist_report(run, candidates, OUTCOME_EXEC_FAILED, [])
        self._transition(run, RUN_EXEC_FAILED, actor_type=SYSTEM, report=report)
        self._move_candidates(
            candidates,
            CANDIDATE_FAILED,
            actor=Actor(actor_type=SYSTEM, actor_id=None),
            action="candidate_change.validation_failed",
        )

    def _persist_report(
        self,
        run: ValidationRun,
        candidates: list[CandidateChange],
        outcome: str,
        violations: list[Violation],
    ) -> ValidationReport:
        payload: dict[str, Any] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "id": str(uuid4()),
            "project_id": run.project_id,
            "created_at": _utc_now_z(),
            "created_by": run.created_by,
            "scene_id": run.scene_id,
            "candidate_change_ids": [item.id for item in candidates],
            "outcome": outcome,
            "violations": [item.to_public_dict() for item in violations],
        }
        try:
            validate_validation_report(payload)
        except ValidationReportSchemaError as exc:
            raise RuntimeError("validation_report_schema_failed") from exc
        report = ValidationReport(
            id=str(payload["id"]),
            project_id=run.project_id,
            scene_id=run.scene_id,
            candidate_change_ids=list(payload["candidate_change_ids"]),
            outcome=outcome,
            violations=list(violations),
            schema_version=DEFAULT_SCHEMA_VERSION,
            created_at=str(payload["created_at"]),
            created_by=run.created_by,
            payload=payload,
            run_id=run.id,
        )
        self._repo.add_report(report)
        self._write_audit(
            actor=Actor(actor_type=REVIEW_AGENT, actor_id=None),
            action="validation_report.create",
            resource_type="validation_report",
            resource_id=report.id,
            before_json=None,
            after_json=report.to_audit_dict(),
        )
        return report

    def _load_canon(self, run: ValidationRun) -> tuple[list[CanonFact], list[Entity]]:
        entities = self._canon.list_entities(run.project_id)
        if run.snapshot_id is not None:
            facts = self._canon.list_snapshot_facts(run.project_id, run.snapshot_id)
        else:
            facts = self._canon.list_facts_in_effect(project_id=run.project_id)
        return facts, entities

    def _require_extracted_candidates(
        self,
        project_id: str,
        *,
        scene_id: str | None,
        candidate_ids: list[str] | None,
    ) -> list[CandidateChange]:
        cleaned_ids = _unique_ids(candidate_ids)
        if cleaned_ids:
            items = [
                self._require_candidate(project_id, item_id) for item_id in cleaned_ids
            ]
        elif scene_id:
            scene = self._require_scene(project_id, scene_id)
            items = self._candidates.list_candidates(project_id, scene.id)
        else:
            raise ValidationServiceError(
                422,
                {
                    "error": "candidates_required",
                    "message": (
                        "Provide scene_id and/or candidate_ids. "
                        "Validate runs against Extracted candidates only."
                    ),
                },
            )
        if not items:
            raise ValidationServiceError(
                422,
                {
                    "error": "candidates_required",
                    "message": "No Extracted candidates were found to validate.",
                },
            )
        scenes = {item.scene_id for item in items}
        if len(scenes) != 1:
            raise ValidationServiceError(
                422,
                {
                    "error": "scene_id_mismatch",
                    "message": "A Validation Run covers exactly one scene.",
                },
            )
        for item in items:
            if item.status != CANDIDATE_EXTRACTED:
                raise ValidationServiceError(
                    409,
                    {
                        "error": "candidate_not_extracted",
                        "message": (
                            "Only Extracted candidates can start a Validation "
                            "Run. Missing Evidence or a non-Extracted status "
                            "cannot start a run. Validate is not Approval."
                        ),
                        "candidate_id": item.id,
                        "status": item.status,
                    },
                )
            if not item.evidence_quote.strip() or not item.source_scene_id.strip():
                raise ValidationServiceError(
                    409,
                    {
                        "error": "candidate_missing_evidence",
                        "message": (
                            "Each candidate must bind Evidence "
                            "(evidence_quote and source_scene_id) before "
                            "Validate. Missing Evidence cannot start a run."
                        ),
                        "candidate_id": item.id,
                    },
                )
        return items

    def _require_candidate(self, project_id: str, candidate_id: str) -> CandidateChange:
        item = self._candidates.get_candidate(candidate_id)
        if item is None or item.project_id != project_id:
            raise ValidationServiceError(404, {"error": "candidate_change_not_found"})
        return item

    def _load_candidates(self, run: ValidationRun) -> list[CandidateChange]:
        items: list[CandidateChange] = []
        for candidate_id in run.candidate_ids:
            item = self._candidates.get_candidate(candidate_id)
            if item is not None:
                items.append(item)
        return items

    def _require_usable_spec(self, project_id: str) -> StorySpecVersion:
        spec = self._story.get_spec_for_project(project_id)
        if spec is None:
            raise ValidationServiceError(
                409,
                {
                    "error": "story_spec_required",
                    "message": (
                        "Validate requires a written or effective Story Spec. "
                        "A missing spec cannot start a run."
                    ),
                },
            )
        version = spec.current_version()
        if spec.status == SPEC_DRAFT or version.status not in SPEC_USABLE_STATUSES:
            raise ValidationServiceError(
                409,
                {
                    "error": "story_spec_not_written",
                    "message": (
                        "Validate requires a written or effective Story Spec. "
                        "A Draft spec cannot start a run."
                    ),
                    "status": spec.status,
                },
            )
        return version

    def _require_snapshot(self, project_id: str, snapshot_id: str | None) -> str | None:
        cleaned = _clean_optional(snapshot_id)
        if cleaned is None:
            return None
        try:
            snapshot = self._canon.get_snapshot(project_id, cleaned)
        except CanonServiceError as exc:
            raise ValidationServiceError(
                409,
                {
                    "error": "snapshot_required",
                    "message": (
                        "The specified Canon Snapshot is missing or not "
                        "usable. Provide a project snapshot or omit "
                        "snapshot_id to use current Canon."
                    ),
                    "snapshot_id": cleaned,
                },
            ) from exc
        if snapshot.status != SNAPSHOT_FROZEN:
            raise ValidationServiceError(
                409,
                {
                    "error": "snapshot_not_frozen",
                    "message": (
                        "A specified Snapshot must be frozen so Validate "
                        "does not read a moving fact list. Live Canon is "
                        "used when snapshot_id is omitted."
                    ),
                    "snapshot_id": snapshot.id,
                    "status": snapshot.status,
                },
            )
        return snapshot.id

    def _require_scene(self, project_id: str, scene_id: str) -> Any:
        try:
            return self._scenes.get_scene(project_id, scene_id)
        except SceneServiceError as exc:
            raise ValidationServiceError(exc.status_code, exc.detail) from exc

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise ValidationServiceError(404, {"error": "project_not_found"})

    def _move_candidates(
        self,
        candidates: list[CandidateChange],
        new_status: str,
        *,
        actor: Actor,
        action: str,
    ) -> None:
        for candidate in candidates:
            if candidate.status == new_status:
                continue
            before = candidate.to_audit_dict()
            candidate.status = new_status
            candidate.payload["status"] = new_status
            self._candidates.save_candidate(candidate)
            self._write_audit(
                actor=actor,
                action=action,
                resource_type="candidate_change",
                resource_id=candidate.id,
                before_json=before,
                after_json=candidate.to_audit_dict(),
            )

    def _transition(
        self,
        run: ValidationRun,
        new_state: str,
        *,
        actor_type: str,
        report: ValidationReport | None = None,
    ) -> None:
        before = run.to_audit_dict()
        previous = run.state
        now = _utc_now_z()
        run.transitions.append({"from": previous, "to": new_state, "at": now})
        run.state = new_state
        run.updated_at = now
        if new_state == RUN_PASSED:
            run.outcome = OUTCOME_PASSED
        elif new_state == RUN_RULE_FAILED:
            run.outcome = OUTCOME_RULE_FAILED
        elif new_state == RUN_EXEC_FAILED:
            run.outcome = OUTCOME_EXEC_FAILED
        if report is not None:
            run.report_id = report.id
        self._repo.save_run(run)
        self._write_audit(
            actor=Actor(actor_type=actor_type, actor_id=None),
            action="validation_run.transition",
            resource_type="validation_run",
            resource_id=run.id,
            before_json=before,
            after_json=run.to_audit_dict(),
        )

    def _write_audit(
        self,
        *,
        actor: Actor,
        action: str,
        resource_type: str,
        resource_id: str,
        before_json: dict[str, Any] | None,
        after_json: dict[str, Any] | None,
    ) -> None:
        self._audit.write(
            actor_type=actor.actor_type or SYSTEM,
            actor_id=actor.actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            correlation_id=get_request_id(),
        )


def _report_created_by(
    actor: Actor,
    spec: StorySpecVersion,
    project_id: str,
    story: StoryRepository,
) -> str:
    # Report created_by identifies the human 主编. Validate is not Approval.
    if actor.actor_type == HUMAN_EDITOR and actor.actor_id:
        return actor.actor_id
    if spec.created_by:
        return spec.created_by
    project = story.get_project(project_id)
    if project is not None and project.created_by:
        return project.created_by
    return "主编"


def _require_trigger_actor(actor: Actor) -> Actor:
    actor_type = actor.actor_type or REVIEW_AGENT
    if actor_type not in ALLOWED_TRIGGER_ACTORS:
        raise ValidationServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Validation Runs may be triggered by the human 主编, "
                    "a review agent, or the system. This is Validate, "
                    "not Approval and not a Canon write."
                ),
                "actor_type": actor_type,
            },
        )
    return Actor(actor_type=actor_type, actor_id=actor.actor_id)


def _unique_ids(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values:
        cleaned = _clean_optional(raw)
        if cleaned is None or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
