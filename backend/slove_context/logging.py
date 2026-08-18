"""Structured JSON logging (node 1.3). No external log SaaS.

Request-complete records include timestamp, level, request_id, operation,
duration_ms. Raw API keys, story prose, and model prompts are never logged;
see docs/audit.md and slove_context.audit.redact.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from slove_context.audit import redact

LOGGER_NAME = "slove_context"
REQUEST_LOGGER_NAME = "slove_context.request"
LLM_LOGGER_NAME = "slove_context.llm"

_request_id_var: ContextVar[str | None] = ContextVar("slove_request_id", default=None)


def get_request_id() -> str | None:
    return _request_id_var.get()


def set_request_id(value: str) -> Token[str | None]:
    return _request_id_var.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id_var.reset(token)


class JsonFormatter(logging.Formatter):
    """Format a LogRecord as one JSON object per line."""

    _extra_fields = (
        "request_id",
        "operation",
        "duration_ms",
        "status_code",
        "method",
        "path",
        "correlation_id",
        "provider",
        "model",
        "prompt_version",
        "task_type",
        "raw_response_reference",
        "latency_ms",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        for key in self._extra_fields:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        extra_payload = getattr(record, "log_payload", None)
        if isinstance(extra_payload, dict):
            for key, value in extra_payload.items():
                if key not in payload:
                    payload[key] = value
        request_id = payload.get("request_id") or get_request_id()
        if request_id:
            payload["request_id"] = request_id
        return json.dumps(redact(payload), ensure_ascii=False, default=str)


def configure_json_logging() -> logging.Logger:
    """Attach a JSON StreamHandler to the slove_context logger once."""
    logger = logging.getLogger(LOGGER_NAME)
    if not any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def get_request_logger() -> logging.Logger:
    return logging.getLogger(REQUEST_LOGGER_NAME)


def get_llm_logger() -> logging.Logger:
    return logging.getLogger(LLM_LOGGER_NAME)
