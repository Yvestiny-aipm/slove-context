"""Create experiment run tables (node 9.2).

Revision ID: 022_experiments
Revises: 021_schedule
Create Date: 2026-08-18

Tables:
- experiments — pinned 9.1 case set + default knobs
- experiment_runs — immutable run history (config / refs / metrics)
- experiment_comparisons — baseline vs candidate metric diffs

Does not recreate prior tables. Does not add 9.3 release-gate tables,
real-vendor clients, or Agent auto-approve. Experiments do not write
Canon. No production seed-status.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "022_experiments"
down_revision: str | None = "021_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE experiments (
            id UUID PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            case_set_version TEXT NOT NULL,
            case_ids JSONB NOT NULL,
            fixture_hashes JSONB NOT NULL,
            expected_hashes JSONB NOT NULL,
            snapshot_ids JSONB NOT NULL,
            default_model TEXT NOT NULL,
            default_prompt_version TEXT NOT NULL,
            default_retrieval_strategy TEXT NOT NULL,
            default_temperature DOUBLE PRECISION NOT NULL,
            default_max_tokens INTEGER NOT NULL,
            random_seed INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            correlation_id TEXT,
            CONSTRAINT experiments_status_check CHECK (
                status IN ('created', 'cancelled')
            ),
            CONSTRAINT experiments_max_tokens_check
                CHECK (default_max_tokens >= 1),
            CONSTRAINT experiments_temperature_check
                CHECK (default_temperature >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE experiment_runs (
            id UUID PRIMARY KEY,
            experiment_id UUID NOT NULL REFERENCES experiments (id),
            status TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            retrieval_strategy TEXT NOT NULL,
            temperature DOUBLE PRECISION NOT NULL,
            max_tokens INTEGER NOT NULL,
            case_set_version TEXT NOT NULL,
            case_ids JSONB NOT NULL,
            input_versions JSONB NOT NULL,
            output_refs JSONB NOT NULL,
            metrics JSONB NOT NULL,
            cost JSONB NOT NULL,
            latency_ms DOUBLE PRECISION NOT NULL,
            duration_ms DOUBLE PRECISION NOT NULL,
            random_seed INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            correlation_id TEXT,
            error_code TEXT,
            CONSTRAINT experiment_runs_status_check CHECK (
                status IN (
                    'queued',
                    'running',
                    'succeeded',
                    'failed',
                    'cancelled'
                )
            ),
            CONSTRAINT experiment_runs_max_tokens_check
                CHECK (max_tokens >= 1),
            CONSTRAINT experiment_runs_temperature_check
                CHECK (temperature >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE experiment_comparisons (
            id UUID PRIMARY KEY,
            experiment_id UUID NOT NULL REFERENCES experiments (id),
            baseline_run_id UUID NOT NULL REFERENCES experiment_runs (id),
            candidate_run_id UUID NOT NULL REFERENCES experiment_runs (id),
            metrics JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT experiment_comparisons_distinct CHECK (
                baseline_run_id <> candidate_run_id
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX experiment_runs_experiment_idx
            ON experiment_runs (experiment_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX experiment_comparisons_experiment_idx
            ON experiment_comparisons (experiment_id, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE experiment_comparisons")
    op.execute("DROP TABLE experiment_runs")
    op.execute("DROP TABLE experiments")
