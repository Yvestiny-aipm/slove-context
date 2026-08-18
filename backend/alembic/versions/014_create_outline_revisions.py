"""Create Outline Revision table (node 6.2).

Revision ID: 014_outline_revisions
Revises: 013_context_packs
Create Date: 2026-08-18

Tables:
- outline_revisions — one Outline Revision row. Confirmed rows are
  immutable; structural change is a new revision / new id. States
  match 0.3 §7: Drafting / Proposed / Confirmed / Revising / Failed /
  Cancelled / Rework / Superseded.

Does not recreate audit_events, Story Project / Spec, Canon, Scene
Card, Scene Plan, Scene Draft, extract, summary, Validation Run,
Repair Task, or Context Pack tables. Does not add Context Pack
assembler changes, chapter-level generate, book-level generate, or
real-vendor tables. Confirm usable is not Approval and does not
write Canon. Outline is not a generation unit.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "014_outline_revisions"
down_revision: str | None = "013_context_packs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE outline_revisions (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            lineage_id UUID NOT NULL,
            parent_revision_id UUID REFERENCES outline_revisions (id),
            superseded_by_id UUID REFERENCES outline_revisions (id),
            revision INTEGER NOT NULL,
            status TEXT NOT NULL,
            nodes JSONB NOT NULL,
            confirmed_at TIMESTAMPTZ,
            confirmed_by TEXT,
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT outline_revisions_status_check CHECK (
                status IN (
                    'Drafting',
                    'Proposed',
                    'Confirmed',
                    'Revising',
                    'Failed',
                    'Cancelled',
                    'Rework',
                    'Superseded'
                )
            ),
            CONSTRAINT outline_revisions_revision_positive CHECK (revision >= 1)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX outline_revisions_project_idx
            ON outline_revisions (project_id, revision)
        """
    )
    op.execute(
        """
        CREATE INDEX outline_revisions_lineage_idx
            ON outline_revisions (lineage_id, revision)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE outline_revisions")
