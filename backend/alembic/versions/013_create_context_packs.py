"""Create Context Pack table (node 6.1).

Revision ID: 013_context_packs
Revises: 012_repair_tasks
Create Date: 2026-08-18

Tables:
- context_packs — immutable per-scene assembled packs
  (Assembled / Frozen / Failed / Cancelled). Re-assemble is a new
  revision / new id. Frozen rows are not overwritten.

Does not recreate audit_events, Story Project / Spec, Canon, Scene
Card, Scene Plan, Scene Draft, extract, summary, Validation Run, or
Repair Task tables. Does not add Outline / model-gateway / real-vendor
tables. A Context Pack is not Canon and freeze is not Approval.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "013_context_packs"
down_revision: str | None = "012_repair_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE context_packs (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id UUID NOT NULL REFERENCES scenes (id),
            scene_card_id UUID NOT NULL,
            story_spec_id UUID NOT NULL,
            snapshot_id UUID NOT NULL REFERENCES canon_snapshots (id),
            scene_plan_id UUID,
            purpose TEXT NOT NULL,
            revision INTEGER NOT NULL,
            status TEXT NOT NULL,
            payload JSONB NOT NULL,
            frozen_at TIMESTAMPTZ,
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT context_packs_purpose_check CHECK (
                purpose IN ('Generate', 'Validate')
            ),
            CONSTRAINT context_packs_status_check CHECK (
                status IN ('Assembled', 'Frozen', 'Failed', 'Cancelled')
            ),
            CONSTRAINT context_packs_revision_positive CHECK (revision >= 1),
            CONSTRAINT context_packs_scene_revision_unique UNIQUE (
                project_id, scene_id, revision
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX context_packs_project_scene_idx
            ON context_packs (project_id, scene_id, revision)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE context_packs")
