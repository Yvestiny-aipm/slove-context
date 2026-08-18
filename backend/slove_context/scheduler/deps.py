"""Wire 8.1 Worker / 8.2 PermissionGuard / 8.3 DAG for the 8.4 scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from slove_context.dags.deps import DagServices, dag_services_from_state
from slove_context.dags.service import DagService


@dataclass
class SchedulerServices:
    dags: DagService
    dag_bundle: DagServices


def scheduler_services_from_state(state: Any) -> SchedulerServices:
    bundle = dag_services_from_state(state)
    dags = DagService(
        story_repository=state.repository,
        dag_repository=state.dag_repository,
        audit_writer=state.audit_writer,
        services=bundle,
    )
    return SchedulerServices(dags=dags, dag_bundle=bundle)
