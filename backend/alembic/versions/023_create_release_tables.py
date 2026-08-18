"""Create release-gate tables (node 9.3).

Revision ID: 023_release
Revises: 022_experiments
Create Date: 2026-08-18

Tables:
- release_checks — eight-gate run + machine-readable failures
- release_manifests — immutable passed-check manifests
- release_exports — formal markdown / json / review-pack copies
- release_due_items — minimal foreshadowing due items
- release_waivers — human waivers for due items / safety
- release_safety_checks — deterministic safety placeholder

Does not recreate prior tables. Does not add 10.x / real-vendor
clients / Agent auto-approve. Release does not write Canon.
Failed checks are kept and are not formal releases.
No production seed-status.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "023_release"
down_revision: str | None = "022_experiments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE release_checks (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL,
            snapshot_id TEXT NOT NULL,
            status TEXT NOT NULL,
            scene_ids JSONB NOT NULL,
            chapter_ids JSONB NOT NULL,
            draft_ids JSONB NOT NULL,
            gate_results JSONB NOT NULL,
            failures JSONB NOT NULL,
            manifest_id UUID,
            export_ids JSONB NOT NULL,
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT release_checks_status_check CHECK (
                status IN (
                    'queued',
                    'running',
                    'passed',
                    'failed',
                    'cancelled'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE release_manifests (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL,
            check_id UUID NOT NULL REFERENCES release_checks (id),
            schema_version TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE release_exports (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL,
            check_id UUID NOT NULL REFERENCES release_checks (id),
            manifest_id UUID NOT NULL REFERENCES release_manifests (id),
            format TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT release_exports_format_check CHECK (
                format IN ('markdown', 'json', 'review_pack')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE release_due_items (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            scene_id TEXT,
            chapter_id TEXT,
            note TEXT,
            waiver_id UUID,
            handled_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT release_due_items_status_check CHECK (
                status IN ('due', 'handled', 'waived')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE release_waivers (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL,
            kind TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            comment TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT release_waivers_kind_check CHECK (
                kind IN ('due_item', 'safety')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE release_safety_checks (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL,
            status TEXT NOT NULL,
            result TEXT NOT NULL,
            vendor TEXT NOT NULL,
            scene_ids JSONB NOT NULL,
            waiver_id UUID,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            CONSTRAINT release_safety_checks_status_check CHECK (
                status IN ('recorded', 'waived')
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX release_checks_project_idx
            ON release_checks (project_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX release_due_items_project_idx
            ON release_due_items (project_id, status)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE release_exports")
    op.execute("DROP TABLE release_manifests")
    op.execute("DROP TABLE release_safety_checks")
    op.execute("DROP TABLE release_waivers")
    op.execute("DROP TABLE release_due_items")
    op.execute("DROP TABLE release_checks")
