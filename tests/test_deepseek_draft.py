"""Node UI.4 DeepSeek Scene Draft trigger.

Mocked HTTP only. No live Postgres. No socket to api.deepseek.com.
Does not write Canon. Does not auto-approve. Shuttle stays usable.
"""

from __future__ import annotations

import json
import socket
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from slove_context.app import create_app
from slove_context.audit import REDACTED, AuditWriter, InMemoryAuditSink
from slove_context.canon.repository import InMemoryCanonRepository
from slove_context.llm.deepseek import (
    DEEPSEEK_API_KEY_ENV,
    DEEPSEEK_CHAT_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_PROVIDER_NAME,
    DeepSeekHttpResult,
    DeepSeekProvider,
    deepseek_api_key_configured,
)
from slove_context.llm.errors import (
    MissingApiKeyError,
    ProviderHttpError,
    ProviderTimeoutError,
)
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway, RetryPolicy
from slove_context.llm.redact import redact_llm
from slove_context.llm.types import GenerateRequest
from slove_context.scene.repository import InMemorySceneRepository
from slove_context.scene_draft.context_pack import STATIC_CONTEXT_PACK_ID
from slove_context.scene_draft.repository import InMemorySceneDraftRepository
from slove_context.scene_plan.repository import InMemoryScenePlanRepository
from slove_context.story.repository import InMemoryStoryRepository

HUMAN = {"X-Actor-Type": "human_editor", "X-Actor-Id": "editor-1"}
GENERATE = {"X-Actor-Type": "generation_agent", "X-Actor-Id": "gen-1"}
PLACEHOLDER_KEY = "test-placeholder-not-a-real-key"
DEEPSEEK_PROSE = (
    "河滩风冷，林晚看见一点光，伸手拾起残玉。她把玉握在掌心，没有追问来历。"
)
SHUTTLE_PROSE = (
    "河滩风冷，林晚看见一点光，伸手拾起残玉。"
    "她把玉握在掌心，没有追问来历，只记住这一夜的潮声。"
    "风从芦苇里穿过，她把残玉收进袖中，继续沿河走下去。"
)
SHUTTLE_SCENE_SUMMARY = (
    "林晚在河滩拾得残玉，未追问来历，只把潮声、夜风和掌心的凉意记在心里。"
    "这场只记她得玉，不写来历，也不写成整章。"
)


@pytest.fixture(autouse=True)
def _never_open_deepseek_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = socket.create_connection

    def guarded(address: Any, *args: Any, **kwargs: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if "deepseek" in str(host).lower():
            raise AssertionError("never open a real socket to api.deepseek.com")
        return real_connect(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded)


def _success_http_post() -> Any:
    calls: list[dict[str, Any]] = []

    def http_post(
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_s: float,
    ) -> DeepSeekHttpResult:
        calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload),
                "timeout_s": timeout_s,
            }
        )
        assert url == DEEPSEEK_CHAT_URL
        assert payload["model"] == DEEPSEEK_MODEL
        assert payload["thinking"] == {"type": "disabled"}
        return DeepSeekHttpResult(
            status_code=200,
            payload={
                "id": "chatcmpl-ui4-test",
                "choices": [{"message": {"content": DEEPSEEK_PROSE}}],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 24,
                    "total_tokens": 36,
                },
            },
        )

    http_post.calls = calls  # type: ignore[attr-defined]
    return http_post


def _status_http_post(status_code: int) -> Any:
    def http_post(
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_s: float,
    ) -> DeepSeekHttpResult:
        return DeepSeekHttpResult(status_code=status_code, payload={"error": "mocked"})

    return http_post


def _timeout_http_post() -> Any:
    def http_post(
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_s: float,
    ) -> DeepSeekHttpResult:
        raise ProviderTimeoutError("mocked DeepSeek timeout")

    return http_post


def _client(
    *,
    http_post: Any | None,
    auto_run: bool = True,
) -> tuple[TestClient, InMemoryAuditSink, InMemoryCanonRepository, Any]:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    canon = InMemoryCanonRepository()
    fake = FakeProvider()
    deepseek = DeepSeekProvider(http_post=http_post)
    app = create_app(
        repository=InMemoryStoryRepository(),
        canon_repository=canon,
        scene_repository=InMemorySceneRepository(),
        scene_plan_repository=InMemoryScenePlanRepository(),
        scene_draft_repository=InMemorySceneDraftRepository(),
        audit_writer=writer,
        llm_gateway=LlmGateway(
            fake,
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
        scene_draft_llm_gateway=LlmGateway(
            deepseek,
            policy=RetryPolicy(max_retries=0, timeout_s=2.0),
            audit_writer=writer,
            sleep=lambda _: None,
        ),
        scene_draft_auto_run=auto_run,
    )
    return TestClient(app), sink, canon, http_post


def _create_project(client: TestClient) -> dict:
    response = client.post(
        "/projects",
        headers=HUMAN,
        json={"title": "青石夜祠", "language": "zh-CN", "created_by": "主编"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_chapter(client: TestClient, project_id: str) -> dict:
    arc = client.post(
        f"/projects/{project_id}/arcs",
        headers=HUMAN,
        json={"title": "七日寻祠", "sort_order": 1, "created_by": "主编"},
    )
    assert arc.status_code == 201, arc.text
    chapter = client.post(
        f"/projects/{project_id}/chapters",
        headers=HUMAN,
        json={
            "arc_id": arc.json()["id"],
            "title": "得玉",
            "sort_order": 1,
            "created_by": "主编",
        },
    )
    assert chapter.status_code == 201, chapter.text
    return chapter.json()


def _scene_payload(chapter_id: str, story_order: int) -> dict:
    return {
        "chapter_id": chapter_id,
        "story_order": story_order,
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
    }


def _ready(client: TestClient) -> tuple[dict, dict, dict, dict]:
    project = _create_project(client)
    chapter = _create_chapter(client, project["id"])
    scene = client.post(
        f"/projects/{project['id']}/scenes",
        headers=HUMAN,
        json=_scene_payload(chapter["id"], 1),
    )
    assert scene.status_code == 201, scene.text
    approved = client.post(
        f"/projects/{project['id']}/scenes/{scene.json()['id']}/approve",
        headers=HUMAN,
        json={},
    )
    assert approved.status_code == 200, approved.text
    snapshot = client.post(
        f"/projects/{project['id']}/canon-snapshots",
        headers=HUMAN,
        json={
            "as_of_scene_seq": 1,
            "as_of_story_time": "day-01",
            "created_by": "主编",
        },
    )
    assert snapshot.status_code == 201, snapshot.text
    plan_job = client.post(
        f"/projects/{project['id']}/scenes/{approved.json()['id']}/plans/jobs",
        headers=GENERATE,
        json={"snapshot_id": snapshot.json()["id"]},
    )
    assert plan_job.status_code == 201, plan_job.text
    current = client.get(
        f"/projects/{project['id']}/scenes/{approved.json()['id']}/plans/current"
    )
    assert current.status_code == 200, current.text
    return project, approved.json(), snapshot.json(), current.json()["plan"]


def _trigger_body(snapshot_id: str, plan_id: str, **overrides: object) -> dict:
    payload: dict = {
        "snapshot_id": snapshot_id,
        "plan_id": plan_id,
        "context_pack_id": STATIC_CONTEXT_PACK_ID,
        "provider": DEEPSEEK_PROVIDER_NAME,
    }
    payload.update(overrides)
    return payload


def test_deepseek_constants_are_official_cheap_chat() -> None:
    assert DEEPSEEK_MODEL == "deepseek-v4-flash"
    assert DEEPSEEK_PROVIDER_NAME == "deepseek"
    assert DEEPSEEK_CHAT_URL == "https://api.deepseek.com/chat/completions"
    assert DEEPSEEK_API_KEY_ENV == "DEEPSEEK_API_KEY"
    assert DEEPSEEK_MODEL not in {
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v4-pro",
    }


def test_missing_key_refuses_without_http_or_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DEEPSEEK_API_KEY_ENV, raising=False)
    http_post = _success_http_post()
    client, _, canon, _ = _client(http_post=http_post)
    project, scene, snapshot, plan = _ready(client)
    facts_before = len(canon.facts)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=HUMAN,
        json=_trigger_body(snapshot["id"], plan["id"]),
    )
    assert created.status_code == 503, created.text
    detail = created.json()["detail"]
    assert detail["error"] == "deepseek_api_key_missing"
    assert detail["writes_canon"] is False
    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/drafts")
    assert listed.json()["items"] == []
    assert http_post.calls == []
    assert len(canon.facts) == facts_before
    assert not deepseek_api_key_configured()


def test_empty_key_refuses_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, "   ")
    http_post = _success_http_post()
    client, _, canon, _ = _client(http_post=http_post)
    project, scene, snapshot, plan = _ready(client)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=HUMAN,
        json=_trigger_body(snapshot["id"], plan["id"]),
    )
    assert created.status_code == 503
    assert created.json()["detail"]["error"] == "deepseek_api_key_missing"
    assert http_post.calls == []
    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/drafts")
    assert listed.json()["items"] == []
    assert len(canon.facts) == 0


def test_mocked_success_persists_deepseek_draft_not_fake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, PLACEHOLDER_KEY)
    http_post = _success_http_post()
    client, sink, canon, _ = _client(http_post=http_post)
    project, scene, snapshot, plan = _ready(client)
    facts_before = len(canon.facts)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=HUMAN,
        json=_trigger_body(snapshot["id"], plan["id"]),
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "succeeded"
    assert job["writes_canon"] is False
    assert job["auto_approved"] is False
    assert job["is_canon"] is False
    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/drafts")
    items = listed.json()["items"]
    assert len(items) == 1
    draft = items[0]
    assert draft["status"] == "Generated"
    assert draft["body"] == DEEPSEEK_PROSE
    assert draft["generation_model"] == DEEPSEEK_MODEL
    assert draft["generation_model"] != "fake-model"
    assert draft["generation_model"] != "fake"
    assert draft["generation_model"] != "external-subscribed"
    assert draft["is_canon"] is False
    assert draft["auto_approved"] is False
    one = client.get(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/{draft['id']}"
    )
    assert one.status_code == 200
    assert one.json()["generation_model"] == DEEPSEEK_MODEL
    assert len(http_post.calls) == 1
    sent = http_post.calls[0]
    assert sent["payload"]["model"] == DEEPSEEK_MODEL
    assert sent["payload"]["thinking"] == {"type": "disabled"}
    assert PLACEHOLDER_KEY not in json.dumps(job)
    assert PLACEHOLDER_KEY not in json.dumps(draft)
    dumped = "".join(
        str(event.after_json) + str(event.before_json) for event in sink.events
    )
    assert PLACEHOLDER_KEY not in dumped
    assert "Bearer " not in dumped
    assert DEEPSEEK_PROSE not in dumped
    assert len(canon.facts) == facts_before
    redacted = redact_llm(
        {
            "Authorization": f"Bearer {PLACEHOLDER_KEY}",
            "DEEPSEEK_API_KEY": PLACEHOLDER_KEY,
            "headers": {"authorization": f"Bearer {PLACEHOLDER_KEY}"},
        }
    )
    assert redacted["Authorization"] == REDACTED
    assert redacted["DEEPSEEK_API_KEY"] == REDACTED
    assert redacted["headers"]["authorization"] == REDACTED


@pytest.mark.parametrize("status_code", [400, 401, 429, 500, 503])
def test_mocked_http_error_fails_job_without_canon(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, PLACEHOLDER_KEY)
    client, _, canon, _ = _client(http_post=_status_http_post(status_code))
    project, scene, snapshot, plan = _ready(client)
    facts_before = len(canon.facts)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=HUMAN,
        json=_trigger_body(snapshot["id"], plan["id"]),
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["state"] == "failed"
    assert job["draft_id"] is None
    assert job["writes_canon"] is False
    assert job["failure_reason"]
    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/drafts")
    assert listed.json()["items"] == []
    assert len(canon.facts) == facts_before


def test_mocked_timeout_fails_job_without_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, PLACEHOLDER_KEY)
    client, _, canon, _ = _client(http_post=_timeout_http_post())
    project, scene, snapshot, plan = _ready(client)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=HUMAN,
        json=_trigger_body(snapshot["id"], plan["id"]),
    )
    assert created.status_code == 201, created.text
    assert created.json()["state"] == "failed"
    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/drafts")
    assert listed.json()["items"] == []
    assert len(canon.facts) == 0


def test_shuttle_ui2_and_ui3_still_work_without_deepseek_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, PLACEHOLDER_KEY)
    http_post = _success_http_post()
    client, _, canon, _ = _client(http_post=http_post)
    project, scene, snapshot, plan = _ready(client)
    facts_before = len(canon.facts)

    pasted = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/shuttle/drafts",
        headers=HUMAN,
        json={
            "body": SHUTTLE_PROSE,
            "snapshot_id": snapshot["id"],
            "plan_id": plan["id"],
        },
    )
    assert pasted.status_code == 201, pasted.text
    draft = pasted.json()["draft"]
    assert draft["generation_model"] == "external-subscribed"
    assert draft["status"] == "Generated"
    assert http_post.calls == []

    summary = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/shuttle/summaries",
        headers=HUMAN,
        json={"draft_revision_id": draft["id"], "body": SHUTTLE_SCENE_SUMMARY},
    )
    assert summary.status_code == 201, summary.text
    assert summary.json()["summary"]["generation_model"] == "external-subscribed"
    assert summary.json()["writes_canon"] is False
    assert http_post.calls == []
    assert len(canon.facts) == facts_before


def test_fake_draft_job_without_provider_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, PLACEHOLDER_KEY)
    http_post = _success_http_post()
    client, _, _, _ = _client(http_post=http_post)
    project, scene, snapshot, plan = _ready(client)
    created = client.post(
        f"/projects/{project['id']}/scenes/{scene['id']}/drafts/jobs",
        headers=GENERATE,
        json={
            "snapshot_id": snapshot["id"],
            "plan_id": plan["id"],
            "context_pack_id": STATIC_CONTEXT_PACK_ID,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["state"] == "succeeded"
    listed = client.get(f"/projects/{project['id']}/scenes/{scene['id']}/drafts")
    draft = listed.json()["items"][0]
    assert draft["generation_model"] == "fake-model"
    assert http_post.calls == []


def test_provider_generate_text_mocked_and_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DEEPSEEK_API_KEY_ENV, raising=False)
    provider = DeepSeekProvider(http_post=_success_http_post())
    request = GenerateRequest(
        model=DEEPSEEK_MODEL,
        system_prompt="sys",
        user_prompt="user",
        temperature=0.4,
        max_tokens=64,
        correlation_id="corr-ui4",
        task_type="scene_draft",
        prompt_version="scene_draft.v1",
    )
    with pytest.raises(MissingApiKeyError):
        provider.generate_text(request)

    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, PLACEHOLDER_KEY)
    http_post = _success_http_post()
    provider = DeepSeekProvider(http_post=http_post)
    response = provider.generate_text(request)
    assert response.provider == DEEPSEEK_PROVIDER_NAME
    assert response.model == DEEPSEEK_MODEL
    assert response.parsed_output == DEEPSEEK_PROSE
    assert response.error is None
    assert PLACEHOLDER_KEY not in json.dumps(response.to_dict())


def test_provider_http_error_is_machine_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, PLACEHOLDER_KEY)
    provider = DeepSeekProvider(http_post=_status_http_post(502))
    request = GenerateRequest(
        model="ignored-retired-name",
        system_prompt="sys",
        user_prompt="user",
        temperature=0.0,
        max_tokens=32,
        correlation_id="corr-ui4-err",
        task_type="scene_draft",
    )
    with pytest.raises(ProviderHttpError) as exc:
        provider.generate_text(request)
    assert exc.value.status_code == 502
    assert PLACEHOLDER_KEY not in str(exc.value)


def test_httpx_mock_transport_never_uses_real_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, PLACEHOLDER_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.deepseek.com"
        body = json.loads(request.content)
        assert body["model"] == DEEPSEEK_MODEL
        assert body["thinking"] == {"type": "disabled"}
        auth = request.headers.get("Authorization", "")
        assert auth.startswith("Bearer ")
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-mock-transport",
                "choices": [{"message": {"content": DEEPSEEK_PROSE}}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)

    def http_post(
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_s: float,
    ) -> DeepSeekHttpResult:
        response = http_client.post(
            url, headers=headers, json=payload, timeout=timeout_s
        )
        loaded = response.json()
        return DeepSeekHttpResult(
            status_code=response.status_code,
            payload=loaded if isinstance(loaded, dict) else None,
        )

    provider = DeepSeekProvider(http_post=http_post)
    response = provider.generate_text(
        GenerateRequest(
            model=DEEPSEEK_MODEL,
            system_prompt="sys",
            user_prompt="user",
            temperature=0.1,
            max_tokens=32,
            correlation_id="corr-mock-transport",
            task_type="scene_draft",
        )
    )
    assert response.model == DEEPSEEK_MODEL
    assert response.parsed_output == DEEPSEEK_PROSE
    http_client.close()
