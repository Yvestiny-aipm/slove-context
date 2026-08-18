"""Create Style Guide / Style Sample tables (node 7.1).

Revision ID: 015_style
Revises: 014_outline_revisions
Create Date: 2026-08-18

Tables:
- style_guides — versioned Style Guide rows. Approved rows are
  immutable; changes open a new revision / new id.
- style_samples — versioned Style Sample rows. Authorized rows are
  immutable; changes open a new revision / new id.

Incremental columns on scene_drafts (reference only; does not change
3.4 generate job behavior):
- style_guide_revision_id
- style_sample_ids

Does not recreate audit_events, Story Project / Spec, Canon, Scene
Card, Scene Plan, Scene Draft, extract, summary, Validation Run,
Repair Task, Context Pack, or Outline tables. Does not add style
scoring (7.2), review queue (7.3), chapter-level generate, or
real-vendor tables. Approving a style asset is not Approval of Canon
and does not write Canon.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "015_style"
down_revision: str | None = "014_outline_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE style_guides (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            lineage_id UUID NOT NULL,
            parent_revision_id UUID REFERENCES style_guides (id),
            superseded_by_id UUID REFERENCES style_guides (id),
            revision INTEGER NOT NULL,
            status TEXT NOT NULL,
            pov TEXT NOT NULL,
            person TEXT NOT NULL,
            tense TEXT NOT NULL,
            narrative_distance TEXT NOT NULL,
            tone TEXT NOT NULL,
            rhythm TEXT NOT NULL,
            dialogue_rules JSONB NOT NULL,
            vocabulary_preferences JSONB NOT NULL,
            forbidden_expressions JSONB NOT NULL,
            positive_examples JSONB NOT NULL,
            negative_examples JSONB NOT NULL,
            approved_at TIMESTAMPTZ,
            approved_by TEXT,
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT style_guides_status_check CHECK (
                status IN (
                    'Draft',
                    'Approved',
                    'Superseded',
                    'Failed',
                    'Cancelled'
                )
            ),
            CONSTRAINT style_guides_revision_positive CHECK (revision >= 1)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX style_guides_project_idx
            ON style_guides (project_id, revision)
        """
    )
    op.execute(
        """
        CREATE INDEX style_guides_lineage_idx
            ON style_guides (lineage_id, revision)
        """
    )
    op.execute(
        """
        CREATE TABLE style_samples (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            lineage_id UUID NOT NULL,
            parent_revision_id UUID REFERENCES style_samples (id),
            superseded_by_id UUID REFERENCES style_samples (id),
            revision INTEGER NOT NULL,
            status TEXT NOT NULL,
            source TEXT NOT NULL,
            copyright_mark TEXT NOT NULL,
            scope_of_use TEXT NOT NULL,
            body TEXT NOT NULL,
            authorized_at TIMESTAMPTZ,
            authorized_by TEXT,
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT style_samples_status_check CHECK (
                status IN (
                    'Draft',
                    'Authorized',
                    'Superseded',
                    'Failed',
                    'Cancelled'
                )
            ),
            CONSTRAINT style_samples_revision_positive CHECK (revision >= 1)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX style_samples_project_idx
            ON style_samples (project_id, revision)
        """
    )
    op.execute(
        """
        CREATE INDEX style_samples_lineage_idx
            ON style_samples (lineage_id, revision)
        """
    )
    op.execute(
        """
        ALTER TABLE scene_drafts
            ADD COLUMN style_guide_revision_id UUID
                REFERENCES style_guides (id),
            ADD COLUMN style_sample_ids JSONB
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE scene_drafts
            DROP COLUMN IF EXISTS style_sample_ids,
            DROP COLUMN IF EXISTS style_guide_revision_id
        """
    )
    op.execute("DROP TABLE style_samples")
    op.execute("DROP TABLE style_guides")
