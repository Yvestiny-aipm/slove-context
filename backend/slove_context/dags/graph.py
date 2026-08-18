"""Fixed single-scene DAG (node 8.3).

Nodes are stateless executors. The orchestrator owns state, inputs,
permissions, and the human-approval gate. Parallel nodes declare
disjoint write sets. No 8.4 batch. No auto Canon approve.
"""

from __future__ import annotations

from dataclasses import dataclass

NODE_CONTEXT_PACK = "context_pack"
NODE_SCENE_PLAN = "scene_plan"
NODE_PLAN_VALIDATION = "plan_validation"
NODE_SCENE_DRAFT = "scene_draft"
NODE_CANDIDATE_EXTRACTION = "candidate_extraction"
NODE_DRAFT_VALIDATION = "draft_validation"
NODE_HUMAN_REVIEW = "human_review"
NODE_CANON_COMMIT = "canon_commit"
NODE_SUMMARY = "summary"
NODE_DOWNSTREAM_UNBLOCK = "downstream_unblock"

NODE_IDS = (
    NODE_CONTEXT_PACK,
    NODE_SCENE_PLAN,
    NODE_PLAN_VALIDATION,
    NODE_SCENE_DRAFT,
    NODE_CANDIDATE_EXTRACTION,
    NODE_DRAFT_VALIDATION,
    NODE_HUMAN_REVIEW,
    NODE_CANON_COMMIT,
    NODE_SUMMARY,
    NODE_DOWNSTREAM_UNBLOCK,
)

FAILURE_STOP = "stop_subsequent"
FAILURE_WAIT = "wait_human"
FAILURE_GATE = "human_gate_only"

KIND_WORKER = "worker"
KIND_LOCAL = "local"
KIND_HUMAN = "human"
KIND_CANON_SUBMIT = "canon_submit"


@dataclass(frozen=True)
class NodeSpec:
    """Declarative node: inputs, outputs, deps, failure, retryability."""

    id: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    dependencies: tuple[str, ...]
    writes: frozenset[str]
    failure_policy: str
    retryable: bool
    kind: str
    job_type: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "dependencies": list(self.dependencies),
            "writes": sorted(self.writes),
            "failure_policy": self.failure_policy,
            "retryable": self.retryable,
            "kind": self.kind,
            "job_type": self.job_type,
            "auto_approve": False,
            "writes_canon": self.id == NODE_CANON_COMMIT,
        }


# context_pack and scene_plan write different resources and may start
# together. candidate_extraction and draft_validation both depend on
# scene_draft and write different resources; draft_validation also
# needs extract outputs at runtime (5.1 requires Extracted candidates).
NODE_SPECS: dict[str, NodeSpec] = {
    NODE_CONTEXT_PACK: NodeSpec(
        id=NODE_CONTEXT_PACK,
        inputs=("scene_id", "snapshot_id", "story_spec"),
        outputs=("context_pack_id",),
        dependencies=(),
        writes=frozenset({"context_pack"}),
        failure_policy=FAILURE_STOP,
        retryable=True,
        kind=KIND_WORKER,
        job_type="context_pack",
    ),
    NODE_SCENE_PLAN: NodeSpec(
        id=NODE_SCENE_PLAN,
        inputs=("scene_id", "snapshot_id"),
        outputs=("plan_id",),
        dependencies=(),
        writes=frozenset({"scene_plan"}),
        failure_policy=FAILURE_STOP,
        retryable=True,
        kind=KIND_WORKER,
        job_type="plan",
    ),
    NODE_PLAN_VALIDATION: NodeSpec(
        id=NODE_PLAN_VALIDATION,
        inputs=("plan_id",),
        outputs=("plan_valid",),
        dependencies=(NODE_SCENE_PLAN,),
        writes=frozenset(),
        failure_policy=FAILURE_STOP,
        retryable=True,
        kind=KIND_LOCAL,
    ),
    NODE_SCENE_DRAFT: NodeSpec(
        id=NODE_SCENE_DRAFT,
        inputs=("scene_id", "snapshot_id", "plan_id", "context_pack_id"),
        outputs=("draft_revision_id", "content_hash"),
        dependencies=(NODE_CONTEXT_PACK, NODE_PLAN_VALIDATION),
        writes=frozenset({"scene_draft"}),
        failure_policy=FAILURE_STOP,
        retryable=True,
        kind=KIND_WORKER,
        job_type="draft",
    ),
    NODE_CANDIDATE_EXTRACTION: NodeSpec(
        id=NODE_CANDIDATE_EXTRACTION,
        inputs=("scene_id", "draft_revision_id"),
        outputs=("candidate_ids",),
        dependencies=(NODE_SCENE_DRAFT,),
        writes=frozenset({"candidate_change"}),
        failure_policy=FAILURE_STOP,
        retryable=True,
        kind=KIND_WORKER,
        job_type="extract",
    ),
    NODE_DRAFT_VALIDATION: NodeSpec(
        id=NODE_DRAFT_VALIDATION,
        inputs=("scene_id", "snapshot_id", "candidate_ids"),
        outputs=("validation_run_id", "validation_report_id"),
        dependencies=(NODE_SCENE_DRAFT,),
        writes=frozenset({"validation_report"}),
        failure_policy=FAILURE_STOP,
        retryable=True,
        kind=KIND_WORKER,
        job_type="validate",
    ),
    NODE_HUMAN_REVIEW: NodeSpec(
        id=NODE_HUMAN_REVIEW,
        inputs=("candidate_ids", "validation_report_id"),
        outputs=("human_decision", "review_queue_item_ids"),
        dependencies=(NODE_CANDIDATE_EXTRACTION, NODE_DRAFT_VALIDATION),
        writes=frozenset({"review_queue_item", "approval_decision"}),
        failure_policy=FAILURE_WAIT,
        retryable=False,
        kind=KIND_HUMAN,
    ),
    NODE_CANON_COMMIT: NodeSpec(
        id=NODE_CANON_COMMIT,
        inputs=("candidate_ids", "human_decision"),
        outputs=("submitted_canon_fact_ids",),
        dependencies=(NODE_HUMAN_REVIEW,),
        writes=frozenset({"canon_fact"}),
        failure_policy=FAILURE_GATE,
        retryable=False,
        kind=KIND_CANON_SUBMIT,
    ),
    NODE_SUMMARY: NodeSpec(
        id=NODE_SUMMARY,
        inputs=("scene_id", "draft_revision_id", "content_hash"),
        outputs=("summary_id",),
        dependencies=(NODE_CANON_COMMIT,),
        writes=frozenset({"scene_summary"}),
        failure_policy=FAILURE_STOP,
        retryable=True,
        kind=KIND_WORKER,
        job_type="summarize",
    ),
    NODE_DOWNSTREAM_UNBLOCK: NodeSpec(
        id=NODE_DOWNSTREAM_UNBLOCK,
        inputs=("scene_id",),
        outputs=("unblocked_scene_ids",),
        dependencies=(NODE_SUMMARY,),
        writes=frozenset(),
        failure_policy=FAILURE_STOP,
        retryable=True,
        kind=KIND_LOCAL,
    ),
}


def spec_for(node_id: str) -> NodeSpec:
    return NODE_SPECS[node_id]


def descendants_of(node_id: str) -> list[str]:
    """Nodes that (transitively) depend on node_id, including itself."""
    dependents: dict[str, list[str]] = {item: [] for item in NODE_IDS}
    for item_id, spec in NODE_SPECS.items():
        for dep in spec.dependencies:
            dependents[dep].append(item_id)
    seen: list[str] = []
    stack = [node_id]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.append(current)
        stack.extend(dependents[current])
    order = {item: index for index, item in enumerate(NODE_IDS)}
    return sorted(seen, key=lambda item: order[item])


def ancestors_of(node_id: str) -> list[str]:
    """Strict ancestors (not including node_id)."""
    seen: list[str] = []
    stack = list(NODE_SPECS[node_id].dependencies)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.append(current)
        stack.extend(NODE_SPECS[current].dependencies)
    order = {item: index for index, item in enumerate(NODE_IDS)}
    return sorted(seen, key=lambda item: order[item])


def parallel_write_pairs() -> list[tuple[str, str]]:
    """Declared sibling pairs that must not write the same resource."""
    return [
        (NODE_CONTEXT_PACK, NODE_SCENE_PLAN),
        (NODE_CANDIDATE_EXTRACTION, NODE_DRAFT_VALIDATION),
    ]


def writes_are_disjoint(left: str, right: str) -> bool:
    return NODE_SPECS[left].writes.isdisjoint(NODE_SPECS[right].writes)


def normalize_node_id(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped in NODE_IDS:
        return stripped
    lowered = stripped.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "pack": NODE_CONTEXT_PACK,
        "plan": NODE_SCENE_PLAN,
        "validate_plan": NODE_PLAN_VALIDATION,
        "draft": NODE_SCENE_DRAFT,
        "extract": NODE_CANDIDATE_EXTRACTION,
        "validate": NODE_DRAFT_VALIDATION,
        "validate_draft": NODE_DRAFT_VALIDATION,
        "review": NODE_HUMAN_REVIEW,
        "commit": NODE_CANON_COMMIT,
        "summarize": NODE_SUMMARY,
        "unblock": NODE_DOWNSTREAM_UNBLOCK,
    }
    if lowered in NODE_IDS:
        return lowered
    return aliases.get(lowered)
