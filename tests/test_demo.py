"""Local workflow Demo seeder and CORS (node UI.1).

In-memory repositories. No live Postgres. No network. No real models.
CLI seeder only — no production seed-status HTTP route.
Approve is not exercised here; the seeder must not submit Canon.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.cors import cors_origins_for_env
from slove_context.demo.seed import seed_demo

ROOT = Path(__file__).resolve().parents[1]
HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}


def test_cors_development_allows_vite_origin() -> None:
    origins = cors_origins_for_env(env="development", configured=None)
    assert "http://localhost:5173" in origins
    assert "*" not in origins
    app = create_app(cors_origins=origins)
    client = TestClient(app)
    response = client.options(
        "/healthz",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == (
        "http://localhost:5173"
    )


def test_cors_production_does_not_open_star() -> None:
    origins = cors_origins_for_env(env="production", configured="*")
    assert origins == []
    origins = cors_origins_for_env(env="production", configured=None)
    assert origins == []
    app = create_app(cors_origins=[])
    client = TestClient(app)
    response = client.options(
        "/healthz",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") in {None, ""}


def test_no_production_seed_status_route() -> None:
    client = TestClient(create_app())
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("seed-status" in path for path in paths)
    assert "/projects" in paths
    assert "get" in paths["/projects"]
    routes = Path(ROOT / "backend/slove_context").read_text() if False else ""
    del routes
    for path in Path(ROOT / "backend/slove_context").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.lstrip().startswith("@router") and "seed-status" in line:
                raise AssertionError(f"seed-status route in {path}")


def test_demo_seed_walks_fake_provider_and_does_not_submit() -> None:
    app = create_app()
    result = seed_demo(app)
    assert result["demo"] is True
    assert result["real_model"] is False
    assert result["auto_approved"] is False
    assert result["auto_submitted"] is False
    assert result["writes_canon"] is False
    project_id = result["project_id"]
    client = TestClient(app)

    listed = client.get("/projects")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == project_id

    spec = client.get(f"/projects/{project_id}/specs/current")
    assert spec.status_code == 200
    assert spec.json()["status"] in {"Effective", "Written"}

    scenes = client.get(f"/projects/{project_id}/scenes")
    assert scenes.status_code == 200
    scene_items = scenes.json()["scenes"]
    assert len(scene_items) == 3

    snapshots = client.get(f"/projects/{project_id}/canon-snapshots")
    assert snapshots.status_code == 200
    assert snapshots.json()["items"]
    assert snapshots.json()["items"][0]["status"] == "frozen"

    facts = client.get(f"/projects/{project_id}/canon-facts")
    assert facts.status_code == 200
    assert facts.json()["facts"]

    walked = result["walked_scene_id"]
    drafts = client.get(f"/projects/{project_id}/scenes/{walked}/drafts")
    assert drafts.status_code == 200
    draft_items = drafts.json()["items"]
    assert draft_items
    assert "FAKE_SCENE_DRAFT_PROSE" in draft_items[0]["body"]

    candidates = client.get(f"/projects/{project_id}/scenes/{walked}/candidate-changes")
    assert candidates.status_code == 200
    cand_items = candidates.json()["items"]
    assert cand_items
    assert cand_items[0]["status"] == "AwaitingVerdict"
    assert cand_items[0]["is_canon"] is False

    runs = client.get(f"/projects/{project_id}/validation-runs")
    assert runs.status_code == 200
    assert runs.json()["items"]

    queue = client.get(f"/projects/{project_id}/review-queue")
    assert queue.status_code == 200
    assert queue.json()["items"]

    dags = client.get(f"/projects/{project_id}/scenes/{walked}/dags")
    assert dags.status_code == 200
    assert dags.json()["items"]

    checks = client.get(f"/projects/{project_id}/release-checks")
    assert checks.status_code == 200
    assert checks.json()["items"]
    check = checks.json()["items"][0]
    assert "gates" in check
    assert len(check["gates"]) == 8
    if not check.get("passed"):
        assert check["failures"]

    # Seeder must leave submit to the human 主编.
    assert cand_items[0]["status"] != "Submitted"
    before = len(facts.json()["facts"])
    facts_after = client.get(f"/projects/{project_id}/canon-facts")
    assert len(facts_after.json()["facts"]) == before


def test_demo_seed_is_idempotent_on_existing_project() -> None:
    app = create_app()
    first = seed_demo(app)
    second = seed_demo(app)
    assert second.get("already_seeded") is True
    assert second["project_id"] == first["project_id"]


def test_healthz_and_existing_apis_remain() -> None:
    client = TestClient(create_app())
    assert client.get("/healthz").json() == {"status": "ok"}
    paths = client.get("/openapi.json").json()["paths"]
    assert "/version" in paths
    assert "/projects/{project_id}/review-queue/{item_id}/approve" in paths
    assert "/projects/{project_id}/candidate-changes/{candidate_id}/submit" in paths
    assert "/projects/{project_id}/release-checks" in paths
