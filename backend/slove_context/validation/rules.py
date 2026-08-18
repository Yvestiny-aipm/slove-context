"""Deterministic Validation Rules (node 5.1).

Compares Candidate Changes against Active Canon (or snapshot facts) and
a written / effective Story Spec. No LLM. No network.

Canon wins over draft / candidate: a conflict is a Blocking Violation
and the run is RuleFailed. Rules themselves do not write Canon and
are not Approval.
"""

from __future__ import annotations

from typing import Any, Protocol

from slove_context.candidate_change.models import CandidateChange
from slove_context.canon.models import CanonFact, Entity
from slove_context.story.models import StorySpecVersion
from slove_context.validation.models import (
    ACTION_HUMAN_REJECT,
    ACTION_REGENERATE,
    RULE_CANON_CONFLICT,
    RULE_SPEC_FORBID,
    SEVERITY_BLOCKING,
    Violation,
)


class RuleEngine(Protocol):
    def evaluate(
        self,
        *,
        candidates: list[CandidateChange],
        facts: list[CanonFact],
        entities: list[Entity],
        spec: StorySpecVersion,
    ) -> list[Violation]: ...


class DeterministicRuleEngine:
    """Small rule engine: Active-fact conflict + Story Spec forbid-list."""

    def evaluate(
        self,
        *,
        candidates: list[CandidateChange],
        facts: list[CanonFact],
        entities: list[Entity],
        spec: StorySpecVersion,
    ) -> list[Violation]:
        entities_by_id = {item.id: item for item in entities}
        violations: list[Violation] = []
        for candidate in candidates:
            violations.extend(
                _canon_conflicts(candidate, facts=facts, entities_by_id=entities_by_id)
            )
            violations.extend(_spec_forbids(candidate, spec=spec))
        return violations


def _canon_conflicts(
    candidate: CandidateChange,
    *,
    facts: list[CanonFact],
    entities_by_id: dict[str, Entity],
) -> list[Violation]:
    violations: list[Violation] = []
    candidate_values = _normalized_set((candidate.object, candidate.value))
    for fact in facts:
        entity = entities_by_id.get(fact.entity_id)
        if entity is None:
            continue
        if not _entity_mentions_candidate(entity, candidate):
            continue
        if fact.predicate != candidate.predicate:
            continue
        fact_values = _fact_value_set(fact.value_json)
        if not fact_values or not candidate_values:
            continue
        if not fact_values.isdisjoint(candidate_values):
            continue
        entity_ids = [entity.name]
        if candidate.subject and candidate.subject not in entity_ids:
            entity_ids.append(candidate.subject)
        if candidate.object and candidate.object not in entity_ids:
            entity_ids.append(candidate.object)
        violations.append(
            Violation(
                rule_id=RULE_CANON_CONFLICT,
                severity=SEVERITY_BLOCKING,
                entity_ids=entity_ids,
                source_evidence=candidate.evidence_quote,
                canon_evidence=_canon_evidence_text(entity, fact),
                recommended_action=ACTION_HUMAN_REJECT,
            )
        )
    return violations


def _spec_forbids(
    candidate: CandidateChange, *, spec: StorySpecVersion
) -> list[Violation]:
    haystack = (
        f"{candidate.subject} {candidate.predicate} {candidate.object} "
        f"{candidate.value} {candidate.evidence_quote}"
    )
    violations: list[Violation] = []
    for raw in spec.must_not_write:
        phrase = _forbid_phrase(raw)
        if not phrase:
            continue
        if phrase not in haystack and raw not in haystack:
            continue
        entity_ids = [candidate.subject]
        if candidate.object and candidate.object not in entity_ids:
            entity_ids.append(candidate.object)
        violations.append(
            Violation(
                rule_id=RULE_SPEC_FORBID,
                severity=SEVERITY_BLOCKING,
                entity_ids=entity_ids,
                source_evidence=candidate.evidence_quote,
                canon_evidence=f"Story Spec must_not_write: {raw}",
                recommended_action=ACTION_REGENERATE,
            )
        )
    return violations


def _entity_mentions_candidate(entity: Entity, candidate: CandidateChange) -> bool:
    name = entity.name.strip()
    if not name:
        return False
    return (
        name
        in {
            candidate.subject,
            candidate.object,
            candidate.value,
        }
        or name in candidate.evidence_quote
    )


def _fact_value_set(value_json: Any) -> set[str]:
    texts: list[str] = []
    if isinstance(value_json, str):
        texts.append(value_json)
    elif isinstance(value_json, dict):
        for key in ("value", "object", "text"):
            item = value_json.get(key)
            if isinstance(item, str):
                texts.append(item)
    return _normalized_set(texts)


def _canon_evidence_text(entity: Entity, fact: CanonFact) -> str:
    values = sorted(_fact_value_set(fact.value_json))
    value_text = values[0] if values else str(fact.value_json)
    return f"{entity.name} {fact.predicate} {value_text}"


def _forbid_phrase(raw: str) -> str:
    stripped = raw.strip()
    for prefix in ("禁止", "不得", "不要"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :].strip()
            break
    return stripped


def _normalized_set(values: tuple[str, ...] | list[str]) -> set[str]:
    return {item.strip() for item in values if isinstance(item, str) and item.strip()}
