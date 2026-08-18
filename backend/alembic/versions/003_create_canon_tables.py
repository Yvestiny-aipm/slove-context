"""Create Canon tables (node 2.2).

Revision ID: 003_canon_tables
Revises: 002_story_project_spec
Create Date: 2026-08-18

Tables:
- entities — generic entities (角色 / 地点 / 物品 / 组织 / 规则)
- evidence_records — prose or editor evidence; evidence is not Canon
- canon_facts — structured facts (append-only; supersede only)
- canon_fact_versions — immutable fact versions
- canon_snapshots — table only; no freeze job or replay API (node 2.3)

This node does not create vector / embedding columns, graph tables,
character-as-product tables, or snapshot replay machinery.
audit_events and Story Project / Spec tables are unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "003_canon_tables"
down_revision: str | None = "002_story_project_spec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entities (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            entity_type TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT entities_type_check CHECK (
                entity_type IN (
                    'character',
                    'location',
                    'item',
                    'organization',
                    'world_rule'
                )
            ),
            CONSTRAINT entities_type_name_unique
                UNIQUE (project_id, entity_type, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE evidence_records (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            source_type TEXT NOT NULL,
            quote TEXT NOT NULL,
            scene_id UUID,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT evidence_source_type_check CHECK (
                source_type IN ('prose', 'editor')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE canon_facts (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            entity_id UUID NOT NULL REFERENCES entities (id),
            predicate TEXT NOT NULL,
            value_json JSONB NOT NULL,
            effective_story_time TEXT NOT NULL,
            valid_from_scene_id UUID NOT NULL,
            status TEXT NOT NULL,
            source_type TEXT NOT NULL,
            evidence_id UUID NOT NULL REFERENCES evidence_records (id),
            current_version_id UUID,
            supersedes_fact_id UUID REFERENCES canon_facts (id),
            superseded_by_fact_id UUID REFERENCES canon_facts (id),
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT canon_facts_status_check CHECK (
                status IN (
                    'NotInCanon',
                    'Active',
                    'Superseded',
                    'Failed',
                    'Abandoned',
                    'Rework'
                )
            ),
            CONSTRAINT canon_facts_source_type_check CHECK (
                source_type IN ('prose', 'editor')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE canon_fact_versions (
            id UUID PRIMARY KEY,
            fact_id UUID NOT NULL REFERENCES canon_facts (id),
            revision_number INTEGER NOT NULL,
            entity_id UUID NOT NULL REFERENCES entities (id),
            predicate TEXT NOT NULL,
            value_json JSONB NOT NULL,
            effective_story_time TEXT NOT NULL,
            valid_from_scene_id UUID NOT NULL,
            source_type TEXT NOT NULL,
            evidence_id UUID NOT NULL REFERENCES evidence_records (id),
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            CONSTRAINT canon_fact_versions_revision_unique
                UNIQUE (fact_id, revision_number),
            CONSTRAINT canon_fact_versions_source_type_check CHECK (
                source_type IN ('prose', 'editor')
            )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE canon_facts
            ADD CONSTRAINT canon_facts_current_version_fk
            FOREIGN KEY (current_version_id)
            REFERENCES canon_fact_versions (id)
        """
    )
    op.execute(
        """
        CREATE INDEX canon_facts_project_status_idx
            ON canon_facts (project_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX canon_facts_in_effect_idx
            ON canon_facts (project_id, entity_id, predicate, effective_story_time)
        """
    )
    op.execute(
        """
        CREATE TABLE canon_snapshots (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            approved_fact_ids JSONB NOT NULL,
            note TEXT
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE canon_snapshots")
    op.execute("ALTER TABLE canon_facts DROP CONSTRAINT canon_facts_current_version_fk")
    op.execute("DROP TABLE canon_fact_versions")
    op.execute("DROP TABLE canon_facts")
    op.execute("DROP TABLE evidence_records")
    op.execute("DROP TABLE entities")
