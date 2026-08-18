"""Create Candidate Change extract tables (node 4.1).

Revision ID: 008_extract
Revises: 007_scene_draft
Create Date: 2026-08-18

Tables:
- extract_jobs — per-scene, per-draft extract job
  (queued/running/repair/succeeded/failed/cancelled)
- candidate_changes — append-only Candidate Change rows (Extracted)

Also allows Scene Draft status Extracted (status-only; body stays
immutable). Does not recreate audit_events, Story Project / Spec, Canon,
Scene Card, Scene Plan, or Scene Draft tables. Does not add Validation
Run / Context Pack / model-gateway / real-vendor tables. No approve or
submit. No Canon writes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "008_extract"
down_revision: str | None = "007_scene_draft"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE scene_drafts
            DROP CONSTRAINT scene_drafts_status_check
        """
    )
    op.execute(
        """
        ALTER TABLE scene_drafts
            ADD CONSTRAINT scene_drafts_status_check CHECK (
                status IN (
                    'Generated', 'Extracted', 'Failed', 'Cancelled', 'Superseded'
                )
            )
        """
    )
    op.execute(
        """
        CREATE TABLE extract_jobs (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id UUID NOT NULL REFERENCES scenes (id),
            draft_id UUID NOT NULL REFERENCES scene_drafts (id),
            draft_revision INTEGER NOT NULL,
            idempotency_key TEXT,
            prompt_version TEXT NOT NULL,
            state TEXT NOT NULL,
            extract_batch INTEGER,
            candidate_ids JSONB NOT NULL,
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
            CONSTRAINT extract_jobs_state_check CHECK (
                state IN (
                    'queued', 'running', 'repair', 'succeeded',
                    'failed', 'cancelled'
                )
            ),
            CONSTRAINT extract_jobs_repair_count_check CHECK (
                repair_count >= 0 AND repair_count <= 1
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE candidate_changes (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id UUID NOT NULL REFERENCES scenes (id),
            draft_id UUID NOT NULL REFERENCES scene_drafts (id),
            job_id UUID NOT NULL REFERENCES extract_jobs (id),
            extract_batch INTEGER NOT NULL,
            schema_version TEXT NOT NULL,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object TEXT NOT NULL,
            value TEXT NOT NULL,
            effective_story_time TEXT NOT NULL,
            source_scene_id UUID NOT NULL,
            evidence_quote TEXT NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            status TEXT NOT NULL DEFAULT 'Extracted',
            payload_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT candidate_changes_status_check CHECK (
                status IN (
                    'Extracted', 'Validating', 'FailedValidation',
                    'AwaitingVerdict', 'Approved', 'Rejected', 'Submitted',
                    'Failed', 'Cancelled', 'Rework'
                )
            ),
            CONSTRAINT candidate_changes_confidence_check CHECK (
                confidence >= 0 AND confidence <= 1
            ),
            CONSTRAINT candidate_changes_batch_positive CHECK (
                extract_batch >= 1
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX extract_jobs_project_scene_idx
            ON extract_jobs (project_id, scene_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX extract_jobs_idempotency_idx
            ON extract_jobs (project_id, scene_id, draft_id, idempotency_key)
        """
    )
    op.execute(
        """
        CREATE INDEX candidate_changes_project_scene_idx
            ON candidate_changes (project_id, scene_id, extract_batch, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE candidate_changes")
    op.execute("DROP TABLE extract_jobs")
    op.execute(
        """
        ALTER TABLE scene_drafts
            DROP CONSTRAINT scene_drafts_status_check
        """
    )
    op.execute(
        """
        ALTER TABLE scene_drafts
            ADD CONSTRAINT scene_drafts_status_check CHECK (
                status IN ('Generated', 'Failed', 'Cancelled', 'Superseded')
            )
        """
    )
