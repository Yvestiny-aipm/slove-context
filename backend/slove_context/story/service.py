"""Story Project / Story Spec write path (node 2.1).

Writes go through AuditWriter. Approving a Spec never writes Canon.
Only the human 主编 can approve. A second Story Project is rejected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.logging import get_request_id
from slove_context.story.actors import (
    HUMAN_EDITOR,
    Actor,
    ActorError,
    require_human_editor,
)
from slove_context.story.models import (
    ALLOWED_LANGUAGES,
    DEFAULT_SCHEMA_VERSION,
    PROJECT_ACTIVE,
    SPEC_DRAFT,
    SPEC_EFFECTIVE,
    SPEC_WRITTEN,
    StoryProject,
    StorySpec,
    StorySpecVersion,
)
from slove_context.story.repository import StoryRepository
from slove_context.story.validate import StorySpecSchemaError, validate_story_spec


class StoryServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class StoryService:
    def __init__(self, repository: StoryRepository, audit_writer: AuditWriter) -> None:
        self._repo = repository
        self._audit = audit_writer

    def create_project(
        self,
        *,
        title: str,
        language: str,
        actor: Actor,
        created_by: str | None = None,
        project_id: str | None = None,
    ) -> StoryProject:
        if self._repo.list_projects():
            raise StoryServiceError(
                409,
                {
                    "error": "second_project_not_supported",
                    "message": (
                        "多项目 is not MVP-normal. Only one Story Project "
                        "is allowed. Creating a second project is rejected."
                    ),
                },
            )
        cleaned_title = title.strip()
        if not cleaned_title:
            raise StoryServiceError(
                422, {"error": "invalid_project", "message": "title is required"}
            )
        if language not in ALLOWED_LANGUAGES:
            raise StoryServiceError(
                422,
                {
                    "error": "invalid_project_language",
                    "message": "MVP language is Chinese only (zh-CN or 中文).",
                },
            )
        created_by_value = _require_created_by(created_by, actor)
        project = StoryProject(
            id=project_id or str(uuid4()),
            title=cleaned_title,
            language=language,
            status=PROJECT_ACTIVE,
            created_at=_utc_now_z(),
            created_by=created_by_value,
        )
        self._repo.add_project(project)
        self._write_audit(
            actor=actor,
            action="story_project.create",
            resource_type="story_project",
            resource_id=project.id,
            before_json=None,
            after_json=project.to_public_dict(),
        )
        return project

    def get_project(self, project_id: str) -> StoryProject:
        project = self._repo.get_project(project_id)
        if project is None:
            raise StoryServiceError(404, {"error": "project_not_found"})
        return project

    def list_projects(self) -> list[StoryProject]:
        return self._repo.list_projects()

    def create_spec_draft(
        self,
        *,
        project_id: str,
        payload: dict[str, Any],
        actor: Actor,
    ) -> StorySpec:
        self.get_project(project_id)
        existing = self._repo.get_spec_for_project(project_id)
        if existing is not None:
            raise StoryServiceError(
                409,
                {
                    "error": "spec_already_exists",
                    "message": (
                        "This Story Project already has a Story Spec. "
                        "After approval, create a new draft Revision instead."
                    ),
                    "spec_id": existing.id,
                },
            )
        self._reject_unapproved_as_approved(payload, action="create")
        spec_id = _optional_uuid(payload.get("id")) or str(uuid4())
        created_at = _utc_now_z()
        created_by = _require_created_by(payload.get("created_by"), actor)
        version = self._build_version(
            spec_id=spec_id,
            project_id=project_id,
            payload=payload,
            status=SPEC_DRAFT,
            revision_number=1,
            created_at=created_at,
            created_by=created_by,
        )
        spec = StorySpec(
            id=spec_id,
            project_id=project_id,
            current_version_id=version.id,
            status=SPEC_DRAFT,
            created_at=created_at,
            created_by=created_by,
            versions=[version],
        )
        self._repo.add_spec(spec)
        self._write_audit(
            actor=actor,
            action="story_spec.create_draft",
            resource_type="story_spec",
            resource_id=spec.id,
            before_json=None,
            after_json=_spec_audit_after(spec),
        )
        return spec

    def get_current_spec(self, project_id: str) -> StorySpec:
        self.get_project(project_id)
        spec = self._repo.get_spec_for_project(project_id)
        if spec is None:
            raise StoryServiceError(404, {"error": "spec_not_found"})
        return spec

    def get_spec(self, project_id: str, spec_id: str) -> StorySpec:
        self.get_project(project_id)
        spec = self._repo.get_spec(spec_id)
        if spec is None or spec.project_id != project_id:
            raise StoryServiceError(404, {"error": "spec_not_found"})
        return spec

    def submit_spec(self, project_id: str, spec_id: str, actor: Actor) -> StorySpec:
        spec = self.get_spec(project_id, spec_id)
        if spec.status != SPEC_DRAFT:
            raise StoryServiceError(
                409,
                {
                    "error": "invalid_spec_transition",
                    "message": "Only a Draft Story Spec can be submitted (主编写定).",
                    "status": spec.status,
                },
            )
        before = _spec_audit_after(spec)
        self._set_current_status(spec, SPEC_WRITTEN)
        self._repo.save_spec(spec)
        self._write_audit(
            actor=actor,
            action="story_spec.submit",
            resource_type="story_spec",
            resource_id=spec.id,
            before_json=before,
            after_json=_spec_audit_after(spec),
        )
        return spec

    def approve_spec(self, project_id: str, spec_id: str, actor: Actor) -> StorySpec:
        try:
            require_human_editor(actor)
        except ActorError as exc:
            raise StoryServiceError(
                403,
                {
                    "error": "human_editor_required",
                    "message": str(exc),
                    "actor_type": actor.actor_type or None,
                },
            ) from exc
        spec = self.get_spec(project_id, spec_id)
        if spec.status == SPEC_EFFECTIVE:
            raise StoryServiceError(
                409,
                {
                    "error": "spec_already_approved",
                    "message": "Story Spec is already Effective. This is not Canon approval.",
                },
            )
        if spec.status != SPEC_WRITTEN:
            raise StoryServiceError(
                409,
                {
                    "error": "unapproved_spec_cannot_be_frozen",
                    "message": (
                        "An unapproved Story Spec cannot be frozen or treated "
                        "as approved. Submit the draft first (Draft → Written), "
                        "then the human 主编 may approve (Written → Effective). "
                        "No auto-approval path exists. Spec approval is not Canon approval."
                    ),
                    "status": spec.status,
                },
            )
        before = _spec_audit_after(spec)
        self._set_current_status(spec, SPEC_EFFECTIVE)
        self._repo.save_spec(spec)
        self._write_audit(
            actor=actor,
            action="story_spec.approve",
            resource_type="story_spec",
            resource_id=spec.id,
            before_json=before,
            after_json=_spec_audit_after(spec),
        )
        return spec

    def list_versions(self, project_id: str, spec_id: str) -> list[StorySpecVersion]:
        spec = self.get_spec(project_id, spec_id)
        return sorted(spec.versions, key=lambda item: item.revision_number)

    def create_next_draft(
        self,
        *,
        project_id: str,
        spec_id: str,
        payload: dict[str, Any],
        actor: Actor,
    ) -> StorySpec:
        spec = self.get_spec(project_id, spec_id)
        if spec.status != SPEC_EFFECTIVE:
            raise StoryServiceError(
                409,
                {
                    "error": "new_draft_requires_approved_spec",
                    "message": (
                        "A next draft Revision is created from an approved "
                        "(Effective) Spec. Unapproved Specs are edited as Draft."
                    ),
                    "status": spec.status,
                },
            )
        self._reject_unapproved_as_approved(payload, action="create_next_draft")
        before = _spec_audit_after(spec)
        created_at = _utc_now_z()
        created_by = _require_created_by(payload.get("created_by"), actor)
        next_revision = max(item.revision_number for item in spec.versions) + 1
        version = self._build_version(
            spec_id=spec.id,
            project_id=project_id,
            payload=payload,
            status=SPEC_DRAFT,
            revision_number=next_revision,
            created_at=created_at,
            created_by=created_by,
        )
        spec.versions.append(version)
        spec.current_version_id = version.id
        spec.status = SPEC_DRAFT
        self._repo.save_spec(spec)
        self._write_audit(
            actor=actor,
            action="story_spec.create_draft_revision",
            resource_type="story_spec",
            resource_id=spec.id,
            before_json=before,
            after_json=_spec_audit_after(spec),
        )
        return spec

    def patch_spec(
        self,
        *,
        project_id: str,
        spec_id: str,
        payload: dict[str, Any],
        actor: Actor,
    ) -> StorySpec:
        spec = self.get_spec(project_id, spec_id)
        if spec.status == SPEC_EFFECTIVE:
            raise StoryServiceError(
                409,
                {
                    "error": "approved_spec_immutable",
                    "message": (
                        "An approved Story Spec cannot be modified in place. "
                        "Changes after approval MUST create a new draft Revision "
                        "(POST .../drafts). PATCH of an approved Spec is rejected."
                    ),
                    "status": spec.status,
                },
            )
        if spec.status != SPEC_DRAFT:
            raise StoryServiceError(
                409,
                {
                    "error": "spec_not_editable_in_place",
                    "message": (
                        "Only a Draft Story Spec can be PATCHed. "
                        "After approval, create a new draft Revision."
                    ),
                    "status": spec.status,
                },
            )
        self._reject_unapproved_as_approved(payload, action="patch")
        before = _spec_audit_after(spec)
        current = spec.current_version()
        merged = dict(current.payload)
        for key in (
            "title",
            "language",
            "must_write",
            "must_not_write",
            "notes",
            "schema_version",
        ):
            if key in payload:
                merged[key] = payload[key]
        created_by = current.created_by
        version = self._build_version(
            spec_id=spec.id,
            project_id=project_id,
            payload=merged,
            status=SPEC_DRAFT,
            revision_number=current.revision_number,
            created_at=current.created_at,
            created_by=created_by,
            version_id=current.id,
        )
        spec.versions = [
            version if item.id == current.id else item for item in spec.versions
        ]
        spec.current_version_id = version.id
        self._repo.save_spec(spec)
        self._write_audit(
            actor=actor,
            action="story_spec.update_draft",
            resource_type="story_spec",
            resource_id=spec.id,
            before_json=before,
            after_json=_spec_audit_after(spec),
        )
        return spec

    def _build_version(
        self,
        *,
        spec_id: str,
        project_id: str,
        payload: dict[str, Any],
        status: str,
        revision_number: int,
        created_at: str,
        created_by: str,
        version_id: str | None = None,
    ) -> StorySpecVersion:
        if payload.get("project_id") not in (None, project_id):
            raise StoryServiceError(
                422,
                {
                    "error": "project_id_mismatch",
                    "message": "payload.project_id must match the URL project.",
                },
            )
        if payload.get("id") not in (None, spec_id):
            raise StoryServiceError(
                422,
                {
                    "error": "spec_id_mismatch",
                    "message": "payload.id must match the Story Spec id.",
                },
            )
        assembled = _assemble_spec_payload(
            payload,
            spec_id=spec_id,
            project_id=project_id,
            created_at=payload.get("created_at") or created_at,
            created_by=created_by,
            status=status,
        )
        try:
            validate_story_spec(assembled)
        except StorySpecSchemaError as exc:
            raise StoryServiceError(
                422,
                {
                    "error": "story_spec_schema_invalid",
                    "message": "Story Spec failed contracts/story-spec.schema.json.",
                    "errors": exc.errors,
                },
            ) from exc
        return StorySpecVersion(
            id=version_id or str(uuid4()),
            spec_id=spec_id,
            revision_number=revision_number,
            schema_version=str(assembled["schema_version"]),
            title=str(assembled["title"]),
            language=str(assembled["language"]),
            status=status,
            must_write=list(assembled["must_write"]),
            must_not_write=list(assembled["must_not_write"]),
            notes=assembled.get("notes")
            if isinstance(assembled.get("notes"), str)
            else None,
            payload=assembled,
            created_at=created_at,
            created_by=created_by,
        )

    def _set_current_status(self, spec: StorySpec, status: str) -> None:
        current = spec.current_version()
        current.status = status
        current.payload = {**current.payload, "status": status}
        try:
            validate_story_spec(current.payload)
        except StorySpecSchemaError as exc:
            raise StoryServiceError(
                422,
                {
                    "error": "story_spec_schema_invalid",
                    "message": "Story Spec failed contracts/story-spec.schema.json.",
                    "errors": exc.errors,
                },
            ) from exc
        spec.status = status

    def _reject_unapproved_as_approved(
        self, payload: dict[str, Any], *, action: str
    ) -> None:
        status = payload.get("status")
        if status in (SPEC_EFFECTIVE, SPEC_WRITTEN):
            raise StoryServiceError(
                422,
                {
                    "error": "unapproved_spec_cannot_be_frozen",
                    "message": (
                        "An unapproved Story Spec cannot be created or edited "
                        f"as {status}. {action} always produces Draft. "
                        "Only the human 主编 can later approve a submitted Spec. "
                        "No auto-approval path exists."
                    ),
                    "status": status,
                },
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
        actor_type = actor.actor_type or HUMAN_EDITOR
        self._audit.write(
            actor_type=actor_type,
            actor_id=actor.actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            correlation_id=get_request_id(),
        )


def _assemble_spec_payload(
    payload: dict[str, Any],
    *,
    spec_id: str,
    project_id: str,
    created_at: str,
    created_by: str,
    status: str,
) -> dict[str, Any]:
    assembled: dict[str, Any] = {
        "schema_version": payload.get("schema_version") or DEFAULT_SCHEMA_VERSION,
        "id": spec_id,
        "project_id": project_id,
        "created_at": created_at if _looks_like_utc_z(created_at) else _utc_now_z(),
        "created_by": created_by,
        "title": payload.get("title"),
        "language": payload.get("language"),
        "status": status,
        "must_write": payload.get("must_write"),
        "must_not_write": payload.get("must_not_write"),
    }
    if "notes" in payload and payload["notes"] is not None:
        assembled["notes"] = payload["notes"]
    return assembled


def _spec_audit_after(spec: StorySpec) -> dict[str, Any]:
    version = spec.current_version()
    return {
        "id": spec.id,
        "project_id": spec.project_id,
        "status": spec.status,
        "revision_number": version.revision_number,
        "title": version.title,
        "language": version.language,
    }


def _require_created_by(created_by: Any, actor: Actor) -> str:
    if isinstance(created_by, str) and created_by.strip():
        return created_by.strip()
    if actor.actor_id:
        return actor.actor_id
    raise StoryServiceError(
        422,
        {
            "error": "created_by_required",
            "message": "created_by or X-Actor-Id is required (human 主编).",
        },
    )


def _optional_uuid(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _looks_like_utc_z(value: str) -> bool:
    return value.endswith("Z") and "T" in value


def _utc_now_z() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
