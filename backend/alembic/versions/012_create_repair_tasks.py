"""Create Repair Task table (node 5.2).

Revision ID: 012_repair_tasks
Revises: 011_validation
Create Date: 2026-08-18

Tables:
- repair_tasks — one repair opened from a RuleFailed Violation
  (Opened / InProgress / Completed / Rechecking / RecheckPassed /
  Failed / Cancelled / Rework)

Does not recreate audit_events, Story Project / Spec, Canon, Scene Card,
Scene Plan, Scene Draft, extract, summary, or Validation Run tables.
Does not add Context Pack assembler / model-gateway / real-vendor tables.
Repair complete is not Approval and does not write Canon.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "012_repair_tasks"
down_revision: str | None = "011_validation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE repair_tasks (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id UUID NOT NULL REFERENCES scenes (id),
            validation_run_id UUID NOT NULL REFERENCES validation_runs (id),
            report_id UUID REFERENCES validation_reports (id),
            violation_id TEXT,
            violation_index INTEGER,
            action TEXT NOT NULL,
            recommended_action TEXT,
            state TEXT NOT NULL,
            candidate_ids JSONB NOT NULL,
            invoked_jobs JSONB NOT NULL,
            produced_candidate_ids JSONB NOT NULL,
            rejected_candidate_ids JSONB NOT NULL,
            recheck_run_id UUID REFERENCES validation_runs (id),
            recheck_status TEXT,
            recheck_skipped_reason TEXT,
            transitions JSONB NOT NULL,
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT repair_tasks_state_check CHECK (
                state IN (
                    'Opened', 'InProgress', 'Completed', 'Rechecking',
                    'RecheckPassed', 'Failed', 'Cancelled', 'Rework'
                )
            ),
            CONSTRAINT repair_tasks_action_check CHECK (
                action IN (
                    'ReviseScenePlan', 'Regenerate', 'Reextract', 'HumanReject'
                )
            ),
            CONSTRAINT repair_tasks_recommended_action_check CHECK (
                recommended_action IS NULL OR recommended_action IN (
                    'ReviseScenePlan', 'Regenerate', 'Reextract', 'HumanReject'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX repair_tasks_project_run_idx
            ON repair_tasks (project_id, validation_run_id, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE repair_tasks")
