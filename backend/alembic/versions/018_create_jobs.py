"""Create local job queue tables (node 8.1).

Revision ID: 018_jobs
Revises: 017_review_queue
Create Date: 2026-08-18

Tables:
- job_payloads — stored input references for replay
- jobs — queue rows (id, project_id, job_type, payload_reference,
  status, idempotency_key, attempt_count, max_attempts,
  scheduled_at, started_at, finished_at, error_code, error_detail,
  correlation_id, plus scene_id / lock helpers)
- job_locks — exclusive write lock per scene_id

Does not recreate audit_events, Story Project / Spec, Canon, Scene
Card, Scene Plan, Scene Draft, extract, summary, Validation Run,
Repair Task, Context Pack, Outline, Style Guide / Sample, Style
Validation, or review-queue tables. Does not add Agent registry
(8.2), DAG (8.3), batch (8.4), chapter-level generate, or
real-vendor tables. Worker does not write Canon. No production
seed-status route.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "018_jobs"
down_revision: str | None = "017_review_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE job_payloads (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            job_type TEXT NOT NULL,
            inputs JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT job_payloads_job_type_check CHECK (
                job_type IN (
                    'plan',
                    'draft',
                    'extract',
                    'validate',
                    'repair',
                    'summarize',
                    'context_pack'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE jobs (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            job_type TEXT NOT NULL,
            payload_reference UUID NOT NULL REFERENCES job_payloads (id),
            status TEXT NOT NULL,
            idempotency_key TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            scheduled_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            error_code TEXT,
            error_detail TEXT,
            correlation_id TEXT NOT NULL,
            scene_id TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            result_reference JSONB,
            dispatched_resource_type TEXT,
            dispatched_resource_id TEXT,
            rerun_of_job_id UUID,
            CONSTRAINT jobs_job_type_check CHECK (
                job_type IN (
                    'plan',
                    'draft',
                    'extract',
                    'validate',
                    'repair',
                    'summarize',
                    'context_pack'
                )
            ),
            CONSTRAINT jobs_status_check CHECK (
                status IN (
                    'queued',
                    'running',
                    'succeeded',
                    'failed',
                    'cancelled',
                    'dead_letter'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX jobs_project_idx
            ON jobs (project_id, status, job_type, scene_id)
        """
    )
    op.execute(
        """
        CREATE INDEX jobs_idempotency_idx
            ON jobs (project_id, job_type, idempotency_key)
        """
    )
    op.execute(
        """
        CREATE TABLE job_locks (
            scene_id TEXT PRIMARY KEY,
            job_id UUID NOT NULL REFERENCES jobs (id),
            locked_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE job_locks")
    op.execute("DROP TABLE jobs")
    op.execute("DROP TABLE job_payloads")
