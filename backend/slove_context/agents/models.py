"""Registered Agent records and Agent Run archival (node 8.2).

Each Agent has input / output schema, allowed tools, forbidden
operations, model config, prompt version, timeout, and cost cap.
Runs store input_ref, output_ref, tool_calls, cost, duration, and
error so they can be replayed from those refs. Failure and cancel
keep the row. Runs never write Canon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AGENT_OUTLINE = "outline_agent"
AGENT_DRAFT = "draft_agent"
AGENT_EXTRACTOR = "extractor_agent"
AGENT_CONSISTENCY = "consistency_agent"
AGENT_STYLE = "style_agent"
AGENT_REPAIR = "repair_agent"
AGENT_HUMAN_APPROVER = "human_approver"

AGENT_IDS = frozenset(
    {
        AGENT_OUTLINE,
        AGENT_DRAFT,
        AGENT_EXTRACTOR,
        AGENT_CONSISTENCY,
        AGENT_STYLE,
        AGENT_REPAIR,
        AGENT_HUMAN_APPROVER,
    }
)

OUTPUT_OUTLINE = "outline"
OUTPUT_SCENE_PLAN = "scene_plan"
OUTPUT_SCENE_DRAFT = "scene_draft"
OUTPUT_CANDIDATE_CHANGE = "candidate_change"
OUTPUT_VALIDATION_REPORT = "validation_report"
OUTPUT_STYLE_REPORT = "style_report"
OUTPUT_DRAFT_REVISION = "scene_draft_revision"
OUTPUT_APPROVAL_DECISION = "approval_decision"

ACTION_PROPOSE_OUTLINE = "propose_outline"
ACTION_PROPOSE_SCENE_PLAN = "propose_scene_plan"
ACTION_GENERATE_DRAFT = "generate_draft"
ACTION_WRITE_DRAFT = "write_draft"
ACTION_PROPOSE_CANDIDATE_CHANGE = "propose_candidate_change"
ACTION_PRODUCE_VALIDATION_REPORT = "produce_validation_report"
ACTION_PRODUCE_STYLE_REPORT = "produce_style_report"
ACTION_PRODUCE_DRAFT_REVISION = "produce_draft_revision"
ACTION_APPROVE_CANON = "approve_canon"
ACTION_APPROVE = "approve"
ACTION_REJECT = "reject"
ACTION_REQUEST_REVISION = "request_revision"
ACTION_ESCALATE = "escalate"
ACTION_WRITE_CANON = "write_canon"
ACTION_SUBMIT_CANON = "submit_canon"
ACTION_BYPASS_APPROVAL = "bypass_approval"
ACTION_CREATE_CANON_FACT = "create_canon_fact"

# Canon write / submit is never an Agent tool. 4.2 human submit only.
CANON_WRITE_ACTIONS = frozenset(
    {
        ACTION_WRITE_CANON,
        ACTION_SUBMIT_CANON,
        ACTION_BYPASS_APPROVAL,
        ACTION_CREATE_CANON_FACT,
    }
)

APPROVE_ACTIONS = frozenset({ACTION_APPROVE_CANON, ACTION_APPROVE})

_ACTION_ALIASES = {
    ACTION_PROPOSE_OUTLINE: ACTION_PROPOSE_OUTLINE,
    "propose-outline": ACTION_PROPOSE_OUTLINE,
    "outline": ACTION_PROPOSE_OUTLINE,
    ACTION_PROPOSE_SCENE_PLAN: ACTION_PROPOSE_SCENE_PLAN,
    "propose-scene-plan": ACTION_PROPOSE_SCENE_PLAN,
    "scene_plan": ACTION_PROPOSE_SCENE_PLAN,
    "plan": ACTION_PROPOSE_SCENE_PLAN,
    ACTION_GENERATE_DRAFT: ACTION_GENERATE_DRAFT,
    ACTION_WRITE_DRAFT: ACTION_WRITE_DRAFT,
    "generate-draft": ACTION_GENERATE_DRAFT,
    "draft": ACTION_GENERATE_DRAFT,
    ACTION_PROPOSE_CANDIDATE_CHANGE: ACTION_PROPOSE_CANDIDATE_CHANGE,
    "propose-candidate-change": ACTION_PROPOSE_CANDIDATE_CHANGE,
    "extract": ACTION_PROPOSE_CANDIDATE_CHANGE,
    ACTION_PRODUCE_VALIDATION_REPORT: ACTION_PRODUCE_VALIDATION_REPORT,
    "produce-validation-report": ACTION_PRODUCE_VALIDATION_REPORT,
    "validate": ACTION_PRODUCE_VALIDATION_REPORT,
    ACTION_PRODUCE_STYLE_REPORT: ACTION_PRODUCE_STYLE_REPORT,
    "produce-style-report": ACTION_PRODUCE_STYLE_REPORT,
    "style": ACTION_PRODUCE_STYLE_REPORT,
    ACTION_PRODUCE_DRAFT_REVISION: ACTION_PRODUCE_DRAFT_REVISION,
    "produce-draft-revision": ACTION_PRODUCE_DRAFT_REVISION,
    "repair": ACTION_PRODUCE_DRAFT_REVISION,
    ACTION_APPROVE_CANON: ACTION_APPROVE_CANON,
    ACTION_APPROVE: ACTION_APPROVE,
    "approve-canon": ACTION_APPROVE_CANON,
    ACTION_REJECT: ACTION_REJECT,
    ACTION_REQUEST_REVISION: ACTION_REQUEST_REVISION,
    "request-revision": ACTION_REQUEST_REVISION,
    ACTION_ESCALATE: ACTION_ESCALATE,
    ACTION_WRITE_CANON: ACTION_WRITE_CANON,
    "write-canon": ACTION_WRITE_CANON,
    ACTION_SUBMIT_CANON: ACTION_SUBMIT_CANON,
    "submit-canon": ACTION_SUBMIT_CANON,
    "submit": ACTION_SUBMIT_CANON,
    ACTION_BYPASS_APPROVAL: ACTION_BYPASS_APPROVAL,
    "bypass-approval": ACTION_BYPASS_APPROVAL,
    ACTION_CREATE_CANON_FACT: ACTION_CREATE_CANON_FACT,
    "create-canon-fact": ACTION_CREATE_CANON_FACT,
}

_AGENT_ALIASES = {
    AGENT_OUTLINE: AGENT_OUTLINE,
    "outline": AGENT_OUTLINE,
    "outline agent": AGENT_OUTLINE,
    AGENT_DRAFT: AGENT_DRAFT,
    "draft": AGENT_DRAFT,
    "draft agent": AGENT_DRAFT,
    AGENT_EXTRACTOR: AGENT_EXTRACTOR,
    "extractor": AGENT_EXTRACTOR,
    "extractor agent": AGENT_EXTRACTOR,
    AGENT_CONSISTENCY: AGENT_CONSISTENCY,
    "consistency": AGENT_CONSISTENCY,
    "consistency agent": AGENT_CONSISTENCY,
    AGENT_STYLE: AGENT_STYLE,
    "style": AGENT_STYLE,
    "style agent": AGENT_STYLE,
    AGENT_REPAIR: AGENT_REPAIR,
    "repair": AGENT_REPAIR,
    "repair agent": AGENT_REPAIR,
    AGENT_HUMAN_APPROVER: AGENT_HUMAN_APPROVER,
    "human": AGENT_HUMAN_APPROVER,
    "human approver": AGENT_HUMAN_APPROVER,
    "human_editor": AGENT_HUMAN_APPROVER,
}

OUTPUT_TYPE_FOR_ACTION = {
    ACTION_PROPOSE_OUTLINE: OUTPUT_OUTLINE,
    ACTION_PROPOSE_SCENE_PLAN: OUTPUT_SCENE_PLAN,
    ACTION_GENERATE_DRAFT: OUTPUT_SCENE_DRAFT,
    ACTION_WRITE_DRAFT: OUTPUT_SCENE_DRAFT,
    ACTION_PROPOSE_CANDIDATE_CHANGE: OUTPUT_CANDIDATE_CHANGE,
    ACTION_PRODUCE_VALIDATION_REPORT: OUTPUT_VALIDATION_REPORT,
    ACTION_PRODUCE_STYLE_REPORT: OUTPUT_STYLE_REPORT,
    ACTION_PRODUCE_DRAFT_REVISION: OUTPUT_DRAFT_REVISION,
    ACTION_APPROVE_CANON: OUTPUT_APPROVAL_DECISION,
    ACTION_APPROVE: OUTPUT_APPROVAL_DECISION,
    ACTION_REJECT: OUTPUT_APPROVAL_DECISION,
    ACTION_REQUEST_REVISION: OUTPUT_APPROVAL_DECISION,
    ACTION_ESCALATE: OUTPUT_APPROVAL_DECISION,
}

JOB_TYPE_TO_AGENT = {
    "plan": AGENT_OUTLINE,
    "draft": AGENT_DRAFT,
    "extract": AGENT_EXTRACTOR,
    "validate": AGENT_CONSISTENCY,
    "repair": AGENT_REPAIR,
}

JOB_TYPE_TO_ACTION = {
    "plan": ACTION_PROPOSE_SCENE_PLAN,
    "draft": ACTION_GENERATE_DRAFT,
    "extract": ACTION_PROPOSE_CANDIDATE_CHANGE,
    "validate": ACTION_PRODUCE_VALIDATION_REPORT,
    "repair": ACTION_PRODUCE_DRAFT_REVISION,
}

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

RUN_STATUSES = frozenset(
    {
        STATUS_QUEUED,
        STATUS_RUNNING,
        STATUS_SUCCEEDED,
        STATUS_FAILED,
        STATUS_CANCELLED,
    }
)
ACTIVE_RUN_STATUSES = frozenset({STATUS_QUEUED, STATUS_RUNNING})
TERMINAL_KEEP_STATUSES = frozenset({STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED})


def normalize_action(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    if stripped in _ACTION_ALIASES:
        return _ACTION_ALIASES[stripped]
    lowered = stripped.lower().replace("-", "_").replace(" ", "_")
    if lowered in _ACTION_ALIASES:
        return _ACTION_ALIASES[lowered]
    spaced = " ".join(stripped.lower().replace("_", " ").replace("-", " ").split())
    return _ACTION_ALIASES.get(spaced, lowered)


def normalize_agent_id(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    if stripped in AGENT_IDS:
        return stripped
    lowered = stripped.lower().replace("-", "_")
    if lowered in _AGENT_ALIASES:
        return _AGENT_ALIASES[lowered]
    spaced = " ".join(stripped.lower().replace("_", " ").replace("-", " ").split())
    return _AGENT_ALIASES.get(spaced)


@dataclass
class Agent:
    id: str
    name: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    allowed_tools: frozenset[str]
    forbidden_operations: frozenset[str]
    model_config: dict[str, Any]
    prompt_version: str | None
    timeout_s: float
    cost_cap: dict[str, Any]
    allowed_output_types: frozenset[str]
    created_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "allowed_tools": sorted(self.allowed_tools),
            "forbidden_operations": sorted(self.forbidden_operations),
            "model_config": dict(self.model_config),
            "prompt_version": self.prompt_version,
            "timeout_s": self.timeout_s,
            "cost_cap": dict(self.cost_cap),
            "allowed_output_types": sorted(self.allowed_output_types),
            "created_at": self.created_at,
            "writes_canon": False,
            "may_approve_canon": self.id == AGENT_HUMAN_APPROVER,
            "may_submit_canon": False,
            "is_human_approver": self.id == AGENT_HUMAN_APPROVER,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "allowed_tools": sorted(self.allowed_tools),
            "forbidden_operations": sorted(self.forbidden_operations),
            "allowed_output_types": sorted(self.allowed_output_types),
            "prompt_version": self.prompt_version,
            "timeout_s": self.timeout_s,
            "cost_cap_keys": sorted(self.cost_cap.keys()),
            "model_provider": self.model_config.get("provider"),
            "writes_canon": False,
            "may_approve_canon": self.id == AGENT_HUMAN_APPROVER,
        }


@dataclass
class AgentRun:
    id: str
    project_id: str
    agent_id: str
    input_ref: str
    status: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    correlation_id: str
    tool: str | None = None
    output_ref: str | None = None
    output_type: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    cost: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None
    error: dict[str, Any] | None = None
    finished_at: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "agent_id": self.agent_id,
            "input_ref": self.input_ref,
            "output_ref": self.output_ref,
            "output_type": self.output_type,
            "tool": self.tool,
            "tool_calls": [dict(item) for item in self.tool_calls],
            "cost": dict(self.cost),
            "duration_ms": self.duration_ms,
            "error": dict(self.error) if self.error is not None else None,
            "status": self.status,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "replayable": True,
            "replay_from": {
                "input_ref": self.input_ref,
                "output_ref": self.output_ref,
                "tool_calls": [dict(item) for item in self.tool_calls],
                "cost": dict(self.cost),
                "duration_ms": self.duration_ms,
                "error": dict(self.error) if self.error is not None else None,
            },
            "writes_canon": False,
            "is_canon": False,
            "auto_approved": False,
            "kept": True,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "agent_id": self.agent_id,
            "input_ref": self.input_ref,
            "output_ref": self.output_ref,
            "output_type": self.output_type,
            "tool": self.tool,
            "tool_names": [
                item.get("tool") for item in self.tool_calls if isinstance(item, dict)
            ],
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error_code": (self.error or {}).get("error") if self.error else None,
            "cost_tokens": self.cost.get("total_tokens"),
            "correlation_id": self.correlation_id,
            "writes_canon": False,
            "is_canon": False,
            "auto_approved": False,
        }

    def replay_refs(self) -> dict[str, Any]:
        """Enough to replay the run without re-calling a model."""
        return {
            "run_id": self.id,
            "agent_id": self.agent_id,
            "input_ref": self.input_ref,
            "output_ref": self.output_ref,
            "output_type": self.output_type,
            "tool_calls": [dict(item) for item in self.tool_calls],
            "cost": dict(self.cost),
            "duration_ms": self.duration_ms,
            "error": dict(self.error) if self.error is not None else None,
            "status": self.status,
            "replayable": True,
        }
