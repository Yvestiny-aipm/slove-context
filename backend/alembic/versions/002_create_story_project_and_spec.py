"""Create story_projects, story_specs, story_spec_versions (node 2.1).

Revision ID: 002_story_project_spec
Revises: 001_audit_events
Create Date: 2026-08-18

0.2 terminology:
- story_projects = Story Project / 故事项目 (unique novel container)
- story_specs = Story Spec / 故事规格 (editorial constraints, not Canon)
- story_spec_versions = Revision / 修订版本 of a Story Spec

MVP-normal is one Story Project. The API rejects a second project.
This node does not create Canon / entity / fact tables.
audit_events from 1.3 is unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "002_story_project_spec"
down_revision: str | None = "001_audit_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE story_projects (
            id UUID PRIMARY KEY,
            title TEXT NOT NULL,
            language TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE story_specs (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            current_version_id UUID,
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT story_specs_one_per_project UNIQUE (project_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE story_spec_versions (
            id UUID PRIMARY KEY,
            spec_id UUID NOT NULL REFERENCES story_specs (id),
            revision_number INTEGER NOT NULL,
            schema_version TEXT NOT NULL,
            title TEXT NOT NULL,
            language TEXT NOT NULL,
            status TEXT NOT NULL,
            must_write JSONB NOT NULL,
            must_not_write JSONB NOT NULL,
            notes TEXT,
            payload_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT story_spec_versions_revision_unique
                UNIQUE (spec_id, revision_number)
        )
        """
    )
    op.execute(
        """
        ALTER TABLE story_specs
            ADD CONSTRAINT story_specs_current_version_fk
            FOREIGN KEY (current_version_id)
            REFERENCES story_spec_versions (id)
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE story_specs DROP CONSTRAINT story_specs_current_version_fk"
    )
    op.execute("DROP TABLE story_spec_versions")
    op.execute("DROP TABLE story_specs")
    op.execute("DROP TABLE story_projects")
