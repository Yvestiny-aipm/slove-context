"""Create Scene Plan job and plan tables (node 3.3).

Revision ID: 006_scene_plan
Revises: 005_scene_tables
Create Date: 2026-08-18

Tables:
- scene_plan_jobs — per-scene generation job (queued/running/repair/succeeded/failed)
- scene_plans — validated Scene Plan payload (intent, not Canon, not Scene Draft)

Does not recreate audit_events, Story Project / Spec, Canon, or Scene Card tables.
Does not add Scene Draft / Context Pack / model-gateway / real-vendor tables.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "006_scene_plan"
down_revision: str | None = "005_scene_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE scene_plan_jobs (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id UUID NOT NULL REFERENCES scenes (id),
            scene_card_id UUID NOT NULL,
            snapshot_id UUID NOT NULL REFERENCES canon_snapshots (id),
            prompt_version TEXT NOT NULL,
            state TEXT NOT NULL,
            plan_id UUID,
            request_refs JSONB NOT NULL,
            validation_result JSONB,
            evidence JSONB,
            transitions JSONB NOT NULL,
            failure_reason TEXT,
            repair_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT scene_plan_jobs_state_check CHECK (
                state IN ('queued', 'running', 'repair', 'succeeded', 'failed')
            ),
            CONSTRAINT scene_plan_jobs_repair_count_check CHECK (
                repair_count >= 0 AND repair_count <= 1
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE scene_plans (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id UUID NOT NULL REFERENCES scenes (id),
            job_id UUID NOT NULL REFERENCES scene_plan_jobs (id),
            snapshot_id UUID NOT NULL REFERENCES canon_snapshots (id),
            scene_card_id UUID NOT NULL,
            prompt_version TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT scene_plans_status_check CHECK (
                status IN ('Drafted', 'InReference', 'Abandoned', 'Rewritten')
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX scene_plan_jobs_project_scene_idx
            ON scene_plan_jobs (project_id, scene_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX scene_plans_project_scene_idx
            ON scene_plans (project_id, scene_id, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE scene_plans")
    op.execute("DROP TABLE scene_plan_jobs")
