"""Allowed and forbidden parallelism (node 8.4).

Allowed: independent projects, read-only checks on the same scene,
early planning with no write dependency.

Forbidden: prose scenes with before/after state dependencies,
Canon writes, conflicting updates against the same Canon Snapshot.

Does not bypass PermissionGuard. Does not invent a Canon write path.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from slove_context.scene.models import DEPENDENCY_SATISFYING_STATUSES, Scene
from slove_context.scheduler.models import (
    DECISION_ENQUEUED,
    DECISION_HELD,
    DECISION_REJECTED,
    DECISION_SKIPPED,
    KIND_CANON_WRITE,
    KIND_PLANNING,
    KIND_PROSE_WRITE,
    KIND_READ_CHECK,
    REASON_ALREADY_ENQUEUED,
    REASON_CANON_WRITE_PARALLEL,
    REASON_COST_CAP,
    REASON_ELIGIBLE,
    REASON_INDEPENDENT_PROJECT,
    REASON_PLANNING,
    REASON_PROSE_STATE_DEPENDENCY,
    REASON_READ_CHECK,
    REASON_SCENE_NOT_APPROVED,
    REASON_SNAPSHOT_CANON_CONFLICT,
    REASON_UNAPPROVED_DEPENDENCY,
)


@dataclass(frozen=True)
class ParallelismVerdict:
    action: str
    reason_code: str
    message: str
    task_kind: str

    @property
    def may_enqueue(self) -> bool:
        return self.action == DECISION_ENQUEUED


@dataclass(frozen=True)
class ActiveSlot:
    project_id: str
    scene_id: str
    snapshot_id: str | None
    task_kind: str
    dag_id: str | None = None


def ancestor_ids(scene: Scene, scenes_by_id: dict[str, Scene]) -> set[str]:
    """Transitive depends_on ancestors (before-state scenes)."""
    seen: set[str] = set()
    stack = list(scene.depends_on)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        parent = scenes_by_id.get(current)
        if parent is not None:
            stack.extend(parent.depends_on)
    return seen


def scenes_have_state_dependency(
    left: Scene, right: Scene, scenes_by_id: dict[str, Scene]
) -> bool:
    """True when either scene is a before/after ancestor of the other."""
    if left.id == right.id:
        return False
    return left.id in ancestor_ids(right, scenes_by_id) or right.id in ancestor_ids(
        left, scenes_by_id
    )


def decide(
    scene: Scene,
    *,
    task_kind: str,
    snapshot_id: str | None,
    unsatisfied_dependencies: Iterable[str],
    active: Iterable[ActiveSlot],
    scenes_by_id: dict[str, Scene],
    estimated_cost: float,
    per_scene_cost_cap: float,
    completed_scene_ids: Iterable[str] | None = None,
) -> ParallelismVerdict:
    """Why a scene DAG / task may or may not be enqueued."""
    kind = (
        task_kind
        if task_kind
        in {
            KIND_PLANNING,
            KIND_READ_CHECK,
            KIND_PROSE_WRITE,
            KIND_CANON_WRITE,
        }
        else KIND_PROSE_WRITE
    )
    active_slots = list(active)
    unsatisfied = [item for item in unsatisfied_dependencies if item]

    if scene.status not in DEPENDENCY_SATISFYING_STATUSES:
        return ParallelismVerdict(
            action=DECISION_SKIPPED,
            reason_code=REASON_SCENE_NOT_APPROVED,
            message=(
                "Scene Card is not approved. Only approved (or published) "
                "scenes whose dependencies are approved may be enqueued."
            ),
            task_kind=kind,
        )
    if unsatisfied:
        return ParallelismVerdict(
            action=DECISION_SKIPPED,
            reason_code=REASON_UNAPPROVED_DEPENDENCY,
            message=(
                "A dependency Scene Card is not yet approved. The scene "
                "stays out of the queue (3.1 generatable semantics)."
            ),
            task_kind=kind,
        )

    if kind == KIND_CANON_WRITE:
        return ParallelismVerdict(
            action=DECISION_REJECTED,
            reason_code=REASON_CANON_WRITE_PARALLEL,
            message=(
                "Canon writes are never parallel and never scheduled by "
                "the batch scheduler. Submit remains 4.2 / 8.3 "
                "canon_commit after a human 主编 approve."
            ),
            task_kind=kind,
        )

    if estimated_cost > per_scene_cost_cap:
        return ParallelismVerdict(
            action=DECISION_HELD,
            reason_code=REASON_COST_CAP,
            message=(
                "Estimated per-scene cost exceeds the configured cap. "
                "The scene is held; the scheduler does not write Canon."
            ),
            task_kind=kind,
        )

    for slot in active_slots:
        if slot.scene_id == scene.id and slot.task_kind == kind:
            return ParallelismVerdict(
                action=DECISION_HELD,
                reason_code=REASON_ALREADY_ENQUEUED,
                message="This scene already has an in-flight task of the same kind.",
                task_kind=kind,
            )
        if (
            slot.task_kind == KIND_CANON_WRITE
            and snapshot_id
            and (slot.snapshot_id == snapshot_id)
        ):
            return ParallelismVerdict(
                action=DECISION_REJECTED,
                reason_code=REASON_SNAPSHOT_CANON_CONFLICT,
                message=(
                    "Conflicting Canon updates against the same Snapshot "
                    "are forbidden. Canon submit stays serial and human-only."
                ),
                task_kind=kind,
            )

    if kind == KIND_READ_CHECK:
        return ParallelismVerdict(
            action=DECISION_ENQUEUED,
            reason_code=REASON_READ_CHECK,
            message="Read-only checks may run in parallel, including on the same scene.",
            task_kind=kind,
        )

    if kind == KIND_PLANNING:
        return ParallelismVerdict(
            action=DECISION_ENQUEUED,
            reason_code=REASON_PLANNING,
            message="Early planning with no write dependency may run in parallel.",
            task_kind=kind,
        )

    for slot in active_slots:
        if slot.project_id != scene.project_id:
            continue
        other = scenes_by_id.get(slot.scene_id)
        if other is None:
            continue
        if slot.task_kind in {KIND_PROSE_WRITE, KIND_CANON_WRITE} and (
            scenes_have_state_dependency(scene, other, scenes_by_id)
        ):
            return ParallelismVerdict(
                action=DECISION_HELD,
                reason_code=REASON_PROSE_STATE_DEPENDENCY,
                message=(
                    "Prose scenes with a before/after state dependency "
                    "must be serialized. The downstream scene is held."
                ),
                task_kind=kind,
            )
        if (
            slot.task_kind == KIND_CANON_WRITE
            and snapshot_id
            and slot.snapshot_id == snapshot_id
        ):
            return ParallelismVerdict(
                action=DECISION_REJECTED,
                reason_code=REASON_SNAPSHOT_CANON_CONFLICT,
                message=(
                    "Conflicting updates against the same Canon Snapshot are forbidden."
                ),
                task_kind=kind,
            )

    completed = set(completed_scene_ids or ())
    incomplete_ancestors = _incomplete_ancestors(
        scene, scenes_by_id, active_slots, completed
    )
    if kind == KIND_PROSE_WRITE and incomplete_ancestors:
        return ParallelismVerdict(
            action=DECISION_HELD,
            reason_code=REASON_PROSE_STATE_DEPENDENCY,
            message=(
                "An upstream scene with a before/after state dependency "
                "has not finished. Downstream prose is serialized."
            ),
            task_kind=kind,
        )

    return ParallelismVerdict(
        action=DECISION_ENQUEUED,
        reason_code=REASON_ELIGIBLE,
        message="Scene is generatable and has no forbidden write-conflict.",
        task_kind=kind,
    )


def _incomplete_ancestors(
    scene: Scene,
    scenes_by_id: dict[str, Scene],
    active: list[ActiveSlot],
    completed: set[str],
) -> list[str]:
    ancestors = ancestor_ids(scene, scenes_by_id)
    if not ancestors:
        return []
    active_ids = {
        slot.scene_id for slot in active if slot.task_kind == KIND_PROSE_WRITE
    }
    unfinished = (ancestors - completed) | (ancestors & active_ids)
    return sorted(unfinished)


def independent_project_ok(left_project_id: str, right_project_id: str) -> bool:
    return left_project_id != right_project_id


def planning_kind_for(task_kind: str) -> bool:
    return task_kind == KIND_PLANNING


def forbidden_canon_pair(left: ActiveSlot, right: ActiveSlot) -> bool:
    if left.task_kind != KIND_CANON_WRITE and right.task_kind != KIND_CANON_WRITE:
        return False
    if left.snapshot_id and left.snapshot_id == right.snapshot_id:
        return True
    return left.task_kind == KIND_CANON_WRITE and right.task_kind == KIND_CANON_WRITE


def reason_for_independent_projects() -> str:
    return REASON_INDEPENDENT_PROJECT
