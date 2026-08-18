"""Create batch schedule tables (node 8.4).

Revision ID: 021_schedule
Revises: 020_scene_dags
Create Date: 2026-08-18

Tables:
- project_schedule_configs — per-project concurrency / budget / caps
- schedule_runs — start / pause / resume / dry-run records
- schedule_decisions — why a scene was or was not enqueued
- schedule_alerts — human alerts (budget / consecutive failures)
- schedule_budget_counters — daily token / cost counters

Does not recreate prior tables. Does not add 9.x eval, Agent
auto-approve, chapter-level generate, or real-vendor tables.
Scheduler does not write Canon. No production seed-status.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "021_schedule"
down_revision: str | None = "020_scene_dags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE project_schedule_configs (
            project_id UUID PRIMARY KEY REFERENCES story_projects (id),
            concurrency INTEGER NOT NULL,
            daily_token_budget INTEGER NOT NULL,
            per_scene_cost_cap DOUBLE PRECISION NOT NULL,
            failure_threshold INTEGER NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            updated_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT project_schedule_configs_concurrency_check
                CHECK (concurrency >= 1),
            CONSTRAINT project_schedule_configs_budget_check
                CHECK (daily_token_budget >= 0),
            CONSTRAINT project_schedule_configs_cost_check
                CHECK (per_scene_cost_cap >= 0),
            CONSTRAINT project_schedule_configs_failure_check
                CHECK (failure_threshold >= 1)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE schedule_runs (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            chapter_id TEXT,
            snapshot_id TEXT NOT NULL,
            status TEXT NOT NULL,
            dry_run BOOLEAN NOT NULL DEFAULT FALSE,
            estimated_task_count INTEGER NOT NULL DEFAULT 0,
            estimated_dag_count INTEGER NOT NULL DEFAULT 0,
            enqueued_count INTEGER NOT NULL DEFAULT 0,
            held_count INTEGER NOT NULL DEFAULT 0,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            cost_used DOUBLE PRECISION NOT NULL DEFAULT 0,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            paused_reason TEXT,
            dag_ids JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            correlation_id TEXT,
            CONSTRAINT schedule_runs_status_check CHECK (
                status IN (
                    'planned',
                    'running',
                    'paused',
                    'succeeded',
                    'failed',
                    'cancelled'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE schedule_decisions (
            id UUID PRIMARY KEY,
            run_id UUID NOT NULL REFERENCES schedule_runs (id),
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            task_kind TEXT NOT NULL,
            snapshot_id TEXT,
            dag_id TEXT,
            message TEXT NOT NULL,
            parallel_with JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT schedule_decisions_action_check CHECK (
                action IN ('enqueued', 'held', 'rejected', 'skipped')
            ),
            CONSTRAINT schedule_decisions_kind_check CHECK (
                task_kind IN (
                    'planning',
                    'read_check',
                    'prose_write',
                    'canon_write'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE schedule_alerts (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            run_id UUID REFERENCES schedule_runs (id),
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT NOT NULL,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT schedule_alerts_kind_check CHECK (
                kind IN ('budget_exceeded', 'consecutive_failures')
            ),
            CONSTRAINT schedule_alerts_status_check CHECK (
                status IN ('open', 'acknowledged')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE schedule_budget_counters (
            project_id UUID NOT NULL REFERENCES story_projects (id),
            day DATE NOT NULL,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            cost_used DOUBLE PRECISION NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (project_id, day)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX schedule_runs_project_status_idx
            ON schedule_runs (project_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX schedule_decisions_run_idx
            ON schedule_decisions (run_id, scene_id)
        """
    )
    op.execute(
        """
        CREATE INDEX schedule_alerts_project_idx
            ON schedule_alerts (project_id, status)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE schedule_budget_counters")
    op.execute("DROP TABLE schedule_alerts")
    op.execute("DROP TABLE schedule_decisions")
    op.execute("DROP TABLE schedule_runs")
    op.execute("DROP TABLE project_schedule_configs")
