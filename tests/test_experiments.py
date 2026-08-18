"""Experiment Run + baseline compare (node 9.2).

In-memory repository. No live Postgres. No network. No real models.
Pins the 9.1 case set and swaps Fake Provider knobs. Does not write
Canon or approve. Not a 9.3 release gate. 2.1–9.1 APIs remain.
No production seed-status. 9.1 expected files stay unchanged.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.experiments.constants import (
    COMPARE_METRICS,
    DEFAULT_PROMPT_VERSION,
    INVALID_PROMPT_VERSION,
)
from slove_context.experiments.repository import InMemoryExperimentRepository
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
SYSTEM = {"X-Actor-Type": "system", "X-Actor-Id": "sys-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}


def _client() -> tuple[
    TestClient,
    InMemoryAuditSink,
    InMemoryCanonRepository,
    FakeProvider,
    InMemoryExperimentRepository,
]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    canon = InMemoryCanonRepository()
    experiments = InMemoryExperimentRepository()
    provider = FakeProvider()
    app = create_app(
        canon_repository=canon,
        experiment_repository=experiments,
        audit_writer=writer,
        llm_gateway=LlmGateway(
            provider,
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
    )
    return TestClient(app), sink, canon, provider, experiments


def _create_experiment(
    client: TestClient,
    *,
    name: str = "baseline-9.1",
    **overrides: object,
) -> dict:
    payload = {"name": name, "created_by": "editor-1"}
    payload.update(overrides)
    response = client.post("/experiments", headers=HUMAN, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _run(client: TestClient, experiment_id: str, **overrides: object) -> dict:
    payload = {"created_by": "editor-1"}
    payload.update(overrides)
    response = client.post(
        f"/experiments/{experiment_id}/runs",
        headers=HUMAN,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_experiment_pins_9_1_cases() -> None:
    client, _, _, _, _ = _client()
    created = _create_experiment(client)
    assert created["status"] == "created"
    assert created["writes_canon"] is False
    assert created["used_real_model"] is False
    assert created["is_release_gate"] is False
    pin = created["case_set_pin"]
    assert pin["version"] == "eval-9.1.0"
    assert len(pin["case_ids"]) >= 9
    assert "timeline-reversal" in pin["case_ids"]
    assert pin["fixture_hashes"]["timeline-reversal"]["draft"]
    assert pin["expected_hashes"]["timeline-reversal"]["violations"]
    assert pin["snapshot_ids"]["timeline-reversal"]
    config = created["config"]
    assert config["model"] == "fake-eval"
    assert config["prompt_version"] == DEFAULT_PROMPT_VERSION
    assert config["retrieval_strategy"] == "snapshot"
    assert config["temperature"] == 0.0
    assert config["max_tokens"] == 256
    listed = client.get("/experiments")
    assert listed.status_code == 200
    assert any(item["id"] == created["id"] for item in listed.json()["items"])


def test_swap_config_records_all_five_knobs() -> None:
    client, _, _, provider, _ = _client()
    created = _create_experiment(client)
    run = _run(
        client,
        created["id"],
        model="fake-eval-b",
        prompt_version="eval-experiment.v2",
        retrieval_strategy="pinned",
        temperature=0.4,
        max_tokens=128,
    )
    config = run["config"]
    assert config["model"] == "fake-eval-b"
    assert config["prompt_version"] == "eval-experiment.v2"
    assert config["retrieval_strategy"] == "pinned"
    assert config["temperature"] == 0.4
    assert config["max_tokens"] == 128
    assert run["input_versions"]["prompt_version"] == "eval-experiment.v2"
    assert run["input_versions"]["case_ids"] == created["case_set_pin"]["case_ids"]
    assert run["output_refs"]
    assert all("raw_response_reference" in item for item in run["output_refs"])
    assert provider.calls == len(run["output_refs"])
    fetched = client.get(f"/experiments/{created['id']}/runs/{run['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["config"] == config


def test_same_config_is_deterministic() -> None:
    client, _, _, _, _ = _client()
    created = _create_experiment(client)
    first = _run(client, created["id"])
    second = _run(client, created["id"])
    assert first["metrics"] == second["metrics"]
    assert first["cost"] == second["cost"]
    assert first["latency_ms"] == second["latency_ms"]
    assert first["config"] == second["config"]


def test_compare_to_baseline_six_metrics() -> None:
    client, _, _, _, _ = _client()
    created = _create_experiment(client)
    baseline = _run(client, created["id"])
    candidate = _run(
        client,
        created["id"],
        prompt_version=INVALID_PROMPT_VERSION,
        model="fake-eval-invalid",
        temperature=0.7,
        max_tokens=64,
    )
    compared = client.post(
        f"/experiments/{created['id']}/runs/{candidate['id']}/compare",
        headers=HUMAN,
        json={"baseline_run_id": baseline["id"], "created_by": "editor-1"},
    )
    assert compared.status_code == 200, compared.text
    body = compared.json()
    names = [item["metric"] for item in body["metrics"]]
    assert names == list(COMPARE_METRICS)
    by_name = body["metrics_by_name"]
    assert by_name["schema_success_rate"]["baseline"] == 1.0
    assert by_name["schema_success_rate"]["candidate"] == 0.0
    assert by_name["first_pass_rate"]["baseline"] == 1.0
    assert by_name["first_pass_rate"]["candidate"] == 0.0
    assert by_name["blocker_error_count"]["delta"] > 0
    assert by_name["token_cost"]["baseline"] != by_name["token_cost"]["candidate"]
    assert "latency_ms" in by_name
    assert body["writes_canon"] is False
    assert body["is_release_gate"] is False
    stored = client.get(f"/experiments/{created['id']}/comparisons/{body['id']}")
    assert stored.status_code == 200
    assert stored.json()["id"] == body["id"]


def test_export_csv_and_json() -> None:
    client, _, _, _, _ = _client()
    created = _create_experiment(client)
    baseline = _run(client, created["id"])
    candidate = _run(client, created["id"], prompt_version=INVALID_PROMPT_VERSION)
    compared = client.post(
        f"/experiments/{created['id']}/runs/{candidate['id']}/compare",
        headers=HUMAN,
        json={"baseline_run_id": baseline["id"]},
    ).json()
    run_json = client.get(
        f"/experiments/{created['id']}/runs/{baseline['id']}/export",
        params={"format": "json"},
    )
    assert run_json.status_code == 200
    assert run_json.headers["content-type"].startswith("application/json")
    payload = run_json.json()
    assert payload["id"] == baseline["id"]
    assert "metrics" in payload
    assert "output_refs" in payload
    run_csv = client.get(
        f"/experiments/{created['id']}/runs/{baseline['id']}/export",
        params={"format": "csv"},
    )
    assert run_csv.status_code == 200
    assert "text/csv" in run_csv.headers["content-type"]
    rows = list(csv.reader(io.StringIO(run_csv.text)))
    assert any(row[:2] == ["metrics", "canon_conflict_count"] for row in rows)
    assert any(row[:2] == ["cost", "total_tokens"] for row in rows)
    cmp_json = client.get(
        f"/experiments/{created['id']}/comparisons/{compared['id']}/export",
        params={"format": "json"},
    )
    assert cmp_json.status_code == 200
    assert [item["metric"] for item in cmp_json.json()["metrics"]] == list(
        COMPARE_METRICS
    )
    cmp_csv = client.get(
        f"/experiments/{created['id']}/comparisons/{compared['id']}/export",
        params={"format": "csv"},
    )
    assert cmp_csv.status_code == 200
    header = next(csv.reader(io.StringIO(cmp_csv.text)))
    assert header == ["metric", "baseline", "candidate", "delta"]


def test_unfrozen_prompt_does_not_overwrite_historical_run() -> None:
    client, _, _, _, _ = _client()
    created = _create_experiment(client)
    historical = _run(client, created["id"])
    patched = client.patch(
        f"/experiments/{created['id']}",
        headers=HUMAN,
        json={"prompt_version": "eval-experiment.unfrozen"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["config"]["prompt_version"] == "eval-experiment.unfrozen"
    reread = client.get(f"/experiments/{created['id']}/runs/{historical['id']}")
    assert reread.status_code == 200
    assert reread.json()["config"]["prompt_version"] == DEFAULT_PROMPT_VERSION
    assert reread.json()["frozen"] is True
    mutate = client.patch(
        f"/experiments/{created['id']}/runs/{historical['id']}",
        headers=HUMAN,
        json={"prompt_version": "eval-experiment.unfrozen"},
    )
    assert mutate.status_code == 409
    assert mutate.json()["detail"]["error"] == "experiment_run_immutable"
    put = client.put(
        f"/experiments/{created['id']}/runs/{historical['id']}",
        headers=HUMAN,
        json={"prompt_version": "eval-experiment.unfrozen"},
    )
    assert put.status_code == 409
    newer = _run(client, created["id"])
    assert newer["id"] != historical["id"]
    assert newer["config"]["prompt_version"] == "eval-experiment.unfrozen"
    listed = client.get(f"/experiments/{created['id']}/runs")
    ids = [item["id"] for item in listed.json()["items"]]
    assert historical["id"] in ids
    assert newer["id"] in ids


def test_does_not_write_canon_or_approve() -> None:
    client, sink, canon, _, _ = _client()
    facts_before = len(canon.facts)
    created = _create_experiment(client)
    run = _run(client, created["id"])
    assert len(canon.facts) == facts_before
    assert run["writes_canon"] is False
    assert run["auto_approved"] is False
    assert run["is_approval"] is False
    assert run["used_real_model"] is False
    for action in ("approve-canon", "submit-canon"):
        for headers in (HUMAN, SYSTEM, GENERATE):
            response = client.post(
                f"/experiments/{created['id']}/{action}",
                headers=headers,
                json={},
            )
            assert response.status_code == 403, response.text
            assert response.json()["detail"]["error"] == (
                "experiment_cannot_write_canon"
            )
    assert len(canon.facts) == facts_before
    assert not any(event.action in {"approve", "submit"} for event in sink.events)


def test_writes_are_audited_and_redacted() -> None:
    client, sink, _, _, _ = _client()
    created = _create_experiment(client)
    run = _run(client, created["id"])
    actions = {event.action for event in sink.events}
    assert "experiment_create" in actions
    assert "experiment_run" in actions
    blob = json.dumps(
        [event.after_json for event in sink.events],
        ensure_ascii=False,
    )
    assert "前日黎明就已站在河滩" not in blob
    assert "旁白提前写出残玉来历" not in blob
    assert "text_evidence" not in blob
    assert "evidence_quote" not in blob
    assert "NOT_JSON_EXPERIMENT" not in blob
    assert created["id"] in blob
    assert run["id"] in blob


def test_failed_and_cancelled_records_are_kept() -> None:
    client, _, _, _, repo = _client()
    created = _create_experiment(client)
    cancelled = client.post(
        f"/experiments/{created['id']}/cancel",
        headers=HUMAN,
        json={},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert repo.get_experiment(created["id"]) is not None
    blocked = client.post(
        f"/experiments/{created['id']}/runs",
        headers=HUMAN,
        json={},
    )
    assert blocked.status_code == 409
    assert repo.get_experiment(created["id"]) is not None
    other = _create_experiment(client, name="kept-after-cancel")
    assert other["id"] in {item.id for item in repo.list_experiments()}


def test_healthz_and_prior_apis_remain() -> None:
    client, _, _, _, _ = _client()
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
    assert "/projects/{project_id}/schedule/config" in paths
    assert "/experiments" in paths
    assert "/experiments/{experiment_id}/runs" in paths
    assert "/experiments/{experiment_id}/runs/{run_id}/compare" in paths
    assert "/experiments/{experiment_id}/runs/{run_id}/export" in paths
    assert "/projects/{project_id}/chapters/generate" not in paths
    assert "/projects/{project_id}/auto-approve" not in paths
    assert "/release-gates" not in paths
    assert "/book-export" not in paths
    assert not any("seed-status" in path for path in paths)
    assert not any("openai" in path for path in paths)


def test_no_production_seed_status() -> None:
    client, _, _, _, _ = _client()
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("seed-status" in path for path in paths)
    route_source = (ROOT / "backend/slove_context/experiments/routes.py").read_text(
        encoding="utf-8"
    )
    assert not any(
        line.lstrip().startswith("@router") and "seed-status" in line
        for line in route_source.splitlines()
    )


def test_9_1_expected_files_unchanged() -> None:
    expected_dir = ROOT / "evals" / "expected"
    assert expected_dir.is_dir()
    files = sorted(expected_dir.rglob("*.json"))
    assert files
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    status = subprocess.run(
        ["git", "diff", "--", "evals/expected", "evals/cases", "evals/fixtures"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert status.returncode == 0
    assert status.stdout == ""
    porcelain = subprocess.run(
        ["git", "status", "--porcelain", "--", "evals/"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert porcelain.stdout == ""
    assert digest.hexdigest()


def test_vector_retrieval_rejected() -> None:
    client, _, _, _, _ = _client()
    response = client.post(
        "/experiments",
        headers=HUMAN,
        json={
            "name": "vector-not-allowed",
            "retrieval_strategy": "vector",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "unsupported_retrieval_strategy"


def test_run_records_cost_latency_and_input_versions() -> None:
    client, _, _, _, _ = _client()
    created = _create_experiment(client)
    run = _run(client, created["id"])
    assert run["status"] == "succeeded"
    assert run["cost"]["prompt_tokens"] > 0
    assert run["cost"]["completion_tokens"] > 0
    assert run["cost"]["total_tokens"] == run["metrics"]["token_cost"]
    assert run["latency_ms"] == run["metrics"]["latency_ms"]
    assert run["duration_ms"] >= 0
    versions = run["input_versions"]
    assert versions["case_set_version"] == "eval-9.1.0"
    assert versions["fixture_hashes"]
    assert versions["expected_hashes"]
    assert versions["snapshot_ids"]
    assert versions["prompt_version"] == DEFAULT_PROMPT_VERSION
    assert "timeline-reversal" in versions["case_ids"]
