"""Walk Fake Provider APIs to seed a local Demo project (node UI.1).

Uses existing 2.1–9.3 routes only. Short fixture prose. Does not
approve / submit extracted Candidate Changes (those stay for the UI).
Not a production seed-status HTTP route.
"""

from __future__ import annotations

from typing import Any

from slove_context.scene_draft.context_pack import STATIC_CONTEXT_PACK_ID

HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}

SPEC = {
    "title": "青石夜祠（Demo）",
    "language": "zh-CN",
    "must_write": ["只写林晚在青石镇的七日"],
    "must_not_write": ["禁止第二主角视角", "禁止真实模型长文"],
    "notes": "Demo 夹具规格，不是 Canon。Fake Provider / 非真实模型。",
    "created_by": "主编",
}

SCENE_BODIES = (
    {
        "story_order": 1,
        "pov": "林晚",
        "story_time": "第一日黄昏",
        "starting_state": "林晚空手走在河滩",
        "goal": "拾得残玉",
        "conflict": "河风与夜色让她几乎错过",
        "expected_end_state": "林晚持有残玉",
        "location": "青石镇河滩",
        "present_entities": ["林晚", "残玉"],
        "generation_boundary": "只写林晚在河滩捡到残玉这一场，不写整章。",
        "forbidden": ["禁止写出残玉来历"],
        "knowledge_boundaries": ["林晚不知残玉能开门"],
        "created_by": "主编",
    },
    {
        "story_order": 2,
        "pov": "林晚",
        "story_time": "第一日入夜",
        "starting_state": "林晚把残玉握在袖中",
        "goal": "找一处过夜的屋檐",
        "conflict": "镇口无人肯借火",
        "expected_end_state": "林晚在河埠廊下过夜",
        "location": "青石镇河埠",
        "present_entities": ["林晚"],
        "generation_boundary": "只写河埠找宿，不写整章。",
        "forbidden": ["禁止写出祠门开启"],
        "knowledge_boundaries": ["林晚仍不知残玉能开门"],
        "created_by": "主编",
    },
    {
        "story_order": 3,
        "pov": "林晚",
        "story_time": "第二日清晨",
        "starting_state": "林晚从廊下醒来",
        "goal": "走到夜祠石阶前",
        "conflict": "雾让石阶若隐若现",
        "expected_end_state": "林晚停在祠阶下",
        "location": "青石镇夜祠台阶",
        "present_entities": ["林晚", "夜祠"],
        "generation_boundary": "只写走到祠阶，不写进门，不写整章。",
        "forbidden": ["禁止写出祠内陈设"],
        "knowledge_boundaries": ["林晚不知祠内有谁"],
        "created_by": "主编",
    },
)


class DemoSeedError(RuntimeError):
    """Raised when a Demo seed HTTP call does not match the expected status."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _json(
    client: Any,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    expected: int,
) -> Any:
    response = client.request(method, path, headers=headers or {}, json=body)
    if response.status_code != expected:
        raise DemoSeedError(
            f"{method} {path} expected {expected}, got {response.status_code}: "
            f"{response.text}",
            status_code=response.status_code,
        )
    if not response.content:
        return {}
    return response.json()


def seed_via_http(client: Any) -> dict[str, Any]:
    """Seed one sample project through existing APIs. Does not submit Canon."""
    existing = _json(client, "GET", "/projects", expected=200)
    items = existing.get("items") or []
    if items:
        project_id = items[0]["id"]
        return _existing_summary(client, project_id)

    project = _json(
        client,
        "POST",
        "/projects",
        headers=HUMAN,
        body={"title": "青石夜祠（Demo）", "language": "zh-CN", "created_by": "主编"},
        expected=201,
    )
    project_id = project["id"]

    spec = _json(
        client,
        "POST",
        f"/projects/{project_id}/specs",
        headers=HUMAN,
        body=SPEC,
        expected=201,
    )
    spec_id = spec["id"]
    _json(
        client,
        "POST",
        f"/projects/{project_id}/specs/{spec_id}/submit",
        headers=HUMAN,
        body={},
        expected=200,
    )
    spec = _json(
        client,
        "POST",
        f"/projects/{project_id}/specs/{spec_id}/approve",
        headers=HUMAN,
        body={},
        expected=200,
    )

    arc = _json(
        client,
        "POST",
        f"/projects/{project_id}/arcs",
        headers=HUMAN,
        body={"title": "七日寻祠", "sort_order": 1, "created_by": "主编"},
        expected=201,
    )
    chapter = _json(
        client,
        "POST",
        f"/projects/{project_id}/chapters",
        headers=HUMAN,
        body={
            "arc_id": arc["id"],
            "title": "得玉",
            "sort_order": 1,
            "created_by": "主编",
        },
        expected=201,
    )

    scenes: list[dict[str, Any]] = []
    for body in SCENE_BODIES:
        payload = dict(body)
        payload["chapter_id"] = chapter["id"]
        scene = _json(
            client,
            "POST",
            f"/projects/{project_id}/scenes",
            headers=HUMAN,
            body=payload,
            expected=201,
        )
        scenes.append(scene)

    _json(
        client,
        "PUT",
        f"/projects/{project_id}/scenes/{scenes[1]['id']}/dependencies",
        headers=HUMAN,
        body={"depends_on": [scenes[0]["id"]], "created_by": "主编"},
        expected=200,
    )
    _json(
        client,
        "PUT",
        f"/projects/{project_id}/scenes/{scenes[2]['id']}/dependencies",
        headers=HUMAN,
        body={"depends_on": [scenes[0]["id"]], "created_by": "主编"},
        expected=200,
    )
    approved_scenes: list[dict[str, Any]] = []
    for scene in scenes:
        approved = _json(
            client,
            "POST",
            f"/projects/{project_id}/scenes/{scene['id']}/approve",
            headers=HUMAN,
            body={},
            expected=200,
        )
        approved_scenes.append(approved)

    entity = _json(
        client,
        "POST",
        f"/projects/{project_id}/entities",
        headers=HUMAN,
        body={"name": "林晚", "entity_type": "角色", "created_by": "主编"},
        expected=201,
    )
    evidence = _json(
        client,
        "POST",
        f"/projects/{project_id}/evidence",
        headers=HUMAN,
        body={
            "source_type": "prose",
            "quote": "FAKE_EVIDENCE：伸手拾起残玉",
            "scene_id": approved_scenes[0]["id"],
            "created_by": "主编",
        },
        expected=201,
    )
    fact = _json(
        client,
        "POST",
        f"/projects/{project_id}/canon-facts",
        headers=HUMAN,
        body={
            "entity_id": entity["id"],
            "predicate": "位于",
            "value_json": {"text": "青石镇"},
            "effective_story_time": "day-01",
            "valid_from_scene_id": approved_scenes[0]["id"],
            "source_type": "editor",
            "evidence_id": evidence["id"],
            "created_by": "主编",
        },
        expected=201,
    )
    fact = _json(
        client,
        "POST",
        f"/projects/{project_id}/canon-facts/{fact['id']}/approve",
        headers=HUMAN,
        body={},
        expected=200,
    )

    snapshot = _json(
        client,
        "POST",
        f"/projects/{project_id}/canon-snapshots",
        headers=HUMAN,
        body={
            "as_of_scene_seq": 1,
            "as_of_story_time": "day-01",
            "note": "Demo 冻结快照",
            "created_by": "主编",
        },
        expected=201,
    )
    snapshot = _json(
        client,
        "POST",
        f"/projects/{project_id}/canon-snapshots/{snapshot['id']}/freeze",
        headers=HUMAN,
        body={},
        expected=200,
    )

    walked = _walk_generate_loop(
        client,
        project_id=project_id,
        scene_id=approved_scenes[0]["id"],
        snapshot_id=snapshot["id"],
        extract=True,
        validate=True,
        review=True,
        summarize=True,
        dag=True,
    )
    _walk_generate_loop(
        client,
        project_id=project_id,
        scene_id=approved_scenes[2]["id"],
        snapshot_id=snapshot["id"],
        extract=False,
        validate=False,
        review=False,
        summarize=False,
        dag=False,
    )

    release = _json(
        client,
        "POST",
        f"/projects/{project_id}/release-checks",
        headers=HUMAN,
        body={
            "snapshot_id": snapshot["id"],
            "scene_ids": [item["id"] for item in approved_scenes],
            "chapter_ids": [chapter["id"]],
            "created_by": "主编",
        },
        expected=201,
    )

    return {
        "demo": True,
        "provider": "fake",
        "real_model": False,
        "writes_canon": False,
        "auto_approved": False,
        "auto_submitted": False,
        "project_id": project_id,
        "spec_id": spec["id"],
        "chapter_id": chapter["id"],
        "scene_ids": [item["id"] for item in approved_scenes],
        "snapshot_id": snapshot["id"],
        "entity_id": entity["id"],
        "fact_id": fact["id"],
        "walked_scene_id": approved_scenes[0]["id"],
        "draft_id": walked.get("draft_id"),
        "candidate_id": walked.get("candidate_id"),
        "validation_run_id": walked.get("validation_run_id"),
        "review_item_id": walked.get("review_item_id"),
        "dag_id": walked.get("dag_id"),
        "release_check_id": release["id"],
        "release_passed": bool(release.get("passed")),
        "banner": "Demo / Fake Provider / 非真实模型",
    }


def _walk_generate_loop(
    client: Any,
    *,
    project_id: str,
    scene_id: str,
    snapshot_id: str,
    extract: bool,
    validate: bool,
    review: bool,
    summarize: bool,
    dag: bool,
) -> dict[str, Any]:
    _json(
        client,
        "POST",
        f"/projects/{project_id}/scenes/{scene_id}/plans/jobs",
        headers=GENERATE,
        body={"snapshot_id": snapshot_id},
        expected=201,
    )
    plan = _json(
        client,
        "GET",
        f"/projects/{project_id}/scenes/{scene_id}/plans/current",
        expected=200,
    )
    plan_id = plan["plan"]["id"]
    draft_job = _json(
        client,
        "POST",
        f"/projects/{project_id}/scenes/{scene_id}/drafts/jobs",
        headers=GENERATE,
        body={
            "snapshot_id": snapshot_id,
            "plan_id": plan_id,
            "context_pack_id": STATIC_CONTEXT_PACK_ID,
        },
        expected=201,
    )
    draft_id = draft_job["draft_id"]
    result: dict[str, Any] = {"plan_id": plan_id, "draft_id": draft_id}
    if not extract:
        return result

    _json(
        client,
        "POST",
        f"/projects/{project_id}/scenes/{scene_id}/drafts/{draft_id}/extract-jobs",
        headers=GENERATE,
        body={},
        expected=201,
    )
    listed = _json(
        client,
        "GET",
        f"/projects/{project_id}/scenes/{scene_id}/candidate-changes",
        expected=200,
    )
    candidates = listed.get("items") or []
    if not candidates:
        raise DemoSeedError("extract produced no candidate changes")
    candidate_id = candidates[0]["id"]
    result["candidate_id"] = candidate_id

    if validate:
        run = _json(
            client,
            "POST",
            f"/projects/{project_id}/validation-runs",
            headers=HUMAN,
            body={
                "scene_id": scene_id,
                "candidate_ids": [candidate_id],
                "snapshot_id": snapshot_id,
                "created_by": "主编",
            },
            expected=201,
        )
        result["validation_run_id"] = run["id"]

    if review:
        item = _json(
            client,
            "POST",
            f"/projects/{project_id}/review-queue/items",
            headers=HUMAN,
            body={
                "subject_type": "candidate_change",
                "subject_id": candidate_id,
                "created_by": "主编",
            },
            expected=201,
        )
        result["review_item_id"] = item["id"]

    if summarize:
        draft = _json(
            client,
            "GET",
            f"/projects/{project_id}/scenes/{scene_id}/drafts/{draft_id}",
            expected=200,
        )
        _json(
            client,
            "POST",
            f"/projects/{project_id}/scenes/{scene_id}/summaries/jobs",
            headers=GENERATE,
            body={
                "draft_revision_id": draft_id,
                "content_hash": draft["content_hash"],
            },
            expected=201,
        )

    if dag:
        created = _json(
            client,
            "POST",
            f"/projects/{project_id}/scenes/{scene_id}/dags",
            headers=HUMAN,
            body={"snapshot_id": snapshot_id, "created_by": "主编"},
            expected=201,
        )
        result["dag_id"] = created["id"]
    return result


def _existing_summary(client: Any, project_id: str) -> dict[str, Any]:
    spec = _json(client, "GET", f"/projects/{project_id}/specs/current", expected=200)
    scenes = _json(client, "GET", f"/projects/{project_id}/scenes", expected=200)
    snapshots = _json(
        client, "GET", f"/projects/{project_id}/canon-snapshots", expected=200
    )
    return {
        "demo": True,
        "already_seeded": True,
        "provider": "fake",
        "real_model": False,
        "writes_canon": False,
        "auto_approved": False,
        "auto_submitted": False,
        "project_id": project_id,
        "spec_id": spec.get("id"),
        "scene_ids": [item["id"] for item in scenes.get("scenes") or []],
        "snapshot_id": (snapshots.get("items") or [{}])[0].get("id"),
        "banner": "Demo / Fake Provider / 非真实模型",
    }


def seed_demo(application: Any) -> dict[str, Any]:
    """Seed an in-process FastAPI app. Used by the CLI and tests."""
    from fastapi.testclient import TestClient

    with TestClient(application) as client:
        return seed_via_http(client)
