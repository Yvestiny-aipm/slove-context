"""Generic audit event writer (node 1.3).

Persists structured audit rows through an AuditSink. The FastAPI app does
not open a database connection in this node; unit tests use InMemoryAuditSink.

Node 2.1 Story Project / Story Spec writes, node 2.2 Canon writes, and
node 2.3 Canon Snapshot create / freeze reuse this writer. Auto-approve
and multi-project are not MVP-normal (see docs/mvp-scope.md).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

# Replacement for secret/key field values. Never store the raw secret.
REDACTED = "[REDACTED]"

# Key names treated as secrets (case-insensitive, '-' normalized to '_').
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "auth",
        "credential",
        "credentials",
        "private_key",
        "model_api_key",
    }
)

# Key names treated as model Prompt text. Stored only as a reference id.
_PROMPT_KEYS = frozenset(
    {
        "prompt",
        "system_prompt",
        "user_prompt",
        "model_prompt",
        "llm_prompt",
        "messages",
    }
)

# Key names treated as story / HTTP body prose. Stored only as a reference id.
_BODY_KEYS = frozenset(
    {
        "body",
        "body_text",
        "prose",
        "prose_body",
        "scene_draft",
        "draft_text",
        "story_body",
        "raw_text",
        "content_text",
    }
)

_SECRET_SUFFIXES = ("_key", "_secret", "_token", "_password", "_credential")


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _is_secret_key(norm: str) -> bool:
    if norm in _SECRET_KEYS:
        return True
    return any(norm.endswith(suffix) for suffix in _SECRET_SUFFIXES)


def _is_prompt_key(norm: str) -> bool:
    return norm in _PROMPT_KEYS or "prompt" in norm


def _is_body_key(norm: str) -> bool:
    return norm in _BODY_KEYS or norm.endswith(("_body", "_prose"))


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _reference(kind: str, value: Any) -> dict[str, Any]:
    """Replace prose/Prompt with a non-reversible reference id."""
    return {"redacted": True, "kind": kind, "ref": f"{kind}:{_fingerprint(value)}"}


def redact(value: Any) -> Any:
    """Redact body text, Prompt, and secret/key fields.

    Policy (also in docs/audit.md):
    - secret/key fields become ``[REDACTED]``
    - Prompt and prose/body fields become a reference id only
    - nested dicts and lists are walked
    - raw API keys, story prose, and model prompts are never retained
    """
    if isinstance(value, dict):
        return {key: _redact_pair(str(key), item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value


def _redact_pair(key: str, value: Any) -> Any:
    norm = _normalize_key(key)
    if _is_secret_key(norm):
        return REDACTED
    if _is_prompt_key(norm):
        return _reference("prompt", value)
    if _is_body_key(norm):
        return _reference("body", value)
    return redact(value)


@dataclass(frozen=True)
class AuditEvent:
    """One audit_events row. Column names match the Alembic migration."""

    id: str
    occurred_at: datetime
    actor_type: str
    actor_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    before_json: dict[str, Any] | None
    after_json: dict[str, Any] | None
    correlation_id: str | None


class AuditSink(Protocol):
    """Persistence target for already-redacted audit events."""

    def write(self, event: AuditEvent) -> None: ...


class InMemoryAuditSink:
    """Test / local sink. Does not need Postgres."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)


class AuditWriter:
    """Generic audit write service. Always redacts before the sink sees data."""

    def __init__(self, sink: AuditSink) -> None:
        self._sink = sink

    def write(
        self,
        *,
        actor_type: str,
        action: str,
        resource_type: str,
        actor_id: str | None = None,
        resource_id: str | None = None,
        before_json: dict[str, Any] | None = None,
        after_json: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            id=event_id or str(uuid4()),
            occurred_at=occurred_at or datetime.now(UTC),
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=redact(before_json) if before_json is not None else None,
            after_json=redact(after_json) if after_json is not None else None,
            correlation_id=correlation_id,
        )
        self._sink.write(event)
        return event
