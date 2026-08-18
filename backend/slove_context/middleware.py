"""HTTP request_id and timing middleware (node 1.3).

Every request receives a request_id (incoming X-Request-ID, or generated).
The same value is returned on the response. Request-complete logs are JSON
via slove_context.logging. Request bodies are not logged.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from slove_context.logging import (
    get_request_logger,
    reset_request_id,
    set_request_id,
)

REQUEST_ID_HEADER = "X-Request-ID"
MAX_REQUEST_ID_LEN = 128


def resolve_request_id(incoming: str | None) -> str:
    """Accept a caller-supplied X-Request-ID, or generate one."""
    if incoming is not None:
        cleaned = incoming.strip()
        if cleaned:
            return cleaned[:MAX_REQUEST_ID_LEN]
    return str(uuid.uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assign request_id, time the request, emit a request-complete JSON log."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = set_request_id(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code: int | None = None
        path = request.url.path
        method = request.method
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            get_request_logger().info(
                "request complete",
                extra={
                    "request_id": request_id,
                    "operation": f"{method} {path}",
                    "duration_ms": duration_ms,
                    "status_code": status_code,
                    "method": method,
                    "path": path,
                },
            )
            reset_request_id(token)
