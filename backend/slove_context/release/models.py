"""Release check, manifest, export, due-item, and waiver records (node 9.3).

Checks are read-only over existing artifacts. A failed check is kept
and is not a formal release. Manifests are immutable after finish.
Exports only copy already-approved Scene Draft prose.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

GATE_DRAFTS_APPROVED = "drafts_human_approved"
GATE_NO_UNHANDLED_BLOCKERS = "no_unhandled_blockers"
GATE_CANDIDATES_RESOLVED = "candidates_resolved"
GATE_SNAPSHOT_FROZEN = "snapshot_frozen"
GATE_CHAPTER_SUMMARIES = "chapter_summaries"
GATE_FORESHADOWING = "foreshadowing"
GATE_STYLE_AND_SAFETY = "style_and_safety"
GATE_AUDIT_COMPLETE = "audit_complete"

GATE_IDS = (
    GATE_DRAFTS_APPROVED,
    GATE_NO_UNHANDLED_BLOCKERS,
    GATE_CANDIDATES_RESOLVED,
    GATE_SNAPSHOT_FROZEN,
    GATE_CHAPTER_SUMMARIES,
    GATE_FORESHADOWING,
    GATE_STYLE_AND_SAFETY,
    GATE_AUDIT_COMPLETE,
)

CHECK_QUEUED = "queued"
CHECK_RUNNING = "running"
CHECK_PASSED = "passed"
CHECK_FAILED = "failed"
CHECK_CANCELLED = "cancelled"

CHECK_STATUSES = frozenset(
    {CHECK_QUEUED, CHECK_RUNNING, CHECK_PASSED, CHECK_FAILED, CHECK_CANCELLED}
)
CHECK_TERMINAL = frozenset({CHECK_PASSED, CHECK_FAILED, CHECK_CANCELLED})

DUE_STATUS_DUE = "due"
DUE_STATUS_HANDLED = "handled"
DUE_STATUS_WAIVED = "waived"
DUE_STATUSES = frozenset({DUE_STATUS_DUE, DUE_STATUS_HANDLED, DUE_STATUS_WAIVED})

WAIVER_DUE_ITEM = "due_item"
WAIVER_SAFETY = "safety"
WAIVER_KINDS = frozenset({WAIVER_DUE_ITEM, WAIVER_SAFETY})

SAFETY_RECORDED = "recorded"
SAFETY_WAIVED = "waived"
SAFETY_PLACEHOLDER = "placeholder"
SAFETY_STATUSES = frozenset({SAFETY_RECORDED, SAFETY_WAIVED})

EXPORT_MARKDOWN = "markdown"
EXPORT_JSON = "json"
EXPORT_REVIEW_PACK = "review_pack"
EXPORT_FORMATS = frozenset({EXPORT_MARKDOWN, EXPORT_JSON, EXPORT_REVIEW_PACK})

MANIFEST_SCHEMA = "release-manifest.v1"
REVIEW_PACK_SCHEMA = "release-review-pack.v1"


def _identity_flags(*, formal: bool = False) -> dict[str, Any]:
    return {
        "writes_canon": False,
        "auto_approved": False,
        "is_approval": False,
        "is_canon_approval": False,
        "is_canon": False,
        "is_published": False,
        "used_real_model": False,
        "used_real_safety_vendor": False,
        "is_formal_release": formal,
        "generates_prose": False,
    }


def stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class GateFailure:
    gate_id: str
    code: str
    message: str
    refs: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "code": self.code,
            "message": self.message,
            "refs": list(self.refs),
        }


@dataclass
class GateResult:
    gate_id: str
    passed: bool
    failures: list[GateFailure] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "failures": [item.to_public_dict() for item in self.failures],
        }


@dataclass
class DueItem:
    """Minimal foreshadowing due-item. Not a full foreshadowing product."""

    id: str
    project_id: str
    title: str
    status: str
    created_at: str
    created_by: str
    actor_type: str
    scene_id: str | None = None
    chapter_id: str | None = None
    note: str | None = None
    waiver_id: str | None = None
    handled_at: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "status": self.status,
            "scene_id": self.scene_id,
            "chapter_id": self.chapter_id,
            "note": self.note,
            "waiver_id": self.waiver_id,
            "handled_at": self.handled_at,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            **_identity_flags(),
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "status": self.status,
            "scene_id": self.scene_id,
            "chapter_id": self.chapter_id,
            "waiver_id": self.waiver_id,
            "has_note": bool(self.note),
            **_identity_flags(),
        }


@dataclass
class HumanWaiver:
    id: str
    project_id: str
    kind: str
    subject_id: str
    reason_code: str
    created_at: str
    created_by: str
    actor_type: str
    comment: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "kind": self.kind,
            "subject_id": self.subject_id,
            "reason_code": self.reason_code,
            "comment": self.comment,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            **_identity_flags(),
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "kind": self.kind,
            "subject_id": self.subject_id,
            "reason_code": self.reason_code,
            "has_comment": bool(self.comment),
            **_identity_flags(),
        }


@dataclass
class SafetyCheck:
    """Deterministic placeholder. No real safety-vendor API."""

    id: str
    project_id: str
    status: str
    result: str
    created_at: str
    created_by: str
    actor_type: str
    scene_ids: list[str] = field(default_factory=list)
    waiver_id: str | None = None
    vendor: str = SAFETY_PLACEHOLDER

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "status": self.status,
            "result": self.result,
            "vendor": self.vendor,
            "scene_ids": list(self.scene_ids),
            "waiver_id": self.waiver_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            **_identity_flags(),
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "status": self.status,
            "result": self.result,
            "vendor": self.vendor,
            "scene_ids": list(self.scene_ids),
            "waiver_id": self.waiver_id,
            **_identity_flags(),
        }


@dataclass
class ReleaseManifest:
    id: str
    project_id: str
    check_id: str
    schema_version: str
    content_hash: str
    payload: dict[str, Any]
    created_at: str
    created_by: str
    actor_type: str

    def to_public_dict(self) -> dict[str, Any]:
        body = dict(self.payload)
        body.update(
            {
                "id": self.id,
                "project_id": self.project_id,
                "check_id": self.check_id,
                "schema_version": self.schema_version,
                "content_hash": self.content_hash,
                "created_at": self.created_at,
                "created_by": self.created_by,
                "actor_type": self.actor_type,
                "immutable": True,
                **_identity_flags(formal=True),
            }
        )
        return body

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "check_id": self.check_id,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
            "version_ref_keys": sorted(self.payload.get("version_refs", {}).keys()),
            **_identity_flags(formal=True),
        }

    def hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "check_id": self.check_id,
            "payload": self.payload,
        }


@dataclass
class ReleaseExport:
    id: str
    project_id: str
    check_id: str
    manifest_id: str
    fmt: str
    content_hash: str
    created_at: str
    created_by: str
    actor_type: str
    markdown: str | None = None
    json_body: dict[str, Any] | None = None
    review_pack: dict[str, Any] | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "check_id": self.check_id,
            "manifest_id": self.manifest_id,
            "format": self.fmt,
            "content_hash": self.content_hash,
            "markdown": self.markdown,
            "json": dict(self.json_body) if self.json_body is not None else None,
            "review_pack": dict(self.review_pack)
            if self.review_pack is not None
            else None,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            **_identity_flags(formal=True),
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "check_id": self.check_id,
            "manifest_id": self.manifest_id,
            "format": self.fmt,
            "content_hash": self.content_hash,
            "has_markdown": self.markdown is not None,
            "has_json": self.json_body is not None,
            "has_review_pack": self.review_pack is not None,
            **_identity_flags(formal=True),
        }


@dataclass
class ReleaseCheck:
    id: str
    project_id: str
    snapshot_id: str
    status: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    scene_ids: list[str] = field(default_factory=list)
    chapter_ids: list[str] = field(default_factory=list)
    draft_ids: list[str] = field(default_factory=list)
    gate_results: list[GateResult] = field(default_factory=list)
    failures: list[GateFailure] = field(default_factory=list)
    manifest_id: str | None = None
    export_ids: list[str] = field(default_factory=list)
    failure_reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == CHECK_PASSED

    @property
    def is_formal_release(self) -> bool:
        return self.status == CHECK_PASSED and self.manifest_id is not None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "passed": self.passed,
            "scene_ids": list(self.scene_ids),
            "chapter_ids": list(self.chapter_ids),
            "draft_ids": list(self.draft_ids),
            "gates": [item.to_public_dict() for item in self.gate_results],
            "failures": [item.to_public_dict() for item in self.failures],
            "manifest_id": self.manifest_id,
            "export_ids": list(self.export_ids),
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "gates_run": [item.gate_id for item in self.gate_results],
            "missing_gate": None,
            **_identity_flags(formal=self.is_formal_release),
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "passed": self.passed,
            "scene_ids": list(self.scene_ids),
            "chapter_ids": list(self.chapter_ids),
            "draft_ids": list(self.draft_ids),
            "failure_codes": [item.code for item in self.failures],
            "gate_ids": [item.gate_id for item in self.gate_results],
            "manifest_id": self.manifest_id,
            "export_ids": list(self.export_ids),
            "failure_reason": self.failure_reason,
            **_identity_flags(formal=self.is_formal_release),
        }
