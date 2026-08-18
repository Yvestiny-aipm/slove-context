"""Create Scene Card / outline structure tables (node 3.1).

Revision ID: 005_scene_tables
Revises: 004_canon_snapshot
Create Date: 2026-08-18

Tables:
- arcs — 卷或弧; structure container only (not a generation unit)
- chapters — 章; structure container only (not a generation unit)
- scenes — 场景; the only generation unit. Holds Scene Card + order
- scene_dependencies — directed edges; cycles are rejected in the API

Does not recreate audit_events, Story Project / Spec, or Canon tables.
Does not add Scene Plan / Scene Draft / Context Pack / model-gateway tables.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "005_scene_tables"
down_revision: str | None = "004_canon_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE arcs (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            title TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chapters (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            arc_id UUID NOT NULL REFERENCES arcs (id),
            title TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE scenes (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            chapter_id UUID NOT NULL REFERENCES chapters (id),
            scene_card_id UUID NOT NULL,
            story_order INTEGER NOT NULL,
            status TEXT NOT NULL,
            scene_status TEXT NOT NULL,
            pov TEXT NOT NULL,
            story_time TEXT NOT NULL,
            location TEXT NOT NULL,
            present_entities JSONB NOT NULL,
            starting_state TEXT NOT NULL,
            goal TEXT NOT NULL,
            conflict TEXT NOT NULL,
            expected_end_state TEXT NOT NULL,
            forbidden JSONB NOT NULL,
            knowledge_boundaries JSONB NOT NULL,
            generation_boundary TEXT NOT NULL,
            scene_card_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT scenes_status_check CHECK (
                status IN ('draft', 'approved', 'published')
            ),
            CONSTRAINT scenes_scene_status_check CHECK (
                scene_status IN ('Specified', 'CardReady')
            ),
            CONSTRAINT scenes_story_order_positive CHECK (story_order >= 1),
            CONSTRAINT scenes_story_order_unique
                UNIQUE (project_id, story_order)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE scene_dependencies (
            scene_id UUID NOT NULL REFERENCES scenes (id),
            depends_on_scene_id UUID NOT NULL REFERENCES scenes (id),
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (scene_id, depends_on_scene_id),
            CONSTRAINT scene_dependencies_no_self
                CHECK (scene_id <> depends_on_scene_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX scenes_project_order_idx
            ON scenes (project_id, story_order)
        """
    )
    op.execute(
        """
        CREATE INDEX scene_dependencies_dep_idx
            ON scene_dependencies (depends_on_scene_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE scene_dependencies")
    op.execute("DROP TABLE scenes")
    op.execute("DROP TABLE chapters")
    op.execute("DROP TABLE arcs")
