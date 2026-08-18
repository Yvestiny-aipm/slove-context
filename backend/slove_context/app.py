"""Local FastAPI app.

Node 1.2 routes: GET /healthz, GET /version (kept).
Node 1.3: request_id + JSON request-complete logs.
Node 2.1: Story Project / Story Spec persistence APIs.
Node 2.2: minimal Canon entities / evidence / facts API.

No auth, queues, or model clients. Spec approval is not Canon approval.
Snapshot freeze / replay is node 2.3 and is not implemented.
Built-in /openapi.json is kept.
"""

from fastapi import FastAPI

from slove_context import __version__
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.canon.repository import CanonRepository, InMemoryCanonRepository
from slove_context.canon.routes import router as canon_router
from slove_context.logging import configure_json_logging
from slove_context.middleware import RequestIdMiddleware
from slove_context.story.repository import InMemoryStoryRepository, StoryRepository
from slove_context.story.routes import router as story_router

configure_json_logging()


def create_app(
    *,
    repository: StoryRepository | None = None,
    canon_repository: CanonRepository | None = None,
    audit_writer: AuditWriter | None = None,
) -> FastAPI:
    """Build the app. Tests inject in-memory repositories and an audit sink."""
    application = FastAPI(title="slove-context", version=__version__)
    application.add_middleware(RequestIdMiddleware)
    application.state.repository = repository or InMemoryStoryRepository()
    application.state.canon_repository = canon_repository or InMemoryCanonRepository()
    application.state.audit_writer = audit_writer or AuditWriter(InMemoryAuditSink())
    application.include_router(story_router)
    application.include_router(canon_router)

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/version")
    def version() -> dict[str, str]:
        return {"version": __version__}

    return application


app = create_app()
