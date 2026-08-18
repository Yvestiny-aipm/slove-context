"""Audit writer and redaction (node 1.3). In-memory sink; no live Postgres."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from slove_context.audit import (
    REDACTED,
    AuditEvent,
    AuditWriter,
    InMemoryAuditSink,
    redact,
)

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_COLUMNS = (
    "id",
    "occurred_at",
    "actor_type",
    "actor_id",
    "action",
    "resource_type",
    "resource_id",
    "before_json",
    "after_json",
    "correlation_id",
)


def test_audit_writer_success_path() -> None:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    occurred = datetime(2026, 8, 18, 3, 40, tzinfo=UTC)

    event = writer.write(
        actor_type="human_editor",
        actor_id="editor-1",
        action="route.inspect",
        resource_type="http_route",
        resource_id="/healthz",
        before_json=None,
        after_json={"status": "ok"},
        correlation_id="req-success-1",
        occurred_at=occurred,
        event_id="11111111-1111-1111-1111-111111111111",
    )

    assert isinstance(event, AuditEvent)
    assert len(sink.events) == 1
    stored = sink.events[0]
    assert stored is event
    assert stored.id == "11111111-1111-1111-1111-111111111111"
    assert stored.occurred_at == occurred
    assert stored.actor_type == "human_editor"
    assert stored.actor_id == "editor-1"
    assert stored.action == "route.inspect"
    assert stored.resource_type == "http_route"
    assert stored.resource_id == "/healthz"
    assert stored.before_json is None
    assert stored.after_json == {"status": "ok"}
    assert stored.correlation_id == "req-success-1"


def test_audit_writer_applies_redaction() -> None:
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)

    writer.write(
        actor_type="system",
        action="generate.attempt",
        resource_type="scene_draft",
        resource_id="draft-ref-1",
        before_json={"prompt": "旧 Prompt 正文不得入库"},
        after_json={
            "api_key": "sk-example-not-a-real-key",
            "MODEL_API_KEY": "changeme-not-real",
            "prompt": "写一场河滩捡玉，但不要输出这段指令本身",
            "body": "林晚蹲在青石镇河滩，把残玉握进掌心。",
            "nested": {"secret": "should-not-remain", "ok": True},
            "status": "queued",
        },
        correlation_id="req-redact-1",
    )

    stored = sink.events[0]
    assert stored.before_json is not None
    assert stored.before_json["prompt"]["redacted"] is True
    assert stored.before_json["prompt"]["ref"].startswith("prompt:")

    payload = stored.after_json
    assert payload is not None
    assert payload["api_key"] == REDACTED
    assert payload["MODEL_API_KEY"] == REDACTED
    assert payload["nested"]["secret"] == REDACTED
    assert payload["nested"]["ok"] is True
    assert payload["status"] == "queued"
    assert payload["prompt"]["redacted"] is True
    assert payload["prompt"]["kind"] == "prompt"
    assert payload["prompt"]["ref"].startswith("prompt:")
    assert payload["body"]["redacted"] is True
    assert payload["body"]["kind"] == "body"
    assert payload["body"]["ref"].startswith("body:")

    dumped = json.dumps(payload, ensure_ascii=False)
    assert "sk-example" not in dumped
    assert "changeme-not-real" not in dumped
    assert "should-not-remain" not in dumped
    assert "写一场河滩" not in dumped
    assert "林晚" not in dumped
    assert "残玉" not in dumped


def test_redact_direct_secret_prompt_and_body() -> None:
    result = redact(
        {
            "authorization": "Bearer example",
            "user_prompt": "模型 Prompt",
            "scene_draft": "散文正文",
            "evidence_quote": "伸手拾起残玉",
            "source_evidence": "残玉在路人手中也亮了",
            "canon_evidence": "残玉只能由林晚触活",
            "keep": 1,
            "prompt_version": "fake-v1",
            "prompt_tokens": 10,
        }
    )
    assert result["authorization"] == REDACTED
    assert result["user_prompt"]["ref"].startswith("prompt:")
    assert result["scene_draft"]["ref"].startswith("body:")
    assert result["evidence_quote"]["ref"].startswith("body:")
    assert result["source_evidence"]["ref"].startswith("body:")
    assert result["canon_evidence"]["ref"].startswith("body:")
    assert result["keep"] == 1
    assert result["prompt_version"] == "fake-v1"
    assert result["prompt_tokens"] == 10
    assert "模型 Prompt" not in json.dumps(result, ensure_ascii=False)
    assert "散文正文" not in json.dumps(result, ensure_ascii=False)
    assert "伸手拾起残玉" not in json.dumps(result, ensure_ascii=False)
    assert "残玉在路人手中也亮了" not in json.dumps(result, ensure_ascii=False)
    assert "残玉只能由林晚触活" not in json.dumps(result, ensure_ascii=False)


def test_redact_style_examples_and_sample_body() -> None:
    result = redact(
        {
            "positive_examples": ["她把残玉握进掌心，河风贴着腕骨过去。"],
            "negative_examples": ["路人也能触活残玉。"],
            "正例": "她低声说，祠门不该在夜里开。",
            "反例": "哇塞这玉也太酷了吧！",
            "sample_body": "河滩泥凉，林晚蹲下去。",
            "sample_text": "完整样本正文不得入审计",
            "keep": "style_guide",
        }
    )
    dumped = json.dumps(result, ensure_ascii=False)
    assert result["positive_examples"]["redacted"] is True
    assert result["negative_examples"]["redacted"] is True
    assert result["正例"]["redacted"] is True
    assert result["反例"]["redacted"] is True
    assert result["sample_body"]["redacted"] is True
    assert result["sample_text"]["redacted"] is True
    assert result["keep"] == "style_guide"
    assert "残玉握进掌心" not in dumped
    assert "路人也能触活" not in dumped
    assert "祠门不该" not in dumped
    assert "太酷了" not in dumped
    assert "河滩泥凉" not in dumped
    assert "完整样本正文" not in dumped


def test_audit_events_migration_defines_required_columns() -> None:
    versions = ROOT / "backend" / "alembic" / "versions"
    files = list(versions.glob("*audit_events*.py"))
    assert files, "expected a reviewable audit_events Alembic revision"
    text = files[0].read_text(encoding="utf-8")
    assert "CREATE TABLE audit_events" in text
    for column in REQUIRED_COLUMNS:
        assert column in text
    lowered = text.lower()
    assert "create table canon" not in lowered
    assert "create table story_project" not in lowered
    assert "create table story_spec" not in lowered
