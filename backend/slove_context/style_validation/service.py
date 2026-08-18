"""Style Validation write path (node 7.2).

Input: an immutable Scene Draft revision + optional approved Style Guide
and authorized Style Samples + configurable thresholds.

Output: a persisted report with problem / text evidence / severity /
minimal fix, plus rule_version and optional llm_score_version.

Deterministic checks run in-process. The optional LLM check uses Fake
Provider only and evaluates conformance to this project's approved
Style Guide. Unapproved guides, unauthorized samples, and living-author
imitation are refused. Missing approved Guide → skip with an explicit
llm_status (never invent a style from the prose).

Findings default to warning / info and never set blocks_canon_submit.
This path does not write Canon, does not extract candidates, does not
approve / submit, and is not a 5.x Validation Run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.llm.errors import LlmError
from slove_context.llm.gateway import LlmGateway
from slove_context.llm.types import GenerateRequest, GenerateResponse
from slove_context.logging import get_request_id
from slove_context.scene.repository import SceneRepository
from slove_context.scene_draft.repository import SceneDraftRepository
from slove_context.story.actors import (
    HUMAN_EDITOR,
    REVIEW_AGENT,
    SYSTEM,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.repository import StoryRepository
from slove_context.style.models import GUIDE_APPROVED, StyleGuide, StyleSample
from slove_context.style.repository import StyleRepository
from slove_context.style.service import StyleService, StyleServiceError
from slove_context.style_validation.checks import run_deterministic_checks
from slove_context.style_validation.models import (
    DEFAULT_TASK_TYPE,
    LIVING_AUTHOR_MARKERS,
    LLM_RAN,
    LLM_REFUSED_LIVING_AUTHOR,
    LLM_SCORE_VERSION,
    LLM_SKIPPED,
    LLM_SKIPPED_NO_GUIDE,
    PROMPT_VERSION,
    RULE_LLM,
    RUN_CANCELLABLE_STATES,
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    SEVERITY_WARNING,
    StyleFinding,
    StyleThresholds,
    StyleValidation,
    coerce_style_severity,
)
from slove_context.style_validation.prompt import (
    build_system_prompt,
    build_user_prompt,
)
from slove_context.style_validation.repository import StyleValidationRepository

ALLOWED_TRIGGER_ACTORS = frozenset({HUMAN_EDITOR, REVIEW_AGENT, SYSTEM})


class StyleValidationServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class StyleValidationService:
    def __init__(
        self,
        *,
        story_repository: StoryRepository,
        scene_repository: SceneRepository,
        draft_repository: SceneDraftRepository,
        style_repository: StyleRepository,
        validation_repository: StyleValidationRepository,
        audit_writer: AuditWriter,
        llm_gateway: LlmGateway,
        style_service: StyleService | None = None,
        auto_run: bool = True,
        task_type: str = DEFAULT_TASK_TYPE,
    ) -> None:
        self._story = story_repository
        self._scenes = scene_repository
        self._drafts = draft_repository
        self._styles = style_repository
        self._repo = validation_repository
        self._audit = audit_writer
        self._gateway = llm_gateway
        self._style = style_service or StyleService(
            story_repository=story_repository,
            style_repository=style_repository,
            audit_writer=audit_writer,
            scene_repository=scene_repository,
            draft_repository=draft_repository,
        )
        self._auto_run = auto_run
        self._task_type = task_type

    def trigger(
        self,
        *,
        project_id: str,
        scene_id: str,
        revision_id: str,
        actor: Actor,
        style_guide_revision_id: str | None = None,
        style_sample_ids: list[str] | None = None,
        thresholds: dict[str, Any] | None = None,
        include_llm: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> StyleValidation:
        self._require_project(project_id)
        trigger = _require_trigger_actor(actor)
        self._reject_living_author_request(extra, style_sample_ids or [])
        scene = self._require_scene(project_id, scene_id)
        draft = self._require_draft(project_id, scene.id, revision_id)
        cuts = StyleThresholds.from_mapping(thresholds)
        samples = [
            self._require_authorized_sample(project_id, sample_id)
            for sample_id in (style_sample_ids or [])
        ]
        guide: StyleGuide | None = None
        if style_guide_revision_id:
            guide = self._require_approved_guide(project_id, style_guide_revision_id)
        elif draft.style_guide_revision_id:
            guide = self._optional_approved_guide(
                project_id, draft.style_guide_revision_id
            )
        if guide is None:
            guide = self._current_approved_guide(project_id)
        now = _utc_now_z()
        run = StyleValidation(
            id=str(uuid4()),
            project_id=project_id,
            scene_id=scene.id,
            draft_revision_id=draft.id,
            status=RUN_QUEUED,
            created_at=now,
            updated_at=now,
            created_by=trigger.actor_id or "主编",
            actor_type=trigger.actor_type,
            style_guide_revision_id=guide.id if guide is not None else None,
            style_sample_ids=[item.id for item in samples],
            include_llm=include_llm,
            thresholds=cuts,
            llm_status=LLM_SKIPPED if not include_llm else LLM_SKIPPED_NO_GUIDE,
        )
        if include_llm and guide is None:
            run.llm_status = LLM_SKIPPED_NO_GUIDE
        elif include_llm and guide is not None:
            run.llm_status = LLM_SKIPPED
        self._repo.add(run)
        self._write_audit(
            actor=trigger,
            action="style_validation.create",
            resource_id=run.id,
            before_json=None,
            after_json=run.to_audit_dict(),
        )
        if self._auto_run:
            self._run(run, body=draft.body, guide=guide)
        return run

    def get(
        self, project_id: str, scene_id: str, revision_id: str, run_id: str
    ) -> StyleValidation:
        self._require_project(project_id)
        run = self._repo.get(run_id)
        if (
            run is None
            or run.project_id != project_id
            or run.scene_id != scene_id
            or run.draft_revision_id != revision_id
        ):
            raise StyleValidationServiceError(
                404, {"error": "style_validation_not_found"}
            )
        return run

    def list_for_draft(
        self, project_id: str, scene_id: str, revision_id: str
    ) -> list[StyleValidation]:
        self._require_project(project_id)
        self._require_scene(project_id, scene_id)
        self._require_draft(project_id, scene_id, revision_id)
        return self._repo.list_for_draft(project_id, scene_id, revision_id)

    def cancel(
        self,
        project_id: str,
        scene_id: str,
        revision_id: str,
        run_id: str,
        *,
        actor: Actor,
    ) -> StyleValidation:
        try:
            editor = require_human_editor(
                actor, action="cancel", resource="Style Validation"
            )
        except ActorError as exc:
            raise StyleValidationServiceError(
                403,
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                    "writes_canon": False,
                    "blocks_canon_submit": False,
                },
            ) from exc
        run = self.get(project_id, scene_id, revision_id, run_id)
        if run.status == RUN_CANCELLED:
            return run
        if run.status not in RUN_CANCELLABLE_STATES:
            raise StyleValidationServiceError(
                409,
                {
                    "error": "invalid_style_validation_transition",
                    "message": (
                        "Only Queued / Running Style Validation can be "
                        "cancelled. Failure / cancel keep the record."
                    ),
                    "status": run.status,
                },
            )
        before = run.to_audit_dict()
        run.status = RUN_CANCELLED
        run.updated_at = _utc_now_z()
        run.report = run._build_report()
        self._repo.save(run)
        self._write_audit(
            actor=editor,
            action="style_validation.cancel",
            resource_id=run.id,
            before_json=before,
            after_json=run.to_audit_dict(),
        )
        return run

    def _run(
        self,
        run: StyleValidation,
        *,
        body: str,
        guide: StyleGuide | None,
    ) -> None:
        before = run.to_audit_dict()
        run.status = RUN_RUNNING
        run.updated_at = _utc_now_z()
        self._repo.save(run)
        self._write_audit(
            actor=Actor(actor_type=SYSTEM, actor_id="style_validation"),
            action="style_validation.running",
            resource_id=run.id,
            before_json=before,
            after_json=run.to_audit_dict(),
        )
        if getattr(self._repo, "force_fail", False):
            self._fail(run, reason="forced_exec_fail")
            return
        try:
            findings = run_deterministic_checks(
                body, guide=guide, thresholds=run.thresholds
            )
            if run.include_llm:
                llm_findings = self._run_llm_check(run, body=body, guide=guide)
                findings.extend(llm_findings)
            run.findings = findings
            run.report = run._build_report()
            run.status = RUN_SUCCEEDED
            run.updated_at = _utc_now_z()
            run.blocks_canon_submit = False
            self._repo.save(run)
            self._write_audit(
                actor=Actor(actor_type=SYSTEM, actor_id="style_validation"),
                action="style_validation.succeeded",
                resource_id=run.id,
                before_json=before,
                after_json=run.to_audit_dict(),
            )
        except StyleValidationServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 — Failed must keep records
            self._fail(run, reason=type(exc).__name__)

    def _run_llm_check(
        self,
        run: StyleValidation,
        *,
        body: str,
        guide: StyleGuide | None,
    ) -> list[StyleFinding]:
        if guide is None:
            run.llm_status = LLM_SKIPPED_NO_GUIDE
            run.llm_score_version = None
            return []
        request = GenerateRequest(
            model="fake-model",
            system_prompt=build_system_prompt(),
            user_prompt=build_user_prompt(
                guide=guide, draft_revision_id=run.draft_revision_id, body=body
            ),
            temperature=0.0,
            max_tokens=512,
            correlation_id=get_request_id() or run.id,
            task_type=self._task_type,
            prompt_version=PROMPT_VERSION,
        )
        try:
            response = self._gateway.generate_structured(request)
        except LlmError as exc:
            run.request_refs.append(
                {
                    "request_id": get_request_id() or run.id,
                    "raw_response_reference": None,
                    "error_code": type(exc).__name__,
                }
            )
            run.llm_status = LLM_SKIPPED
            return []
        run.request_refs.append(
            {
                "request_id": response.request_id,
                "raw_response_reference": response.raw_response_reference,
                "error_code": (
                    response.error.code if response.error is not None else None
                ),
            }
        )
        return self._findings_from_llm(run, response)

    def _findings_from_llm(
        self, run: StyleValidation, response: GenerateResponse
    ) -> list[StyleFinding]:
        if response.error is not None or not isinstance(response.parsed_output, dict):
            run.llm_status = LLM_SKIPPED
            return []
        parsed = response.parsed_output
        if _mentions_living_author(parsed):
            run.llm_status = LLM_REFUSED_LIVING_AUTHOR
            run.llm_score_version = LLM_SCORE_VERSION
            return []
        raw_findings = parsed.get("findings") or []
        if not isinstance(raw_findings, list):
            raw_findings = []
        findings: list[StyleFinding] = []
        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            if _mentions_living_author(item):
                run.llm_status = LLM_REFUSED_LIVING_AUTHOR
                continue
            findings.append(
                StyleFinding(
                    rule_id=str(item.get("rule_id") or RULE_LLM),
                    problem=str(
                        item.get("problem") or "草稿与已批准 Style Guide 不完全符合。"
                    ),
                    text_evidence=str(item.get("text_evidence") or ""),
                    severity=coerce_style_severity(
                        str(item.get("severity") or SEVERITY_WARNING)
                    ),
                    minimal_fix=str(
                        item.get("minimal_fix") or "按已批准 Style Guide 最小改写该处。"
                    ),
                )
            )
        run.llm_score_version = str(parsed.get("score_version") or LLM_SCORE_VERSION)
        if run.llm_status != LLM_REFUSED_LIVING_AUTHOR:
            run.llm_status = LLM_RAN
        return findings

    def _fail(self, run: StyleValidation, *, reason: str) -> None:
        before = run.to_audit_dict()
        run.status = RUN_FAILED
        run.failure_reason = reason
        run.updated_at = _utc_now_z()
        run.blocks_canon_submit = False
        run.report = run._build_report()
        self._repo.save(run)
        self._write_audit(
            actor=Actor(actor_type=SYSTEM, actor_id="style_validation"),
            action="style_validation.failed",
            resource_id=run.id,
            before_json=before,
            after_json=run.to_audit_dict(),
        )

    def _require_project(self, project_id: str) -> None:
        if self._story.get_project(project_id) is None:
            raise StyleValidationServiceError(404, {"error": "project_not_found"})

    def _require_scene(self, project_id: str, scene_id: str) -> Any:
        scene = self._scenes.get_scene(scene_id)
        if scene is None or scene.project_id != project_id:
            raise StyleValidationServiceError(404, {"error": "scene_not_found"})
        return scene

    def _require_draft(self, project_id: str, scene_id: str, revision_id: str) -> Any:
        draft = self._drafts.get_draft(revision_id)
        if (
            draft is None
            or draft.project_id != project_id
            or draft.scene_id != scene_id
        ):
            raise StyleValidationServiceError(404, {"error": "scene_draft_not_found"})
        return draft

    def _require_approved_guide(self, project_id: str, guide_id: str) -> StyleGuide:
        try:
            return self._style.require_usable_guide(project_id, guide_id)
        except StyleServiceError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc)}
            if detail.get("error") == "style_guide_unapproved":
                detail = {
                    **detail,
                    "llm_status": "refused_unapproved_guide",
                    "writes_canon": False,
                    "blocks_canon_submit": False,
                }
            raise StyleValidationServiceError(exc.status_code, detail) from exc

    def _optional_approved_guide(
        self, project_id: str, guide_id: str
    ) -> StyleGuide | None:
        guide = self._styles.get_guide(guide_id)
        if (
            guide is None
            or guide.project_id != project_id
            or guide.status != GUIDE_APPROVED
        ):
            return None
        return guide

    def _current_approved_guide(self, project_id: str) -> StyleGuide | None:
        for item in self._styles.list_guides(project_id):
            if item.status == GUIDE_APPROVED:
                return item
        return None

    def _require_authorized_sample(
        self, project_id: str, sample_id: str
    ) -> StyleSample:
        try:
            sample = self._style.require_usable_sample(project_id, sample_id)
        except StyleServiceError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc)}
            if detail.get("error") == "style_sample_unauthorized":
                detail = {
                    **detail,
                    "llm_status": "refused_unauthorized_sample",
                    "writes_canon": False,
                    "blocks_canon_submit": False,
                }
            raise StyleValidationServiceError(exc.status_code, detail) from exc
        if _mentions_living_author(
            {
                "source": sample.source,
                "scope_of_use": sample.scope_of_use,
            }
        ):
            raise StyleValidationServiceError(
                409,
                {
                    "error": "living_author_imitation_forbidden",
                    "message": (
                        "Style Validation must not score imitation of living "
                        "authors. Unauthorized / living-author samples cannot "
                        "be used as style references."
                    ),
                    "llm_status": LLM_REFUSED_LIVING_AUTHOR,
                    "cited_id": sample.id,
                    "writes_canon": False,
                    "blocks_canon_submit": False,
                },
            )
        return sample

    def _reject_living_author_request(
        self, extra: dict[str, Any] | None, sample_ids: list[str]
    ) -> None:
        payload = extra or {}
        if _mentions_living_author(payload) or any(
            _looks_like_living_author(item) for item in sample_ids
        ):
            raise StyleValidationServiceError(
                409,
                {
                    "error": "living_author_imitation_forbidden",
                    "message": (
                        "Style Validation evaluates conformance to this "
                        "project's approved Style Guide only. It must not "
                        "require imitating living authors."
                    ),
                    "llm_status": LLM_REFUSED_LIVING_AUTHOR,
                    "writes_canon": False,
                    "blocks_canon_submit": False,
                },
            )

    def _write_audit(
        self,
        *,
        actor: Actor,
        action: str,
        resource_id: str,
        before_json: dict[str, Any] | None,
        after_json: dict[str, Any] | None,
    ) -> None:
        self._audit.write(
            actor_type=actor.actor_type or HUMAN_EDITOR,
            actor_id=actor.actor_id,
            action=action,
            resource_type="style_validation",
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            correlation_id=get_request_id(),
        )


def _require_trigger_actor(actor: Actor) -> Actor:
    if actor.actor_type not in ALLOWED_TRIGGER_ACTORS:
        raise StyleValidationServiceError(
            403,
            {
                "error": "actor_not_allowed",
                "message": (
                    "Style Validation may be triggered by human_editor, "
                    "review_agent, or system. It is not Approval and does "
                    "not write Canon."
                ),
                "actor_type": actor.actor_type or None,
                "writes_canon": False,
                "blocks_canon_submit": False,
            },
        )
    return actor


def _mentions_living_author(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, bool):
                if item and _looks_like_living_author(str(key)):
                    return True
                continue
            if item and _looks_like_living_author(str(key)):
                return True
            if _mentions_living_author(item):
                return True
        return False
    if isinstance(value, list):
        return any(_mentions_living_author(item) for item in value)
    if isinstance(value, bool):
        return False
    return _looks_like_living_author(str(value)) if value is not None else False


def _looks_like_living_author(value: str) -> bool:
    lowered = value.casefold()
    return any(marker.casefold() in lowered for marker in LIVING_AUTHOR_MARKERS)


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
