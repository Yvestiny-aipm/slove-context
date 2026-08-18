"""In-process Story Project / Story Spec / Revision records (node 2.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 0.2 Story Spec lifecycle: 草稿 → 主编写定 → 生效约束
SPEC_DRAFT = "Draft"
SPEC_WRITTEN = "Written"
SPEC_EFFECTIVE = "Effective"

SPEC_STATUSES = frozenset({SPEC_DRAFT, SPEC_WRITTEN, SPEC_EFFECTIVE})

# 0.2 Story Project: 创建 → 唯一存活（进行中）
PROJECT_ACTIVE = "Active"

DEFAULT_SCHEMA_VERSION = "0.4.0"
ALLOWED_LANGUAGES = frozenset({"zh-CN", "中文"})


@dataclass
class StoryProject:
    id: str
    title: str
    language: str
    status: str
    created_at: str
    created_by: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "language": self.language,
            "status": self.status,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }


@dataclass
class StorySpecVersion:
    """One Revision of a Story Spec (0.2 Revision)."""

    id: str
    spec_id: str
    revision_number: int
    schema_version: str
    title: str
    language: str
    status: str
    must_write: list[str]
    must_not_write: list[str]
    notes: str | None
    payload: dict[str, Any]
    created_at: str
    created_by: str

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "spec_id": self.spec_id,
            "revision_number": self.revision_number,
            "status": self.status,
            "title": self.title,
            "language": self.language,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }


@dataclass
class StorySpec:
    id: str
    project_id: str
    current_version_id: str
    status: str
    created_at: str
    created_by: str
    versions: list[StorySpecVersion] = field(default_factory=list)

    def current_version(self) -> StorySpecVersion:
        for version in self.versions:
            if version.id == self.current_version_id:
                return version
        raise KeyError(f"current version {self.current_version_id} missing")

    def to_public_dict(self) -> dict[str, Any]:
        version = self.current_version()
        return {
            "id": self.id,
            "project_id": self.project_id,
            "status": self.status,
            "revision_number": version.revision_number,
            "current_version_id": self.current_version_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "spec": dict(version.payload),
        }
