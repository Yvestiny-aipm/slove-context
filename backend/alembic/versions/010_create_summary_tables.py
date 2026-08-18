"""Create Scene / Chapter summary tables (node 4.3).

Revision ID: 010_summaries
Revises: 009_candidate_approval
Create Date: 2026-08-18

Tables:
- summary_jobs — scene or chapter summary job
  (queued/running/succeeded/failed/cancelled)
- scene_summaries — immutable Scene Summary revisions
- chapter_summaries — immutable Chapter Summary revisions
  (rolled up from scene summaries; not chapter prose)

Does not recreate audit_events, Story Project / Spec, Canon, Scene Card,
Scene Plan, Scene Draft, or extract tables. Does not add Validation Run
/ Context Pack / model-gateway / real-vendor tables. Summaries are not
Canon and are not Candidate Changes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "010_summaries"
down_revision: str | None = "009_candidate_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE summary_jobs (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            kind TEXT NOT NULL,
            scene_id UUID REFERENCES scenes (id),
            chapter_id UUID REFERENCES chapters (id),
            draft_revision_id UUID REFERENCES scene_drafts (id),
            source_draft_content_hash TEXT,
            source_scene_summary_revision_ids JSONB NOT NULL,
            idempotency_key TEXT,
            prompt_version TEXT NOT NULL,
            state TEXT NOT NULL,
            summary_id UUID,
            summary_revision INTEGER,
            request_refs JSONB NOT NULL,
            evidence JSONB,
            transitions JSONB NOT NULL,
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT summary_jobs_kind_check CHECK (
                kind IN ('scene', 'chapter')
            ),
            CONSTRAINT summary_jobs_state_check CHECK (
                state IN (
                    'queued', 'running', 'succeeded', 'failed', 'cancelled'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE scene_summaries (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id UUID NOT NULL REFERENCES scenes (id),
            job_id UUID NOT NULL REFERENCES summary_jobs (id),
            revision INTEGER NOT NULL,
            status TEXT NOT NULL,
            body TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            source_draft_revision_id UUID NOT NULL REFERENCES scene_drafts (id),
            source_draft_revision INTEGER NOT NULL,
            source_draft_content_hash TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL,
            generation_model TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT scene_summaries_status_check CHECK (
                status IN ('Generated', 'Superseded')
            ),
            CONSTRAINT scene_summaries_revision_positive CHECK (revision >= 1),
            CONSTRAINT scene_summaries_scene_revision_unique UNIQUE (
                project_id, scene_id, revision
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chapter_summaries (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            chapter_id UUID NOT NULL REFERENCES chapters (id),
            job_id UUID NOT NULL REFERENCES summary_jobs (id),
            revision INTEGER NOT NULL,
            status TEXT NOT NULL,
            body TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            source_scene_summary_revision_ids JSONB NOT NULL,
            prompt_version TEXT NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL,
            generation_model TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT chapter_summaries_status_check CHECK (
                status IN ('Generated', 'Superseded')
            ),
            CONSTRAINT chapter_summaries_revision_positive CHECK (revision >= 1),
            CONSTRAINT chapter_summaries_chapter_revision_unique UNIQUE (
                project_id, chapter_id, revision
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX summary_jobs_project_scene_idx
            ON summary_jobs (project_id, kind, scene_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX summary_jobs_project_chapter_idx
            ON summary_jobs (project_id, kind, chapter_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX summary_jobs_idempotency_idx
            ON summary_jobs (project_id, kind, idempotency_key)
        """
    )
    op.execute(
        """
        CREATE INDEX scene_summaries_project_scene_idx
            ON scene_summaries (project_id, scene_id, revision DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX chapter_summaries_project_chapter_idx
            ON chapter_summaries (project_id, chapter_id, revision DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE chapter_summaries")
    op.execute("DROP TABLE scene_summaries")
    op.execute("DROP TABLE summary_jobs")
