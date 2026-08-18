"""request_id middleware and structured request-complete logs (node 1.3)."""

from __future__ import annotations

import io
import json
import logging

from fastapi.testclient import TestClient
from slove_context.app import app
from slove_context.logging import JsonFormatter
from slove_context.middleware import REQUEST_ID_HEADER, resolve_request_id

client = TestClient(app)


def _capture_request_logs() -> tuple[logging.Handler, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("slove_context")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return handler, stream


def test_healthz_returns_generated_request_id() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    request_id = response.headers.get(REQUEST_ID_HEADER)
    assert request_id
    assert request_id.strip() == request_id


def test_incoming_x_request_id_is_accepted() -> None:
    incoming = "client-supplied-request-id"
    response = client.get("/healthz", headers={REQUEST_ID_HEADER: incoming})
    assert response.status_code == 200
    assert response.headers.get(REQUEST_ID_HEADER) == incoming


def test_blank_x_request_id_is_replaced() -> None:
    response = client.get("/healthz", headers={REQUEST_ID_HEADER: "   "})
    assert response.status_code == 200
    request_id = response.headers.get(REQUEST_ID_HEADER)
    assert request_id
    assert request_id.strip() != ""


def test_version_still_works_with_request_id() -> None:
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json().get("version")
    assert response.headers.get(REQUEST_ID_HEADER)


def test_request_complete_json_log_fields() -> None:
    handler, stream = _capture_request_logs()
    logger = logging.getLogger("slove_context")
    try:
        response = client.get("/healthz", headers={REQUEST_ID_HEADER: "log-req-1"})
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 200
    records = [
        json.loads(line) for line in stream.getvalue().splitlines() if line.strip()
    ]
    complete = [row for row in records if row.get("message") == "request complete"]
    assert complete
    payload = complete[-1]
    assert payload["timestamp"]
    assert payload["level"]
    assert payload["request_id"] == "log-req-1"
    assert payload["operation"] == "GET /healthz"
    assert isinstance(payload["duration_ms"], int | float)
    assert payload["duration_ms"] >= 0


def test_json_formatter_includes_required_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="slove_context.request",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request complete",
        args=(),
        exc_info=None,
    )
    record.request_id = "fmt-1"
    record.operation = "GET /version"
    record.duration_ms = 2.5
    payload = json.loads(formatter.format(record))
    assert payload["timestamp"]
    assert payload["level"] == "INFO"
    assert payload["request_id"] == "fmt-1"
    assert payload["operation"] == "GET /version"
    assert payload["duration_ms"] == 2.5


def test_resolve_request_id_generates_when_missing() -> None:
    generated = resolve_request_id(None)
    assert generated
    assert resolve_request_id("abc") == "abc"
