"""Create Agent Registry tables (node 8.2).

Revision ID: 019_agents
Revises: 018_jobs
Create Date: 2026-08-18

Tables:
- agents — registered Agent records (id, input/output schema,
  allowed tools, forbidden operations, model config, prompt
  version, timeout, cost cap)
- agent_runs — replayable runs (input_ref, output_ref, tool_calls,
  cost, duration_ms, error)

Seeds the seven built-in agents. Does not recreate prior tables.
Does not add DAG (8.3), batch (8.4), chapter-level generate, or
real-vendor tables. No production seed-status route. Agents do
not write Canon.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "019_agents"
down_revision: str | None = "018_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            input_schema JSONB NOT NULL,
            output_schema JSONB NOT NULL,
            allowed_tools JSONB NOT NULL,
            forbidden_operations JSONB NOT NULL,
            model_config JSONB NOT NULL,
            prompt_version TEXT,
            timeout_s DOUBLE PRECISION NOT NULL,
            cost_cap JSONB NOT NULL,
            allowed_output_types JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT agents_id_check CHECK (
                id IN (
                    'outline_agent',
                    'draft_agent',
                    'extractor_agent',
                    'consistency_agent',
                    'style_agent',
                    'repair_agent',
                    'human_approver'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE agent_runs (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES story_projects (id),
            agent_id TEXT NOT NULL REFERENCES agents (id),
            input_ref TEXT NOT NULL,
            output_ref TEXT,
            output_type TEXT,
            tool TEXT,
            tool_calls JSONB NOT NULL,
            cost JSONB NOT NULL,
            duration_ms INTEGER,
            error JSONB,
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ,
            created_by TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            CONSTRAINT agent_runs_status_check CHECK (
                status IN (
                    'queued',
                    'running',
                    'succeeded',
                    'failed',
                    'cancelled'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX agent_runs_project_idx
            ON agent_runs (project_id, agent_id, status)
        """
    )
    op.execute(
        """
        INSERT INTO agents (
            id, name, input_schema, output_schema, allowed_tools,
            forbidden_operations, model_config, prompt_version,
            timeout_s, cost_cap, allowed_output_types, created_at
        ) VALUES
        (
            'outline_agent',
            'Outline Agent',
            '{"title":"OutlineAgentInput"}'::jsonb,
            '{"title":"OutlineAgentOutput"}'::jsonb,
            '["propose_outline","propose_scene_plan"]'::jsonb,
            '["write_canon","submit_canon","approve","approve_canon","write_draft","generate_draft"]'::jsonb,
            '{"provider":"fake","model":"fake-outline-v1","real_http":false}'::jsonb,
            'scene_plan.v1',
            30,
            '{"max_tokens":4096,"max_cost_usd":0.5}'::jsonb,
            '["outline","scene_plan"]'::jsonb,
            TIMESTAMPTZ '2026-08-18 00:00:00+00'
        ),
        (
            'draft_agent',
            'Draft Agent',
            '{"title":"DraftAgentInput"}'::jsonb,
            '{"title":"DraftAgentOutput"}'::jsonb,
            '["generate_draft"]'::jsonb,
            '["write_canon","submit_canon","approve","approve_canon"]'::jsonb,
            '{"provider":"fake","model":"fake-draft-v1","real_http":false}'::jsonb,
            'scene_draft.v1',
            30,
            '{"max_tokens":4096,"max_cost_usd":0.5}'::jsonb,
            '["scene_draft"]'::jsonb,
            TIMESTAMPTZ '2026-08-18 00:00:00+00'
        ),
        (
            'extractor_agent',
            'Extractor Agent',
            '{"title":"ExtractorAgentInput"}'::jsonb,
            '{"title":"ExtractorAgentOutput"}'::jsonb,
            '["propose_candidate_change"]'::jsonb,
            '["write_canon","submit_canon","approve","approve_canon"]'::jsonb,
            '{"provider":"fake","model":"fake-extract-v1","real_http":false}'::jsonb,
            'extract_candidates.v1',
            30,
            '{"max_tokens":4096,"max_cost_usd":0.5}'::jsonb,
            '["candidate_change"]'::jsonb,
            TIMESTAMPTZ '2026-08-18 00:00:00+00'
        ),
        (
            'consistency_agent',
            'Consistency Agent',
            '{"title":"ConsistencyAgentInput"}'::jsonb,
            '{"title":"ConsistencyAgentOutput"}'::jsonb,
            '["produce_validation_report"]'::jsonb,
            '["write_canon","submit_canon","approve","approve_canon"]'::jsonb,
            '{"provider":"fake","model":"fake-validate-v1","real_http":false}'::jsonb,
            NULL,
            15,
            '{"max_tokens":0,"max_cost_usd":0}'::jsonb,
            '["validation_report"]'::jsonb,
            TIMESTAMPTZ '2026-08-18 00:00:00+00'
        ),
        (
            'style_agent',
            'Style Agent',
            '{"title":"StyleAgentInput"}'::jsonb,
            '{"title":"StyleAgentOutput"}'::jsonb,
            '["produce_style_report"]'::jsonb,
            '["write_canon","submit_canon","approve","approve_canon"]'::jsonb,
            '{"provider":"fake","model":"fake-style-v1","real_http":false}'::jsonb,
            'style_validation.v1',
            20,
            '{"max_tokens":4096,"max_cost_usd":0.5}'::jsonb,
            '["style_report"]'::jsonb,
            TIMESTAMPTZ '2026-08-18 00:00:00+00'
        ),
        (
            'repair_agent',
            'Repair Agent',
            '{"title":"RepairAgentInput"}'::jsonb,
            '{"title":"RepairAgentOutput"}'::jsonb,
            '["produce_draft_revision"]'::jsonb,
            '["write_canon","submit_canon","approve","approve_canon"]'::jsonb,
            '{"provider":"fake","model":"fake-repair-v1","real_http":false}'::jsonb,
            'scene_draft.v1',
            30,
            '{"max_tokens":4096,"max_cost_usd":0.5}'::jsonb,
            '["scene_draft_revision"]'::jsonb,
            TIMESTAMPTZ '2026-08-18 00:00:00+00'
        ),
        (
            'human_approver',
            'Human Approver',
            '{"title":"HumanApproverInput"}'::jsonb,
            '{"title":"HumanApproverOutput"}'::jsonb,
            '["approve_canon","approve","reject","request_revision","escalate"]'::jsonb,
            '["write_canon","submit_canon","bypass_approval","generate_draft"]'::jsonb,
            '{"provider":null,"model":null,"note":"human_only_no_model","real_http":false}'::jsonb,
            NULL,
            0,
            '{"max_tokens":0,"max_cost_usd":0}'::jsonb,
            '["approval_decision"]'::jsonb,
            TIMESTAMPTZ '2026-08-18 00:00:00+00'
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE agent_runs")
    op.execute("DROP TABLE agents")
