"""Create Style Validation table (node 7.2).

Revision ID: 016_style_validation
Revises: 015_style
Create Date: 2026-08-18

Tables:
- style_validations — one Style Validation execution with embedded
  report JSON (findings, rule_version, llm_score_version).

Does not recreate audit_events, Story Project / Spec, Canon, Scene
Card, Scene Plan, Scene Draft, extract, summary, Validation Run,
Repair Task, Context Pack, Outline, or Style Guide / Sample tables.
Does not add review queue (7.3), chapter-level generate, or
real-vendor tables. Style findings do not block Canon submit and
do not write Canon. Does not change 5.x Validation Run semantics
or 3.4 Scene Draft generate-job columns.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "016_style_validation"
down_revision: str | None = "015_style"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE style_validations (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            scene_id UUID NOT NULL REFERENCES scenes (id),
            draft_revision_id UUID NOT NULL REFERENCES scene_drafts (id),
            style_guide_revision_id UUID REFERENCES style_guides (id),
            style_sample_ids JSONB NOT NULL,
            status TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            llm_score_version TEXT,
            llm_status TEXT NOT NULL,
            include_llm BOOLEAN NOT NULL,
            thresholds_json JSONB NOT NULL,
            findings_json JSONB NOT NULL,
            report_json JSONB NOT NULL,
            blocks_canon_submit BOOLEAN NOT NULL DEFAULT FALSE,
            request_refs JSONB NOT NULL,
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT style_validations_status_check CHECK (
                status IN (
                    'Queued',
                    'Running',
                    'Succeeded',
                    'Failed',
                    'Cancelled'
                )
            ),
            CONSTRAINT style_validations_blocks_default CHECK (
                blocks_canon_submit = FALSE
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX style_validations_draft_idx
            ON style_validations (project_id, scene_id, draft_revision_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE style_validations")
