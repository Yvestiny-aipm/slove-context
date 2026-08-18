"""Create audit_events (node 1.3).

Revision ID: 001_audit_events
Revises:
Create Date: 2026-08-18

This is the only table added in this node. It is not a Canon table and
does not create Story Project / Story Spec / scene tables.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "001_audit_events"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit_events (
            id UUID PRIMARY KEY,
            occurred_at TIMESTAMPTZ NOT NULL,
            actor_type TEXT NOT NULL,
            actor_id TEXT,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            before_json JSONB,
            after_json JSONB,
            correlation_id TEXT
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE audit_events")
