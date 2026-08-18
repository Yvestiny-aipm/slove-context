"""Add Candidate Change approval / submit columns (node 4.2).

Revision ID: 009_candidate_approval
Revises: 008_extract
Create Date: 2026-08-18

Incremental columns on candidate_changes:
- approval_decision_json — last human Approval Decision (not Canon)
- submitted_canon_fact_id — Canon Fact created or superseding on submit
- superseded_canon_fact_id — previous Active fact if submit superseded

Does not recreate audit_events, Story Project / Spec, Canon, Scene Card,
Scene Plan, Scene Draft, or extract tables. Does not add Validation Run
/ Context Pack / model-gateway / real-vendor / summary tables.
Approve itself does not write Canon; only submit fills the fact ids.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "009_candidate_approval"
down_revision: str | None = "008_extract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE candidate_changes
            ADD COLUMN approval_decision_json JSONB,
            ADD COLUMN submitted_canon_fact_id UUID REFERENCES canon_facts (id),
            ADD COLUMN superseded_canon_fact_id UUID REFERENCES canon_facts (id)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE candidate_changes
            DROP COLUMN IF EXISTS superseded_canon_fact_id,
            DROP COLUMN IF EXISTS submitted_canon_fact_id,
            DROP COLUMN IF EXISTS approval_decision_json
        """
    )
