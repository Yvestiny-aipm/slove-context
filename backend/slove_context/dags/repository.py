"""Scene DAG repository. Tests use in-memory. No Postgres."""

from __future__ import annotations

from typing import Protocol

from slove_context.dags.models import DagNode, SceneDag


class DagRepository(Protocol):
    def add_dag(self, dag: SceneDag) -> None: ...

    def get_dag(self, dag_id: str) -> SceneDag | None: ...

    def save_dag(self, dag: SceneDag) -> None: ...

    def add_node(self, node: DagNode) -> None: ...

    def save_node(self, node: DagNode) -> None: ...

    def list_for_scene(self, project_id: str, scene_id: str) -> list[SceneDag]: ...


class InMemoryDagRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.dags: dict[str, SceneDag] = {}
        self.nodes: dict[str, DagNode] = {}

    def add_dag(self, dag: SceneDag) -> None:
        self.dags[dag.id] = dag
        for node in dag.nodes.values():
            self.nodes[node.id] = node

    def get_dag(self, dag_id: str) -> SceneDag | None:
        return self.dags.get(dag_id)

    def save_dag(self, dag: SceneDag) -> None:
        self.dags[dag.id] = dag
        for node in dag.nodes.values():
            self.nodes[node.id] = node

    def add_node(self, node: DagNode) -> None:
        self.nodes[node.id] = node
        dag = self.dags.get(node.dag_id)
        if dag is not None:
            dag.nodes[node.node_id] = node

    def save_node(self, node: DagNode) -> None:
        self.add_node(node)

    def list_for_scene(self, project_id: str, scene_id: str) -> list[SceneDag]:
        items = [
            dag
            for dag in self.dags.values()
            if dag.project_id == project_id and dag.scene_id == scene_id
        ]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items
