"""Create Scene Draft job and immutable draft tables (node 3.4).

Revision ID: 007_scene_draft
Revises: 006_scene_plan
Create Date: 2026-08-18

Tables:
- scene_draft_jobs — per-scene generation job
  (queued/running/succeeded/failed/cancelled)
- scene_drafts — immutable Scene Draft revisions (body + metadata + hash)

Does not recreate audit_events, Story Project / Spec, Canon, Scene Card,
or Scene Plan tables. Does not add Context Pack / Candidate Change /
model-gateway / real-vendor tables. No automatic fact extraction (4.1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "007_scene_draft"
down_revision: str | None = "006_scene_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE scene_draft_jobs (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id UUID NOT NULL REFERENCES scenes (id),
            scene_card_id UUID NOT NULL,
            plan_id UUID NOT NULL REFERENCES scene_plans (id),
            snapshot_id UUID NOT NULL REFERENCES canon_snapshots (id),
            context_pack_id UUID NOT NULL,
            idempotency_key TEXT,
            prompt_version TEXT NOT NULL,
            state TEXT NOT NULL,
            draft_id UUID,
            draft_revision INTEGER,
            request_refs JSONB NOT NULL,
            evidence JSONB,
            transitions JSONB NOT NULL,
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT scene_draft_jobs_state_check CHECK (
                state IN (
                    'queued', 'running', 'succeeded', 'failed', 'cancelled'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE scene_drafts (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id UUID NOT NULL REFERENCES scenes (id),
            job_id UUID NOT NULL REFERENCES scene_draft_jobs (id),
            revision INTEGER NOT NULL,
            status TEXT NOT NULL,
            body TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            character_count INTEGER NOT NULL,
            word_count_estimate INTEGER NOT NULL,
            generation_model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL,
            scene_card_id UUID NOT NULL,
            plan_id UUID NOT NULL,
            snapshot_id UUID NOT NULL,
            context_pack_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT scene_drafts_status_check CHECK (
                status IN ('Generated', 'Failed', 'Cancelled', 'Superseded')
            ),
            CONSTRAINT scene_drafts_revision_positive CHECK (revision >= 1),
            CONSTRAINT scene_drafts_scene_revision_unique UNIQUE (
                project_id, scene_id, revision
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX scene_draft_jobs_project_scene_idx
            ON scene_draft_jobs (project_id, scene_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX scene_draft_jobs_idempotency_idx
            ON scene_draft_jobs (project_id, scene_id, idempotency_key)
        """
    )
    op.execute(
        """
        CREATE INDEX scene_drafts_project_scene_idx
            ON scene_drafts (project_id, scene_id, revision DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE scene_drafts")
    op.execute("DROP TABLE scene_draft_jobs")
