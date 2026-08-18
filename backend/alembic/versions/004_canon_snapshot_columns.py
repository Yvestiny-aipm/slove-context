"""Add Canon Snapshot freeze / replay columns (node 2.3).

Revision ID: 004_canon_snapshot
Revises: 003_canon_tables
Create Date: 2026-08-18

Incremental ALTER of canon_snapshots (created in 2.2). Adds:
- fact_ids
- frozen_at
- as_of_scene_seq
- as_of_story_time
- status

Does not recreate Canon tables. Does not add vector columns,
Scene Card tables, Context Pack, or a generator.
audit_events and Story Project / Spec / Canon Fact tables are unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "004_canon_snapshot"
down_revision: str | None = "003_canon_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE canon_snapshots
            ADD COLUMN fact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN frozen_at TIMESTAMPTZ,
            ADD COLUMN as_of_scene_seq INTEGER,
            ADD COLUMN as_of_story_time TEXT,
            ADD COLUMN status TEXT NOT NULL DEFAULT 'unfrozen'
        """
    )
    op.execute(
        """
        ALTER TABLE canon_snapshots
            ADD CONSTRAINT canon_snapshots_status_check CHECK (
                status IN ('unfrozen', 'frozen')
            )
        """
    )
    op.execute(
        """
        UPDATE canon_snapshots
            SET fact_ids = approved_fact_ids
            WHERE fact_ids = '[]'::jsonb
              AND approved_fact_ids IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE canon_snapshots DROP CONSTRAINT canon_snapshots_status_check"
    )
    op.execute(
        """
        ALTER TABLE canon_snapshots
            DROP COLUMN status,
            DROP COLUMN as_of_story_time,
            DROP COLUMN as_of_scene_seq,
            DROP COLUMN frozen_at,
            DROP COLUMN fact_ids
        """
    )
