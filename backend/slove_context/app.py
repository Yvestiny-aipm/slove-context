"""Local FastAPI app (node 1.2). Health and version only.

No Canon APIs, auth, queues, or model clients.
"""

from fastapi import FastAPI

from slove_context import __version__

app = FastAPI(title="slove-context", version=__version__)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
def version() -> dict[str, str]:
    return {"version": __version__}
