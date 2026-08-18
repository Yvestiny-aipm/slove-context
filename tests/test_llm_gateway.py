"""LLM Gateway + Fake Provider (node 3.2).

In-process fixtures only. No live Postgres. No network. No vendor HTTP.
No Scene Plan / Scene Draft generation job.
"""

from __future__ import annotations

import inspect
import io
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from slove_context.app import app
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.llm.errors import (
    NonIdempotentRetryError,
    ProviderTimeoutError,
    ProviderTransientError,
    RetriesExhaustedError,
)
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import (
    IDEMPOTENT_GENERATE_OPS,
    LlmGateway,
    RetryPolicy,
    backoff_delay_s,
)
from slove_context.llm.provider import Provider
from slove_context.llm.redact import redact_llm
from slove_context.llm.types import (
    REQUEST_REQUIRED_FIELDS,
    RESPONSE_REQUIRED_FIELDS,
    USAGE_COST_FIELDS,
    USAGE_TOKEN_FIELDS,
    GenerateRequest,
    GenerateResponse,
    Usage,
    request_field_names,
    response_field_names,
)
from slove_context.logging import JsonFormatter

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "backend" / "slove_context" / "llm"
PROMPT_MARK = "UNIQUE_PROMPT_BODY_DO_NOT_LOG"
PROSE_MARK = "UNIQUE_PROSE_BODY_DO_NOT_LOG"

client = TestClient(app)


def _request(**overrides: object) -> GenerateRequest:
    payload = {
        "model": "fake-model",
        "system_prompt": PROMPT_MARK,
        "user_prompt": "fixture user prompt",
        "temperature": 0.0,
        "max_tokens": 32,
        "correlation_id": "corr-llm-1",
        "task_type": "text",
    }
    payload.update(overrides)
    return GenerateRequest(**payload)  # type: ignore[arg-type]


def _ok_response() -> GenerateResponse:
    return GenerateResponse(
        request_id="provider-req",
        provider="scripted",
        model="fake-model",
        prompt_version="fake-v1",
        usage=Usage(1, 1, 2, 0.0, "USD"),
        latency_ms=0.0,
        raw_response_reference="scripted:ok",
        parsed_output="FAKE_TEXT_FIXTURE",
        error=None,
    )


class ScriptedProvider(Provider):
    """Test double: queued outcomes. No HTTP."""

    name = "scripted"

    def __init__(self, outcomes: list[GenerateResponse | BaseException]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def generate_text(self, request: GenerateRequest) -> GenerateResponse:
        return self._next()

    def generate_structured(self, request: GenerateRequest) -> GenerateResponse:
        return self._next()

    def _next(self) -> GenerateResponse:
        self.calls += 1
        if not self.outcomes:
            raise ProviderTransientError("scripted provider exhausted")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class SleepingProvider(Provider):
    name = "sleeping"

    def __init__(self, sleep_s: float) -> None:
        self.sleep_s = sleep_s
        self.calls = 0

    def generate_text(self, request: GenerateRequest) -> GenerateResponse:
        import time

        self.calls += 1
        time.sleep(self.sleep_s)
        return _ok_response()

    def generate_structured(self, request: GenerateRequest) -> GenerateResponse:
        return self.generate_text(request)


def _gateway(
    provider: Provider,
    *,
    policy: RetryPolicy | None = None,
    sink: InMemoryAuditSink | None = None,
    sleeps: list[float] | None = None,
) -> LlmGateway:
    writer = AuditWriter(sink) if sink is not None else None
    sleep = sleeps.append if sleeps is not None else (lambda _: None)
    return LlmGateway(provider, policy=policy, audit_writer=writer, sleep=sleep)


def test_provider_interface_has_generate_text_and_generate_structured() -> None:
    assert inspect.isabstract(Provider)
    assert hasattr(Provider, "generate_text")
    assert hasattr(Provider, "generate_structured")
    assert "generate_text" in Provider.__abstractmethods__
    assert "generate_structured" in Provider.__abstractmethods__
    assert "generate_text" in IDEMPOTENT_GENERATE_OPS
    assert "generate_structured" in IDEMPOTENT_GENERATE_OPS


def test_request_and_response_required_fields() -> None:
    for name in REQUEST_REQUIRED_FIELDS:
        assert name in request_field_names()
    for name in RESPONSE_REQUIRED_FIELDS:
        assert name in response_field_names()
    usage_fields = Usage.__dataclass_fields__
    for name in USAGE_TOKEN_FIELDS + USAGE_COST_FIELDS:
        assert name in usage_fields


def test_fake_generate_text_returns_fixture_fields() -> None:
    gateway = _gateway(FakeProvider())
    response = gateway.generate_text(_request())

    assert response.provider == "fake"
    assert response.model == "fake-model"
    assert response.prompt_version == "fake-v1"
    assert response.parsed_output == "FAKE_TEXT_FIXTURE"
    assert response.error is None
    assert response.request_id
    assert response.raw_response_reference.startswith("fake:text_ok.json:")
    assert "{" not in response.raw_response_reference or "FAKE_TEXT" not in (
        response.raw_response_reference
    )
    assert response.usage.prompt_tokens == 10
    assert response.usage.completion_tokens == 4
    assert response.usage.total_tokens == 14
    assert response.usage.cost_amount == 0.0
    assert response.usage.cost_currency == "USD"
    assert response.latency_ms >= 0


def test_fake_generate_structured_parses_fixture() -> None:
    gateway = _gateway(FakeProvider())
    response = gateway.generate_structured(_request(task_type="structured_ok"))

    assert response.error is None
    assert response.parsed_output == {"fixture": "structured_ok", "ok": True}
    assert response.usage.total_tokens == 14
    assert response.raw_response_reference.startswith("fake:structured_ok.json:")


def test_structured_parse_failure_is_not_retried() -> None:
    gateway = _gateway(
        FakeProvider(),
        policy=RetryPolicy(max_retries=3, timeout_s=1.0),
        sleeps=[],
    )
    response = gateway.generate_structured(_request(task_type="structured_invalid"))

    assert response.error is not None
    assert response.error.code == "structured_parse_failed"
    assert response.parsed_output is None


def test_timeout_raises_and_is_retryable_until_exhausted() -> None:
    provider = SleepingProvider(sleep_s=0.2)
    sleeps: list[float] = []
    gateway = _gateway(
        provider,
        policy=RetryPolicy(timeout_s=0.05, max_retries=1, backoff_base_s=0.01),
        sleeps=sleeps,
    )
    with pytest.raises(RetriesExhaustedError) as exc_info:
        gateway.generate_text(_request())
    assert isinstance(exc_info.value.__cause__, ProviderTimeoutError)
    assert provider.calls == 2
    assert sleeps == [0.01]


def test_retries_then_success_uses_exponential_backoff() -> None:
    sleeps: list[float] = []
    provider = ScriptedProvider(
        [
            ProviderTransientError("flaky-1"),
            ProviderTransientError("flaky-2"),
            _ok_response(),
        ]
    )
    policy = RetryPolicy(
        timeout_s=1.0,
        max_retries=2,
        backoff_base_s=0.1,
        backoff_multiplier=2.0,
    )
    gateway = _gateway(provider, policy=policy, sleeps=sleeps)
    response = gateway.generate_text(_request())

    assert response.parsed_output == "FAKE_TEXT_FIXTURE"
    assert provider.calls == 3
    assert sleeps == [
        backoff_delay_s(1, policy),
        backoff_delay_s(2, policy),
    ]
    assert sleeps == [0.1, 0.2]


def test_retries_exhausted_on_transient_errors() -> None:
    provider = ScriptedProvider(
        [
            ProviderTransientError("a"),
            ProviderTransientError("b"),
            ProviderTransientError("c"),
        ]
    )
    sleeps: list[float] = []
    gateway = _gateway(
        provider,
        policy=RetryPolicy(timeout_s=1.0, max_retries=2, backoff_base_s=0.05),
        sleeps=sleeps,
    )
    with pytest.raises(RetriesExhaustedError):
        gateway.generate_text(_request())
    assert provider.calls == 3
    assert len(sleeps) == 2


def test_write_side_effect_is_not_retried() -> None:
    calls = {"n": 0}

    def persist() -> None:
        calls["n"] += 1
        raise ProviderTransientError("already wrote audit+state")

    gateway = _gateway(FakeProvider(), policy=RetryPolicy(max_retries=5))
    with pytest.raises(ProviderTransientError):
        gateway.invoke_once("persist_generation_state", persist)
    assert calls["n"] == 1


def test_run_generate_refuses_write_operation_name() -> None:
    gateway = _gateway(FakeProvider())
    with pytest.raises(NonIdempotentRetryError):
        gateway._run_generate("canon_write", FakeProvider().generate_text, _request())


def test_audit_written_once_after_retries_and_redacts_prompt() -> None:
    sink = InMemoryAuditSink()
    provider = ScriptedProvider([ProviderTransientError("once"), _ok_response()])
    gateway = _gateway(
        provider,
        policy=RetryPolicy(timeout_s=1.0, max_retries=2),
        sink=sink,
        sleeps=[],
    )
    gateway.generate_text(_request())

    assert len(sink.events) == 1
    after = sink.events[0].after_json
    assert after is not None
    dumped = json.dumps(after, ensure_ascii=False)
    assert PROMPT_MARK not in dumped
    assert "fixture user prompt" not in dumped
    assert after["system_prompt"]["redacted"] is True
    assert after["system_prompt"]["ref"].startswith("prompt:")
    assert after["usage"]["prompt_tokens"] == 1
    assert after["prompt_version"] == "fake-v1"
    assert after["raw_response_reference"] == "scripted:ok"
    assert "FAKE_TEXT_FIXTURE" not in dumped


def test_logs_do_not_store_full_prompt_or_prose() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("slove_context.llm")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        gateway = LlmGateway(
            FakeProvider(),
            policy=RetryPolicy(timeout_s=1.0, max_retries=0),
            sleep=lambda _: None,
            logger=logger,
        )
        gateway.generate_text(_request(user_prompt=PROSE_MARK))
    finally:
        logger.removeHandler(handler)

    text = stream.getvalue()
    assert PROMPT_MARK not in text
    assert PROSE_MARK not in text
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    complete = [row for row in records if row.get("message") == "llm generate complete"]
    assert complete
    payload = complete[-1]
    assert payload["system_prompt"]["redacted"] is True
    assert payload["user_prompt"]["redacted"] is True


def test_redact_llm_reuses_audit_policy_for_parsed_output() -> None:
    redacted = redact_llm(
        {
            "system_prompt": PROMPT_MARK,
            "parsed_output": PROSE_MARK,
            "api_key": "sk-example-not-real",
            "raw_response_reference": "fake:ref:1",
            "prompt_version": "fake-v1",
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        }
    )
    dumped = json.dumps(redacted, ensure_ascii=False)
    assert PROMPT_MARK not in dumped
    assert PROSE_MARK not in dumped
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["raw_response_reference"] == "fake:ref:1"
    assert redacted["parsed_output"]["kind"] == "body"
    assert redacted["prompt_version"] == "fake-v1"
    assert redacted["usage"]["prompt_tokens"] == 10


def test_llm_package_has_no_vendor_http_or_scene_plan_job() -> None:
    forbidden = (
        "openai",
        "anthropic",
        "langchain",
        "httpx",
        "requests",
        "aiohttp",
    )
    for path in LLM_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in text
            assert f"from {name}" not in text
        assert "def generate_scene_plan" not in text
        assert "class ScenePlan" not in text
        assert "scene-plan generation job" not in text.lower()


def test_no_generate_scene_or_scene_plan_http() -> None:
    assert client.get("/healthz").status_code == 200
    assert client.get("/version").status_code == 200
    assert client.post("/llm/generate", json={}).status_code == 404
    assert client.post("/scenes/generate", json={}).status_code == 404
    assert client.post("/scene-plans", json={}).status_code == 404


def test_gateway_does_not_import_canon_or_scene_writers() -> None:
    text = (LLM_DIR / "gateway.py").read_text(encoding="utf-8")
    assert "from slove_context.canon" not in text
    assert "from slove_context.scene" not in text
    assert "generate-scene" not in text
