"""Create review queue tables (node 7.3).

Revision ID: 017_review_queue
Revises: 016_style_validation
Create Date: 2026-08-18

Tables:
- review_queue_items — one queue row per enqueued subject
  (Scene Plan / Scene Draft / Candidate Change / Validation Report /
  Repair Task / Style Report).
- review_decisions — append-only human decisions with required
  reason_code.

Does not recreate audit_events, Story Project / Spec, Canon, Scene
Card, Scene Plan, Scene Draft, extract, summary, Validation Run,
Repair Task, Context Pack, Outline, Style Guide / Sample, or Style
Validation tables. Does not add 8.x worker / agent registry tables,
chapter-level generate, or real-vendor tables. Review-queue approve
does not write Canon. Style-report approve is not Canon approval.
Does not change 5.x Validation Run semantics or 3.4 Scene Draft
generate-job columns. No production seed-status route.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "017_review_queue"
down_revision: str | None = "016_style_validation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE review_queue_items (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            status TEXT NOT NULL,
            is_blocker BOOLEAN NOT NULL DEFAULT FALSE,
            chapter_id UUID,
            scene_id UUID,
            context_pack_id TEXT,
            input_versions JSONB NOT NULL,
            evidence_refs JSONB NOT NULL,
            diff_json JSONB NOT NULL,
            decision_ids JSONB NOT NULL,
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT review_queue_items_subject_type_check CHECK (
                subject_type IN (
                    'scene_plan',
                    'scene_draft',
                    'candidate_change',
                    'validation_report',
                    'repair_task',
                    'style_report'
                )
            ),
            CONSTRAINT review_queue_items_status_check CHECK (
                status IN (
                    'Opened',
                    'Escalated',
                    'Approved',
                    'Rejected',
                    'RevisionRequested',
                    'Failed',
                    'Cancelled'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX review_queue_items_project_idx
            ON review_queue_items (project_id, status, is_blocker, chapter_id)
        """
    )
    op.execute(
        """
        CREATE TABLE review_decisions (
            id UUID PRIMARY KEY,
            item_id UUID NOT NULL REFERENCES review_queue_items (id),
            project_id UUID NOT NULL REFERENCES story_projects (id),
            action TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            comment TEXT,
            actor_type TEXT NOT NULL,
            actor_id TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            writes_canon BOOLEAN NOT NULL DEFAULT FALSE,
            is_canon_approval BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT review_decisions_action_check CHECK (
                action IN (
                    'approve',
                    'reject',
                    'request_revision',
                    'escalate',
                    'cancel'
                )
            ),
            CONSTRAINT review_decisions_reason_required CHECK (
                char_length(reason_code) > 0
            ),
            CONSTRAINT review_decisions_no_canon_write CHECK (
                writes_canon = FALSE AND is_canon_approval = FALSE
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX review_decisions_item_idx
            ON review_decisions (item_id, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE review_decisions")
    op.execute("DROP TABLE review_queue_items")
