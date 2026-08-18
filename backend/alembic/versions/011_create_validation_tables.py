"""Create Validation Run / Report tables (node 5.1).

Revision ID: 011_validation
Revises: 010_summaries
Create Date: 2026-08-18

Tables:
- validation_runs — one Validate execution
  (Queued / Running / Passed / RuleFailed / ExecFailed / Cancelled)
- validation_reports — schema-valid report; violations are embedded JSON

Does not recreate audit_events, Story Project / Spec, Canon, Scene Card,
Scene Plan, Scene Draft, extract, or summary tables. Does not add
Repair Task / Context Pack / model-gateway / real-vendor tables.
Validate is not Approval and does not write Canon.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "011_validation"
down_revision: str | None = "010_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE validation_runs (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id UUID NOT NULL REFERENCES scenes (id),
            snapshot_id UUID REFERENCES canon_snapshots (id),
            spec_id UUID REFERENCES story_specs (id),
            candidate_ids JSONB NOT NULL,
            state TEXT NOT NULL,
            outcome TEXT,
            report_id UUID,
            transitions JSONB NOT NULL,
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT validation_runs_state_check CHECK (
                state IN (
                    'Queued', 'Running', 'Passed', 'RuleFailed',
                    'ExecFailed', 'Cancelled'
                )
            ),
            CONSTRAINT validation_runs_outcome_check CHECK (
                outcome IS NULL OR outcome IN (
                    'Passed', 'RuleFailed', 'ExecFailed'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE validation_reports (
            id UUID PRIMARY KEY,
            run_id UUID NOT NULL REFERENCES validation_runs (id),
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id UUID NOT NULL REFERENCES scenes (id),
            outcome TEXT NOT NULL,
            payload_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT validation_reports_outcome_check CHECK (
                outcome IN ('Passed', 'RuleFailed', 'ExecFailed')
            )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE validation_runs
            ADD CONSTRAINT validation_runs_report_fk
            FOREIGN KEY (report_id) REFERENCES validation_reports (id)
        """
    )
    op.execute(
        """
        CREATE INDEX validation_runs_project_scene_idx
            ON validation_runs (project_id, scene_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX validation_reports_run_idx
            ON validation_reports (run_id)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE validation_runs DROP CONSTRAINT validation_runs_report_fk")
    op.execute("DROP TABLE validation_reports")
    op.execute("DROP TABLE validation_runs")
