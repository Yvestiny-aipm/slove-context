"""Local FastAPI app (node 1.2 routes + node 1.3 request_id / JSON logs).

Keeps GET /healthz and GET /version. No Canon APIs, auth, queues, or model clients.
"""

from fastapi import FastAPI

from slove_context import __version__
from slove_context.logging import configure_json_logging
from slove_context.middleware import RequestIdMiddleware

configure_json_logging()

app = FastAPI(title="slove-context", version=__version__)
app.add_middleware(RequestIdMiddleware)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
def version() -> dict[str, str]:
    return {"version": __version__}
