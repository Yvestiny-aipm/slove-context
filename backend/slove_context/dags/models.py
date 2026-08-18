"""Single-scene DAG records (node 8.3).

Statuses: pending / ready / running / succeeded / failed / blocked /
waiting_human / skipped / cancelled. Failure / cancel / blocked keep
the row. canon_commit is not auto-approve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from slove_context.dags.graph import NODE_IDS, NodeSpec, spec_for

STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_WAITING_HUMAN = "waiting_human"
STATUS_SKIPPED = "skipped"
STATUS_CANCELLED = "cancelled"

NODE_STATUSES = frozenset(
    {
        STATUS_PENDING,
        STATUS_READY,
        STATUS_RUNNING,
        STATUS_SUCCEEDED,
        STATUS_FAILED,
        STATUS_BLOCKED,
        STATUS_WAITING_HUMAN,
        STATUS_SKIPPED,
        STATUS_CANCELLED,
    }
)

DAG_CREATED = "created"
DAG_RUNNING = "running"
DAG_WAITING_HUMAN = "waiting_human"
DAG_BLOCKED = "blocked"
DAG_SUCCEEDED = "succeeded"
DAG_FAILED = "failed"
DAG_CANCELLED = "cancelled"

DAG_STATUSES = frozenset(
    {
        DAG_CREATED,
        DAG_RUNNING,
        DAG_WAITING_HUMAN,
        DAG_BLOCKED,
        DAG_SUCCEEDED,
        DAG_FAILED,
        DAG_CANCELLED,
    }
)

TERMINAL_DAG_STATUSES = frozenset(
    {DAG_SUCCEEDED, DAG_FAILED, DAG_CANCELLED, DAG_BLOCKED}
)
KEEP_NODE_STATUSES = frozenset(
    {STATUS_FAILED, STATUS_BLOCKED, STATUS_CANCELLED, STATUS_SUCCEEDED}
)
DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"
HUMAN_DECISIONS = frozenset({DECISION_APPROVE, DECISION_REJECT})


@dataclass
class DagNode:
    id: str
    dag_id: str
    node_id: str
    status: str
    created_at: str
    updated_at: str
    job_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_detail: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    reused_upstream: bool = False

    @property
    def spec(self) -> NodeSpec:
        return spec_for(self.node_id)

    def to_public_dict(self) -> dict[str, Any]:
        declared = self.spec.to_public_dict()
        return {
            "id": self.id,
            "dag_id": self.dag_id,
            "node_id": self.node_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "job_id": self.job_id,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "outputs": dict(self.outputs),
            "reused_upstream": self.reused_upstream,
            "inputs": declared["inputs"],
            "declared_outputs": declared["outputs"],
            "dependencies": declared["dependencies"],
            "writes": declared["writes"],
            "failure_policy": declared["failure_policy"],
            "retryable": declared["retryable"],
            "kind": declared["kind"],
            "job_type": declared["job_type"],
            "writes_canon": self.node_id == "canon_commit",
            "auto_approved": False,
            "kept": True,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "dag_id": self.dag_id,
            "node_id": self.node_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "job_id": self.job_id,
            "error_code": self.error_code,
            "output_keys": sorted(self.outputs.keys()),
            "reused_upstream": self.reused_upstream,
            "writes_canon": False,
            "auto_approved": False,
        }

    def graph_dict(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "dependencies": list(self.spec.dependencies),
            "writes": sorted(self.spec.writes),
            "failure_policy": self.spec.failure_policy,
            "retryable": self.spec.retryable,
            "outputs": {
                key: value
                for key, value in self.outputs.items()
                if isinstance(value, str | int | float | bool | list) or value is None
            },
            "error_code": self.error_code,
            "reused_upstream": self.reused_upstream,
        }


@dataclass
class SceneDag:
    id: str
    project_id: str
    scene_id: str
    snapshot_id: str
    status: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    correlation_id: str
    rebuild_context_pack: bool = False
    start_from: str | None = None
    blocked: bool = False
    blocker_node_id: str | None = None
    blocker_reason: str | None = None
    human_decision: str | None = None
    human_reason_code: str | None = None
    human_actor_type: str | None = None
    human_actor_id: str | None = None
    frozen_outputs: dict[str, Any] = field(default_factory=dict)
    nodes: dict[str, DagNode] = field(default_factory=dict)

    def node(self, node_id: str) -> DagNode:
        return self.nodes[node_id]

    def ordered_nodes(self) -> list[DagNode]:
        return [self.nodes[item] for item in NODE_IDS if item in self.nodes]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "rebuild_context_pack": self.rebuild_context_pack,
            "start_from": self.start_from,
            "blocked": self.blocked,
            "blocker_node_id": self.blocker_node_id,
            "blocker_reason": self.blocker_reason,
            "human_decision": self.human_decision,
            "human_reason_code": self.human_reason_code,
            "frozen_outputs": _public_outputs(self.frozen_outputs),
            "nodes": [item.to_public_dict() for item in self.ordered_nodes()],
            "writes_canon": False,
            "auto_approved": False,
            "auto_canon_commit": False,
            "kept": True,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "blocked": self.blocked,
            "blocker_node_id": self.blocker_node_id,
            "human_decision": self.human_decision,
            "start_from": self.start_from,
            "rebuild_context_pack": self.rebuild_context_pack,
            "frozen_output_keys": sorted(self.frozen_outputs.keys()),
            "writes_canon": False,
            "auto_approved": False,
            "auto_canon_commit": False,
        }

    def graph_dict(self) -> dict[str, Any]:
        nodes = [item.graph_dict() for item in self.ordered_nodes()]
        edges = []
        for item in self.ordered_nodes():
            for dep in item.spec.dependencies:
                edges.append({"from": dep, "to": item.node_id})
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "status": self.status,
            "blocked": self.blocked,
            "blocker_node_id": self.blocker_node_id,
            "human_decision": self.human_decision,
            "nodes": nodes,
            "edges": edges,
            "writes_canon": False,
            "auto_approved": False,
        }


def _public_outputs(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if isinstance(value, str | int | float | bool | list) or value is None
    }
