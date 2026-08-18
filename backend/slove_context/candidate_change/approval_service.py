"""Human approve / reject / submit for Candidate Changes (node 4.2).

Approve: AwaitingVerdict → Approved. Records the verdict only.
Reject: AwaitingVerdict or Approved → Rejected. Does not write Canon.
Submit: Approved → Submitted. Only then create or supersede a Canon Fact.
The candidate remains a Submitted candidate; it does not become a fact.

Only the human 主编 (X-Actor-Type: human_editor) may approve or submit.
System / generation Agent / review Agent / model / bot are rejected.
No auto-approve. Approved does not automatically become Submitted.

Duplicate submit is rejected (409). It is not idempotent and must not
double-write Canon. Failure / cancel / reject keep records.

This module does not implement Validate / Validation Run (5.x).
Tests may seed AwaitingVerdict and skip Validate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.agents.permissions import PermissionDenied, PermissionGuard
from slove_context.audit import AuditWriter
from slove_context.candidate_change.models import (
    APPROVE_FROM,
    CANDIDATE_APPROVED,
    CANDIDATE_REJECTED,
    CANDIDATE_SUBMITTED,
    DECISION_APPROVE,
    DECISION_REJECT,
    DEFAULT_SCHEMA_VERSION,
    REJECT_FROM,
    SUBMIT_FROM,
    CandidateChange,
)
from slove_context.candidate_change.repository import CandidateChangeRepository
from slove_context.candidate_change.service import CandidateChangeServiceError
from slove_context.candidate_change.validate import (
    ApprovalDecisionSchemaError,
    validate_approval_decision,
)
from slove_context.canon.models import CanonFact, Entity
from slove_context.canon.service import CanonService, CanonServiceError
from slove_context.logging import get_request_id
from slove_context.story.actors import (
    HUMAN_EDITOR,
    NON_HUMAN_TYPES,
    Actor,
    ActorError,
    normalize_actor_type,
    require_human_editor,
)
from slove_context.story.repository import StoryRepository

# created_by must be the human 主编. These exact values are never allowed.
_FORBIDDEN_CREATED_BY = frozenset(
    {
        "model",
        "bot",
        "auto",
        "autoapprove",
        "auto_approve",
        "openai",
        "anthropic",
        "llm",
        "boonibot",
        "hettbot",
        "lollibot",
        "实现 bot",
        "验收 bot",
        "实现bot",
        "验收bot",
    }
)


class ApprovalService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        extract_repository: CandidateChangeRepository,
        canon_service: CanonService,
        audit_writer: AuditWriter,
    ) -> None:
        self._story = story_repository
        self._repo = extract_repository
        self._canon = canon_service
        self._audit = audit_writer

    def get_candidate(self, project_id: str, candidate_id: str) -> CandidateChange:
        return self._require_candidate(project_id, candidate_id)

    def approve(
        self,
        *,
        project_id: str,
        candidate_id: str,
        actor: Actor,
        body: dict[str, Any],
    ) -> tuple[CandidateChange, dict[str, Any]]:
        editor = self._require_human(actor, action="approve")
        candidate = self._require_candidate(project_id, candidate_id)
        if candidate.status not in APPROVE_FROM:
            raise CandidateChangeServiceError(
                409,
                {
                    "error": "invalid_candidate_transition",
                    "message": (
                        "Only AwaitingVerdict can be approved. Extracted / "
                        "Validating / FailedValidation / Failed / Rework / "
                        "Cancelled cannot approve. Approve does not write Canon."
                    ),
                    "status": candidate.status,
                },
            )
        decision = self._assemble_decision(
            project_id=project_id,
            candidate_id=candidate.id,
            expected=DECISION_APPROVE,
            actor=editor,
            body=body,
        )
        self._record_verdict(candidate, decision, editor, CANDIDATE_APPROVED)
        return candidate, decision

    def reject(
        self,
        *,
        project_id: str,
        candidate_id: str,
        actor: Actor,
        body: dict[str, Any],
    ) -> tuple[CandidateChange, dict[str, Any]]:
        editor = self._require_human(actor, action="reject")
        candidate = self._require_candidate(project_id, candidate_id)
        if candidate.status not in REJECT_FROM:
            raise CandidateChangeServiceError(
                409,
                {
                    "error": "invalid_candidate_transition",
                    "message": (
                        "Reject is allowed from AwaitingVerdict or Approved "
                        "(before submit). It does not write Canon. Records "
                        "are kept."
                    ),
                    "status": candidate.status,
                },
            )
        decision = self._assemble_decision(
            project_id=project_id,
            candidate_id=candidate.id,
            expected=DECISION_REJECT,
            actor=editor,
            body=body,
        )
        self._record_verdict(candidate, decision, editor, CANDIDATE_REJECTED)
        return candidate, decision

    def submit(
        self,
        *,
        project_id: str,
        candidate_id: str,
        actor: Actor,
        body: dict[str, Any],
    ) -> dict[str, CandidateChange | CanonFact | None]:
        editor = self._require_human(actor, action="submit")
        candidate = self._require_candidate(project_id, candidate_id)
        if candidate.status == CANDIDATE_SUBMITTED:
            # Documented rule: second submit is rejected. Not idempotent.
            # Prevents a double Canon write.
            raise CandidateChangeServiceError(
                409,
                {
                    "error": "candidate_already_submitted",
                    "message": (
                        "This candidate is already Submitted. A second submit "
                        "is rejected and does not write another Canon Fact. "
                        "Duplicate submit is not idempotent."
                    ),
                    "status": candidate.status,
                    "submitted_canon_fact_id": candidate.submitted_canon_fact_id,
                },
            )
        if candidate.status not in SUBMIT_FROM:
            raise CandidateChangeServiceError(
                409,
                {
                    "error": "invalid_candidate_transition",
                    "message": (
                        "Only an Approved candidate can be submitted. "
                        "Extracted / Validating / FailedValidation / Failed / "
                        "Rework / Cancelled / AwaitingVerdict cannot submit. "
                        "Approved does not automatically become Submitted."
                    ),
                    "status": candidate.status,
                },
            )

        entity: Entity = self._resolve_entity(candidate, editor, body)
        evidence = self._canon.create_evidence(
            project_id=project_id,
            source_type="prose",
            quote=candidate.evidence_quote,
            actor=editor,
            scene_id=candidate.source_scene_id,
            created_by=editor.actor_id or candidate.created_by,
        )
        fact, superseded = self._commit_canon(
            candidate,
            editor,
            entity_id=entity.id,
            evidence_id=evidence.id,
            supersede_fact_id=_optional_str(body.get("supersede_fact_id")),
        )
        before = candidate.to_audit_dict()
        candidate.status = CANDIDATE_SUBMITTED
        candidate.payload["status"] = CANDIDATE_SUBMITTED
        candidate.submitted_canon_fact_id = fact.id
        candidate.superseded_canon_fact_id = superseded.id if superseded else None
        self._repo.save_candidate(candidate)
        self._write_audit(
            actor=editor,
            action="candidate_change.submit",
            resource_type="candidate_change",
            resource_id=candidate.id,
            before_json=before,
            after_json=candidate.to_audit_dict(),
        )
        return {
            "candidate": candidate,
            "canon_fact": fact,
            "superseded": superseded,
        }

    def _record_verdict(
        self,
        candidate: CandidateChange,
        decision: dict[str, Any],
        editor: Actor,
        new_status: str,
    ) -> None:
        before = candidate.to_audit_dict()
        candidate.status = new_status
        candidate.payload["status"] = new_status
        candidate.approval_decision = dict(decision)
        self._repo.save_candidate(candidate)
        action = (
            "candidate_change.approve"
            if new_status == CANDIDATE_APPROVED
            else "candidate_change.reject"
        )
        self._write_audit(
            actor=editor,
            action=action,
            resource_type="candidate_change",
            resource_id=candidate.id,
            before_json=before,
            after_json=candidate.to_audit_dict(),
        )
        self._write_audit(
            actor=editor,
            action="approval_decision.create",
            resource_type="approval_decision",
            resource_id=str(decision["id"]),
            before_json=None,
            after_json=_decision_audit_dict(decision),
        )

    def _commit_canon(
        self,
        candidate: CandidateChange,
        editor: Actor,
        *,
        entity_id: str,
        evidence_id: str,
        supersede_fact_id: str | None,
    ) -> tuple[CanonFact, CanonFact | None]:
        payload = {
            "entity_id": entity_id,
            "predicate": candidate.predicate,
            "value_json": {
                "object": candidate.object,
                "value": candidate.value,
            },
            "effective_story_time": candidate.effective_story_time,
            "valid_from_scene_id": candidate.source_scene_id,
            "source_type": "prose",
            "evidence_id": evidence_id,
            "created_by": editor.actor_id or candidate.created_by,
        }
        target_id = supersede_fact_id
        if target_id is None:
            matching = self._canon.list_facts_in_effect(
                project_id=candidate.project_id,
                entity_id=entity_id,
                predicate=candidate.predicate,
            )
            if matching:
                target_id = matching[0].id
        try:
            if target_id is not None:
                result = self._canon.supersede_fact(
                    project_id=candidate.project_id,
                    fact_id=target_id,
                    payload=payload,
                    actor=editor,
                )
                return result["new"], result["old"]
            created = self._canon.create_fact(
                project_id=candidate.project_id,
                payload=payload,
                actor=editor,
            )
            # Human submit is the commit path that activates the fact.
            # Not auto-approve of the candidate (already Approved).
            active = self._canon.approve_fact(candidate.project_id, created.id, editor)
            return active, None
        except CanonServiceError as exc:
            raise CandidateChangeServiceError(exc.status_code, exc.detail) from exc

    def _resolve_entity(
        self, candidate: CandidateChange, editor: Actor, body: dict[str, Any]
    ) -> Entity:
        entity_id = _optional_str(body.get("entity_id"))
        entity_type = _optional_str(body.get("entity_type"))
        try:
            if entity_id is not None:
                matches = [
                    item
                    for item in self._canon.list_entities(candidate.project_id)
                    if item.id == entity_id
                ]
                if not matches:
                    raise CandidateChangeServiceError(
                        404, {"error": "entity_not_found"}
                    )
                return matches[0]
            named = [
                item
                for item in self._canon.list_entities(candidate.project_id)
                if item.name == candidate.subject
            ]
            if len(named) == 1:
                return named[0]
            if len(named) > 1:
                raise CandidateChangeServiceError(
                    422,
                    {
                        "error": "entity_ambiguous",
                        "message": (
                            "Multiple entities share this subject name. "
                            "Pass entity_id to submit."
                        ),
                    },
                )
            if entity_type is None:
                raise CandidateChangeServiceError(
                    422,
                    {
                        "error": "entity_type_required",
                        "message": (
                            "No existing entity matches the candidate subject. "
                            "Pass entity_type (or entity_id) so submit can "
                            "create a generic entity. This is not auto-approve."
                        ),
                    },
                )
            return self._canon.create_entity(
                project_id=candidate.project_id,
                name=candidate.subject,
                entity_type=entity_type,
                actor=editor,
                created_by=editor.actor_id or candidate.created_by,
            )
        except CanonServiceError as exc:
            raise CandidateChangeServiceError(exc.status_code, exc.detail) from exc

    def _assemble_decision(
        self,
        *,
        project_id: str,
        candidate_id: str,
        expected: str,
        actor: Actor,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        incoming = body.get("decision")
        if incoming is not None and incoming != expected:
            raise CandidateChangeServiceError(
                422,
                {
                    "error": "decision_mismatch",
                    "message": (
                        f"This endpoint records decision={expected} only. "
                        "AutoApprove is not a valid decision."
                    ),
                    "decision": incoming,
                },
            )
        created_by = _optional_str(body.get("created_by")) or actor.actor_id
        if created_by is None:
            raise CandidateChangeServiceError(
                422,
                {
                    "error": "created_by_required",
                    "message": (
                        "created_by must be the human 主编 (created_by or X-Actor-Id)."
                    ),
                },
            )
        if not _is_human_created_by(created_by):
            raise CandidateChangeServiceError(
                403,
                {
                    "error": "created_by_must_be_human_editor",
                    "message": (
                        "created_by MUST be the human 主编. System / "
                        "generation Agent / review Agent / model / bot "
                        "cannot approve or submit."
                    ),
                    "created_by": created_by,
                },
            )
        payload: dict[str, Any] = {
            "schema_version": body.get("schema_version") or DEFAULT_SCHEMA_VERSION,
            "id": body.get("id") or str(uuid4()),
            "project_id": body.get("project_id") or project_id,
            "created_at": body.get("created_at") or _utc_now_z(),
            "created_by": created_by,
            "candidate_change_id": body.get("candidate_change_id") or candidate_id,
            "decision": expected,
        }
        reason = body.get("reason")
        if reason is not None:
            payload["reason"] = reason
        if payload["project_id"] != project_id:
            raise CandidateChangeServiceError(
                422,
                {
                    "error": "project_id_mismatch",
                    "message": "Approval Decision project_id must match the URL.",
                },
            )
        if payload["candidate_change_id"] != candidate_id:
            raise CandidateChangeServiceError(
                422,
                {
                    "error": "candidate_change_id_mismatch",
                    "message": (
                        "Approval Decision candidate_change_id must match "
                        "the candidate being decided."
                    ),
                },
            )
        try:
            validate_approval_decision(payload)
        except ApprovalDecisionSchemaError as exc:
            raise CandidateChangeServiceError(
                422,
                {
                    "error": "approval_decision_schema_failed",
                    "message": (
                        "Approval Decision must match "
                        "contracts/approval-decision.schema.json."
                    ),
                    "errors": exc.errors,
                },
            ) from exc
        return payload

    def _require_candidate(self, project_id: str, candidate_id: str) -> CandidateChange:
        self._require_project(project_id)
        candidate = self._repo.get_candidate(candidate_id)
        if candidate is None or candidate.project_id != project_id:
            raise CandidateChangeServiceError(
                404, {"error": "candidate_change_not_found"}
            )
        return candidate

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise CandidateChangeServiceError(404, {"error": "project_not_found"})

    def _require_human(self, actor: Actor, *, action: str) -> Actor:
        try:
            editor = require_human_editor(
                actor, action=action, resource="Candidate Change"
            )
        except ActorError as exc:
            raise CandidateChangeServiceError(
                403,
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                    "actor_type": actor.actor_type or None,
                },
            ) from exc
        try:
            guard = PermissionGuard()
            if action == "approve":
                guard.assert_actor_may_approve_canon(editor)
            elif action == "submit":
                guard.assert_actor_may_submit_canon(editor)
        except PermissionDenied as exc:
            raise CandidateChangeServiceError(exc.status_code, exc.detail) from exc
        return editor

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
            actor_type=actor.actor_type or HUMAN_EDITOR,
            actor_id=actor.actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            correlation_id=get_request_id(),
        )


def _is_human_created_by(value: str) -> bool:
    normalized = normalize_actor_type(value)
    if normalized in NON_HUMAN_TYPES:
        return False
    compact = value.strip().lower().replace("-", "_").replace(" ", "_")
    if compact in _FORBIDDEN_CREATED_BY:
        return False
    return value.strip().lower() not in _FORBIDDEN_CREATED_BY


def _decision_audit_dict(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": decision.get("id"),
        "project_id": decision.get("project_id"),
        "candidate_change_id": decision.get("candidate_change_id"),
        "decision": decision.get("decision"),
        "created_by": decision.get("created_by"),
        "has_reason": bool(decision.get("reason")),
        "writes_canon": False,
        "auto_approved": False,
    }


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
