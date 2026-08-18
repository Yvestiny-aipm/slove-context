"""Deterministic narrative-consistency eval runner (node 9.1).

Calls existing 5.x ``DeterministicRuleEngine`` on in-memory fixtures.
Adds eval-only checks only for categories 5.x cannot express.
Never writes Canon, never approves, never calls a real model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slove_context.audit import AuditWriter
from slove_context.evals.adapters import (
    candidate_from_payload,
    entities_from_snapshot,
    facts_from_snapshot,
    story_spec_version,
)
from slove_context.evals.eval_rules import evaluate_eval_only
from slove_context.evals.loader import load_all_cases, load_case
from slove_context.evals.models import (
    CaseResult,
    LoadedEvalCase,
    RunSummary,
    violation_key,
    violation_to_dict,
)
from slove_context.evals.paths import find_evals_root
from slove_context.validation.rules import DeterministicRuleEngine

_RULES = DeterministicRuleEngine()


def run_case(
    case: LoadedEvalCase | Path | str,
    *,
    audit_writer: AuditWriter | None = None,
) -> CaseResult:
    loaded = case if isinstance(case, LoadedEvalCase) else load_case(Path(case))
    draft_id = str(loaded.draft["id"])
    candidates = [
        candidate_from_payload(item, draft_id=draft_id)
        for item in loaded.expected_candidates
    ]
    observed = [
        violation_to_dict(item)
        for item in _RULES.evaluate(
            candidates=candidates,
            facts=facts_from_snapshot(loaded.canon_snapshot),
            entities=entities_from_snapshot(loaded.canon_snapshot),
            spec=story_spec_version(loaded.story_spec),
        )
    ]
    observed.extend(
        violation_to_dict(item)
        for item in evaluate_eval_only(
            story_spec=loaded.story_spec,
            draft=loaded.draft,
        )
    )
    result = _score_case(loaded, observed)
    if audit_writer is not None:
        _write_audit(audit_writer, result)
    return result


def run_all(
    *,
    evals_root: Path | None = None,
    audit_writer: AuditWriter | None = None,
) -> tuple[list[CaseResult], RunSummary]:
    root = evals_root or find_evals_root()
    results = [
        run_case(item, audit_writer=audit_writer) for item in load_all_cases(root)
    ]
    return results, summarize(results)


def summarize(results: list[CaseResult]) -> RunSummary:
    hits = sum(item.hits for item in results)
    misses = sum(item.misses for item in results)
    extras = sum(item.extras for item in results)
    cases_passed = sum(1 for item in results if item.passed)
    predicted = hits + extras
    actual = hits + misses
    precision = (hits / predicted) if predicted else 1.0
    recall = (hits / actual) if actual else 1.0
    return RunSummary(
        cases_run=len(results),
        cases_passed=cases_passed,
        cases_failed=len(results) - cases_passed,
        hits=hits,
        misses=misses,
        extras=extras,
        precision=round(precision, 4),
        recall=round(recall, 4),
        passed=bool(results) and all(item.passed for item in results),
        categories=[item.rule_category for item in results],
    )


def write_report(
    results: list[CaseResult],
    summary: RunSummary,
    destination: Path,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": summary.to_public_dict(),
        "cases": [item.to_public_dict() for item in results],
    }
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def _score_case(loaded: LoadedEvalCase, observed: list[dict[str, Any]]) -> CaseResult:
    expected = [dict(item) for item in loaded.expected_violations]
    remaining = list(observed)
    hits = 0
    missed: list[dict[str, Any]] = []
    for payload in expected:
        key = violation_key(payload)
        match_at = next(
            (
                index
                for index, item in enumerate(remaining)
                if violation_key(item) == key
            ),
            None,
        )
        if match_at is None:
            missed.append(payload)
            continue
        hits += 1
        remaining.pop(match_at)
    extras = remaining
    misses = len(missed)
    extra_count = len(extras)
    return CaseResult(
        case_id=loaded.manifest.id,
        rule_category=loaded.manifest.rule_category,
        difficulty=loaded.manifest.difficulty,
        expected_severity=loaded.manifest.expected_severity,
        passed=misses == 0 and extra_count == 0,
        hits=hits,
        misses=misses,
        extras=extra_count,
        expected_violation_count=len(expected),
        observed_violation_count=len(observed),
        observed_violations=observed,
        expected_violations=expected,
        missed_violations=missed,
        extra_violations=extras,
        observed_rule_ids=[str(item["rule_id"]) for item in observed],
    )


def _write_audit(writer: AuditWriter, result: CaseResult) -> None:
    writer.write(
        actor_type="system",
        actor_id="eval-runner",
        action="eval_run",
        resource_type="eval_case",
        resource_id=result.case_id,
        after_json=result.to_audit_dict(),
    )
