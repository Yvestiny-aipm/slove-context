"""Create single-scene DAG tables (node 8.3).

Revision ID: 020_scene_dags
Revises: 019_agents
Create Date: 2026-08-18

Tables:
- scene_dags — one-scene orchestrator runs
- dag_nodes — fixed workflow nodes (status, duration_ms, outputs)

Does not recreate prior tables. Does not add batch scheduling (8.4),
Agent auto-approve, chapter-level generate, or real-vendor tables.
canon_commit is not a new Canon write path. No production seed-status.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "020_scene_dags"
down_revision: str | None = "019_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE scene_dags (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            status TEXT NOT NULL,
            rebuild_context_pack BOOLEAN NOT NULL DEFAULT FALSE,
            start_from TEXT,
            blocked BOOLEAN NOT NULL DEFAULT FALSE,
            blocker_node_id TEXT,
            blocker_reason TEXT,
            human_decision TEXT,
            human_reason_code TEXT,
            human_actor_type TEXT,
            human_actor_id TEXT,
            frozen_outputs JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            CONSTRAINT scene_dags_status_check CHECK (
                status IN (
                    'created',
                    'running',
                    'waiting_human',
                    'blocked',
                    'succeeded',
                    'failed',
                    'cancelled'
                )
            ),
            CONSTRAINT scene_dags_human_decision_check CHECK (
                human_decision IS NULL
                OR human_decision IN ('approve', 'reject')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE dag_nodes (
            id UUID PRIMARY KEY,
            dag_id UUID NOT NULL REFERENCES scene_dags (id),
            node_id TEXT NOT NULL,
            status TEXT NOT NULL,
            job_id TEXT,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            duration_ms INTEGER,
            error_code TEXT,
            error_detail TEXT,
            outputs JSONB NOT NULL,
            reused_upstream BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT dag_nodes_node_id_check CHECK (
                node_id IN (
                    'context_pack',
                    'scene_plan',
                    'plan_validation',
                    'scene_draft',
                    'candidate_extraction',
                    'draft_validation',
                    'human_review',
                    'canon_commit',
                    'summary',
                    'downstream_unblock'
                )
            ),
            CONSTRAINT dag_nodes_status_check CHECK (
                status IN (
                    'pending',
                    'ready',
                    'running',
                    'succeeded',
                    'failed',
                    'blocked',
                    'waiting_human',
                    'skipped',
                    'cancelled'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX dag_nodes_dag_node_idx
            ON dag_nodes (dag_id, node_id)
        """
    )
    op.execute(
        """
        CREATE INDEX scene_dags_project_scene_idx
            ON scene_dags (project_id, scene_id, status)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE dag_nodes")
    op.execute("DROP TABLE scene_dags")
