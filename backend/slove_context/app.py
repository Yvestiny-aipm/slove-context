"""Local FastAPI app.

Node 1.2 routes: GET /healthz, GET /version (kept).
Node 1.3: request_id + JSON request-complete logs.
Node 2.1: Story Project / Story Spec persistence APIs.
Node 2.2: minimal Canon entities / evidence / facts API.
Node 2.3: Canon Snapshot create / freeze / query / diff / replay.
Node 3.1: Scene Card, in-story order, and scene dependencies.
Node 3.2: LLM Gateway as an in-process Fake Provider (no live vendor calls).
Node 3.3: Scene Plan generation jobs (Fake Provider only).
Node 3.4: Scene Draft generation jobs (Fake Provider only).
Node 4.1: Candidate Change extraction jobs (Fake Provider only; no Validate).

No auth, queues, or live model clients. Spec / Scene Card approval is not
Canon approval. Scene Plan, Scene Draft, and Candidate Change are not Canon.
There is no Context Pack builder — draft jobs reference a static fixture.
Built-in /openapi.json is kept.
"""

from fastapi import FastAPI

from slove_context import __version__
from slove_context.audit import AuditWriter, InMemoryAuditSink
from slove_context.candidate_change.models import (
    DEFAULT_REPAIR_TASK_TYPE as EXTRACT_REPAIR_TASK_TYPE,
)
from slove_context.candidate_change.models import DEFAULT_TASK_TYPE as EXTRACT_TASK_TYPE
from slove_context.candidate_change.repository import (
    CandidateChangeRepository,
    InMemoryCandidateChangeRepository,
)
from slove_context.candidate_change.routes import router as candidate_change_router
from slove_context.canon.repository import CanonRepository, InMemoryCanonRepository
from slove_context.canon.routes import router as canon_router
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway
from slove_context.logging import configure_json_logging
from slove_context.middleware import RequestIdMiddleware
from slove_context.scene.repository import InMemorySceneRepository, SceneRepository
from slove_context.scene.routes import router as scene_router
from slove_context.scene_draft.models import DEFAULT_TASK_TYPE as DRAFT_TASK_TYPE
from slove_context.scene_draft.repository import (
    InMemorySceneDraftRepository,
    SceneDraftRepository,
)
from slove_context.scene_draft.routes import router as scene_draft_router
from slove_context.scene_plan.models import DEFAULT_REPAIR_TASK_TYPE, DEFAULT_TASK_TYPE
from slove_context.scene_plan.repository import (
    InMemoryScenePlanRepository,
    ScenePlanRepository,
)
from slove_context.scene_plan.routes import router as scene_plan_router
from slove_context.story.repository import InMemoryStoryRepository, StoryRepository
from slove_context.story.routes import router as story_router

configure_json_logging()


def create_app(
    *,
    repository: StoryRepository | None = None,
    canon_repository: CanonRepository | None = None,
    scene_repository: SceneRepository | None = None,
    scene_plan_repository: ScenePlanRepository | None = None,
    scene_draft_repository: SceneDraftRepository | None = None,
    candidate_change_repository: CandidateChangeRepository | None = None,
    audit_writer: AuditWriter | None = None,
    llm_gateway: LlmGateway | None = None,
    scene_plan_task_type: str = DEFAULT_TASK_TYPE,
    scene_plan_repair_task_type: str = DEFAULT_REPAIR_TASK_TYPE,
    scene_draft_task_type: str = DRAFT_TASK_TYPE,
    scene_draft_auto_run: bool = True,
    extract_task_type: str = EXTRACT_TASK_TYPE,
    extract_repair_task_type: str = EXTRACT_REPAIR_TASK_TYPE,
    extract_auto_run: bool = True,
) -> FastAPI:
    """Build the app. Tests inject in-memory repositories and an audit sink."""
    application = FastAPI(title="slove-context", version=__version__)
    application.add_middleware(RequestIdMiddleware)
    writer = audit_writer or AuditWriter(InMemoryAuditSink())
    application.state.repository = repository or InMemoryStoryRepository()
    application.state.canon_repository = canon_repository or InMemoryCanonRepository()
    application.state.scene_repository = scene_repository or InMemorySceneRepository()
    application.state.scene_plan_repository = (
        scene_plan_repository or InMemoryScenePlanRepository()
    )
    application.state.scene_draft_repository = (
        scene_draft_repository or InMemorySceneDraftRepository()
    )
    application.state.candidate_change_repository = (
        candidate_change_repository or InMemoryCandidateChangeRepository()
    )
    application.state.audit_writer = writer
    application.state.llm_gateway = llm_gateway or LlmGateway(
        FakeProvider(), audit_writer=writer
    )
    application.state.scene_plan_task_type = scene_plan_task_type
    application.state.scene_plan_repair_task_type = scene_plan_repair_task_type
    application.state.scene_draft_task_type = scene_draft_task_type
    application.state.scene_draft_auto_run = scene_draft_auto_run
    application.state.extract_task_type = extract_task_type
    application.state.extract_repair_task_type = extract_repair_task_type
    application.state.extract_auto_run = extract_auto_run
    application.include_router(story_router)
    application.include_router(canon_router)
    application.include_router(scene_router)
    application.include_router(scene_plan_router)
    application.include_router(scene_draft_router)
    application.include_router(candidate_change_router)

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/version")
    def version() -> dict[str, str]:
        return {"version": __version__}

    return application


app = create_app()
