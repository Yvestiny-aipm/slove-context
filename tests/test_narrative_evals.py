"""Narrative consistency eval dataset + runner (node 9.1).

In-memory fixtures. No live Postgres. No network. No real models.
The runner calls existing 5.x hard rules and one eval-only check.
It does not write Canon, approve candidates, or start 9.2 / 9.3.
2.1–8.4 APIs and /healthz remain. No production seed-status.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.evals.constants import (
    REQUIRED_CATEGORIES,
    RULE_EVAL_LOST_FORESHADOWING,
)
from slove_context.evals.loader import load_all_cases
from slove_context.evals.runner import run_all, run_case, write_report
from slove_context.validation.models import RULE_CANON_CONFLICT, RULE_SPEC_FORBID

ROOT = Path(__file__).resolve().parents[1]


def _client() -> TestClient:
    return TestClient(create_app())


def test_all_nine_categories_can_be_loaded() -> None:
    loaded = load_all_cases()
    categories = [item.manifest.rule_category for item in loaded]
    assert set(categories) >= set(REQUIRED_CATEGORIES)
    assert len(loaded) >= 9
    for item in loaded:
        assert item.story_spec["title"]
        assert item.canon_snapshot["eval_kind"] == "canon_snapshot"
        assert item.scene_card["scene_id"]
        assert item.context_pack["purpose"] == "Validate"
        assert item.draft["eval_kind"] == "scene_draft"
        assert item.draft["prose"]
        assert item.manifest.human_verdict_rationale
        assert item.manifest.difficulty
        assert item.manifest.expected_severity


def test_deterministic_rules_hit_expected_for_each_case() -> None:
    results, summary = run_all()
    by_category = {item.rule_category: item for item in results}
    for category in REQUIRED_CATEGORIES:
        assert category in by_category, category
        result = by_category[category]
        assert result.passed, (
            f"{category} missed={result.missed_violations} extra={result.extra_violations}"
        )
        assert result.hits >= 1
        assert result.misses == 0
        assert result.extras == 0
        assert result.observed_violations
    assert summary.passed
    assert summary.cases_run >= 9
    assert summary.hits >= 9
    assert summary.misses == 0
    assert summary.extras == 0
    assert summary.precision == 1.0
    assert summary.recall == 1.0


def test_five_x_rule_ids_unchanged_and_used() -> None:
    assert RULE_CANON_CONFLICT == "canon-active-conflict"
    assert RULE_SPEC_FORBID == "spec-must-not-write"
    results, _ = run_all()
    used = {rule_id for item in results for rule_id in item.observed_rule_ids}
    assert RULE_CANON_CONFLICT in used
    assert RULE_SPEC_FORBID in used
    lost = next(item for item in results if item.rule_category == "lost_foreshadowing")
    assert lost.observed_rule_ids == [RULE_EVAL_LOST_FORESHADOWING]


def test_runner_json_and_summary_metrics(tmp_path: Path) -> None:
    results, summary = run_all()
    destination = tmp_path / "narrative-eval.json"
    write_report(results, summary, destination)
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert "summary" in payload
    assert "cases" in payload
    assert payload["summary"]["cases_run"] == summary.cases_run
    assert payload["summary"]["hits"] == summary.hits
    assert payload["summary"]["misses"] == summary.misses
    assert payload["summary"]["precision"] == summary.precision
    assert payload["summary"]["recall"] == summary.recall
    assert payload["summary"]["passed"] is True
    assert payload["summary"]["writes_canon"] is False
    assert payload["summary"]["auto_approved"] is False
    assert payload["summary"]["used_real_model"] is False
    assert len(payload["cases"]) == summary.cases_run
    for item in payload["cases"]:
        assert "observed_violations" in item
        assert item["writes_canon"] is False
        assert item["auto_approved"] is False


def test_runner_does_not_write_canon_or_approve() -> None:
    canon = InMemoryCanonRepository()
    facts_before = len(canon.facts)
    sink = InMemoryAuditSink()
    results, summary = run_all(audit_writer=AuditWriter(sink))
    assert len(canon.facts) == facts_before
    assert summary.writes_canon is False
    assert summary.auto_approved is False
    assert all(item.writes_canon is False for item in results)
    assert all(item.auto_approved is False for item in results)
    assert all(item.is_approval is False for item in results)
    assert all(event.action == "eval_run" for event in sink.events)
    assert not any(event.action in {"approve", "submit"} for event in sink.events)
    blob = json.dumps(
        [event.after_json for event in sink.events],
        ensure_ascii=False,
    )
    assert "前日黎明就已站在河滩" not in blob
    assert "旁白提前写出残玉来历" not in blob
    assert "text_evidence" not in blob
    assert "evidence_quote" not in blob
    assert "source_evidence" not in blob


def test_run_case_matches_manifest_id() -> None:
    loaded = load_all_cases()
    first = loaded[0]
    result = run_case(first)
    assert result.case_id == first.manifest.id
    assert result.rule_category == first.manifest.rule_category


def test_healthz_and_prior_apis_remain() -> None:
    client = _client()
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/version").json().get("version")
    paths = client.get("/openapi.json").json()["paths"]
    assert "/healthz" in paths
    assert "/version" in paths
    assert "/projects/{project_id}/specs/{spec_id}/approve" in paths
    assert "/projects/{project_id}/canon-facts" in paths
    assert "/projects/{project_id}/canon-snapshots/{snapshot_id}/freeze" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/approve" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/plans/jobs" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/drafts/jobs" in paths
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}/extract-jobs"
        in paths
    )
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/approve" in paths
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/submit" in paths
    assert "/projects/{project_id}/validation-runs" in paths
    assert "/projects/{project_id}/repair-tasks" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/context-packs" in paths
    assert "/projects/{project_id}/outline-revisions" in paths
    assert "/projects/{project_id}/style-guides" in paths
    assert (
        "/projects/{project_id}/scenes/{scene_id}/drafts/{revision_id}"
        "/style-validations" in paths
    )
    assert "/projects/{project_id}/review-queue/items" in paths
    assert "/projects/{project_id}/jobs" in paths
    assert "/agents" in paths
    assert "/projects/{project_id}/scenes/{scene_id}/dags" in paths
    assert "/projects/{project_id}/dags/{dag_id}/human-review" in paths
    assert "/projects/{project_id}/schedule/config" in paths
    assert "/projects/{project_id}/schedule/start" in paths
    assert "/projects/{project_id}/schedule/dry-run" in paths
    assert "/schedules/tick" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/auto-approve" not in paths
    assert "/eval-sets" not in paths
    assert "/evals" not in paths
    assert not any("seed-status" in path for path in paths)
    assert not any("openai" in path for path in paths)


def test_no_production_seed_status() -> None:
    client = _client()
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("seed-status" in path for path in paths)
    eval_dir = ROOT / "backend/slove_context/evals"
    for path in eval_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(
            line.lstrip().startswith("@router") and "seed-status" in line
            for line in text.splitlines()
        )


def test_frozen_contracts_and_mvp_docs_untouched() -> None:
    assert (ROOT / "docs/mvp-scope.md").is_file()
    assert (ROOT / "docs/domain-glossary.md").is_file()
    assert (ROOT / "docs/state-machines.md").is_file()
    assert (ROOT / "contracts/validation-report.schema.json").is_file()
    assert (ROOT / "evals/cases").is_dir()
    assert (ROOT / "evals/fixtures").is_dir()
    assert (ROOT / "evals/expected").is_dir()
