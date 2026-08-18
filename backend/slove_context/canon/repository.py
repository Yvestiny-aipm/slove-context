"""Canon repository. Tests use the in-memory implementation."""

from __future__ import annotations

from typing import Protocol

from slove_context.canon.models import CanonFact, CanonSnapshot, Entity, EvidenceRecord


class CanonRepository(Protocol):
    def add_entity(self, entity: Entity) -> None: ...

    def get_entity(self, entity_id: str) -> Entity | None: ...

    def list_entities(self, project_id: str) -> list[Entity]: ...

    def find_entity(
        self, project_id: str, entity_type: str, name: str
    ) -> Entity | None: ...

    def add_evidence(self, evidence: EvidenceRecord) -> None: ...

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None: ...

    def add_fact(self, fact: CanonFact) -> None: ...

    def get_fact(self, fact_id: str) -> CanonFact | None: ...

    def list_facts(self, project_id: str) -> list[CanonFact]: ...

    def save_fact(self, fact: CanonFact) -> None: ...

    def add_snapshot(self, snapshot: CanonSnapshot) -> None: ...

    def get_snapshot(self, snapshot_id: str) -> CanonSnapshot | None: ...

    def save_snapshot(self, snapshot: CanonSnapshot) -> None: ...


class InMemoryCanonRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self.evidence: dict[str, EvidenceRecord] = {}
        self.facts: dict[str, CanonFact] = {}
        self.snapshots: dict[str, CanonSnapshot] = {}

    def add_entity(self, entity: Entity) -> None:
        self.entities[entity.id] = entity

    def get_entity(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    def list_entities(self, project_id: str) -> list[Entity]:
        return [
            item for item in self.entities.values() if item.project_id == project_id
        ]

    def find_entity(
        self, project_id: str, entity_type: str, name: str
    ) -> Entity | None:
        for item in self.entities.values():
            if (
                item.project_id == project_id
                and item.entity_type == entity_type
                and item.name == name
            ):
                return item
        return None

    def add_evidence(self, evidence: EvidenceRecord) -> None:
        self.evidence[evidence.id] = evidence

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        return self.evidence.get(evidence_id)

    def add_fact(self, fact: CanonFact) -> None:
        self.facts[fact.id] = fact

    def get_fact(self, fact_id: str) -> CanonFact | None:
        return self.facts.get(fact_id)

    def list_facts(self, project_id: str) -> list[CanonFact]:
        return [item for item in self.facts.values() if item.project_id == project_id]

    def save_fact(self, fact: CanonFact) -> None:
        self.facts[fact.id] = fact

    def add_snapshot(self, snapshot: CanonSnapshot) -> None:
        self.snapshots[snapshot.id] = snapshot

    def get_snapshot(self, snapshot_id: str) -> CanonSnapshot | None:
        return self.snapshots.get(snapshot_id)

    def save_snapshot(self, snapshot: CanonSnapshot) -> None:
        self.snapshots[snapshot.id] = snapshot
