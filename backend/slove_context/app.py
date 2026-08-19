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
Node 4.2: human approve / reject / submit for Candidate Changes.
Approve does not write Canon; submit creates or supersedes a Canon Fact.
Node 4.3: Scene / Chapter summary jobs (Fake Provider only).
Scene Summary recaps one existing Scene Draft. Chapter Summary rolls up
existing Scene Summaries. Summaries are not Canon / Draft / Candidate.
Node 5.1: Validation Run (deterministic rules; no LLM). Passed moves
candidates to AwaitingVerdict only. It is not Approval and does not
write Canon.
Node 5.2: Repair Task opened only from a RuleFailed Violation.
Completed must start a 5.1 Validation Run. RecheckPassed is not
Approval and does not write Canon.
Node 6.1: Context Pack assembler (deterministic; one scene; Snapshot
excerpts are read-only). Freeze is not Canon approval.
Node 6.2: Outline Revision (Drafting → Proposed → Confirmed). Confirm
usable is not Approval and does not write Canon. Outline is not a
generation unit.
Node 7.1: versioned Style Guide / Style Sample. Only a human 主编 may
approve a guide or authorize a sample. Approve / authorize is not Canon
approval and does not write Canon. Frozen rows are immutable; changes
open a new revision / new id. Scene Draft may associate an approved
guide revision as a reference only (3.4 generate job is unchanged).
Node 7.2: Style Validation v1 (deterministic checks + Fake Provider
LLM check against an approved Style Guide). Findings default to
warning / info and do not block Canon submit. Not a 5.x Validation
Run. 3.4 generate job is unchanged.
Node 7.3: human review-queue API. Enqueue existing Scene Plan / Scene
Draft / Candidate Change / Validation Report / Repair Task / Style
Report subjects. Only a human 主编 may approve / reject /
request_revision / escalate, each with a reason_code. Candidate
approve reuses 4.2 (verdict only, not submit). Style-report approve
is not Canon approval and does not block Canon submit.
Node 8.1: local job queue and in-process Worker. The Worker
dispatches by job_type to existing plan / draft / extract / validate
/ repair / summarize / context_pack services. It does not approve
Candidate Changes, does not submit Canon, and does not take review-
queue decisions.
Node 8.2: Agent Registry and permission boundaries. Seven agents
are registered. The service layer re-checks permissions; unauthorized
tools are 403. Agent Runs archive input/output refs, tool calls,
cost, duration, and error. No Agent (including Worker / system) may
bypass Approval to write Canon. Human Approver is the only
Canon-approve actor.
Node 8.3: single-scene DAG orchestrator. Fixed nodes dispatch
through the 8.1 Worker. human_review / canon_commit wait.
canon_commit calls existing 4.2 submit only after a human 主编
approve.
Node 8.4: batch project/chapter scheduler. Multi-project ticks
go through 8.3 DAG + 8.1 Worker + 8.2 PermissionGuard. Same-
project enqueue requires approved dependencies. Pause + human
alert on budget or consecutive failures. dry-run does not call
the model. No auto Canon approve.
Node 9.1: narrative consistency eval dataset and deterministic
runner (no HTTP). Node 9.2: Experiment Run + baseline compare
on the pinned 9.1 cases (Fake Provider only). Node 9.3: release
gates and formal book export (read-only checks; no new prose).
Release does not write Canon or approve.
Node UI.2 adds a human shuttle (copy prompt / paste result).
Shuttle does not call Gateway / Fake / vendor HTTP and does not
write Canon.

No auth or live model clients. Spec / Scene Card approval is not
Canon approval. Scene Plan, Scene Draft, Candidate Change,
summaries, Validation Runs, Repair Tasks, Context Packs, Outline
Revisions, Style Guide / Sample approvals, Style Validation
reports, review-queue decisions, and Worker jobs are not Canon
writes. Scene Draft jobs still accept the 3.4 static fixture id or
a frozen assembler pack. There is no chapter-level or book-level
generate entrance and no chapter-level Context Pack. No production
seed-status route. Built-in /openapi.json is kept.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from slove_context import __version__
from slove_context.agents.repository import (
    AgentRepository,
    InMemoryAgentRunRepository,
)
from slove_context.agents.routes import router as agents_router
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
from slove_context.context_pack.repository import (
    ContextPackRepository,
    InMemoryContextPackRepository,
)
from slove_context.context_pack.routes import router as context_pack_router
from slove_context.cors import cors_origins_for_env
from slove_context.dags.repository import DagRepository, InMemoryDagRepository
from slove_context.dags.routes import router as dags_router
from slove_context.experiments.repository import (
    ExperimentRepository,
    InMemoryExperimentRepository,
)
from slove_context.experiments.routes import router as experiments_router
from slove_context.jobs.deps import services_from_state
from slove_context.jobs.repository import InMemoryJobRepository, JobRepository
from slove_context.jobs.routes import router as jobs_router
from slove_context.jobs.worker import Worker
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import LlmGateway
from slove_context.logging import configure_json_logging
from slove_context.middleware import RequestIdMiddleware
from slove_context.outline.repository import (
    InMemoryOutlineRepository,
    OutlineRepository,
)
from slove_context.outline.routes import router as outline_router
from slove_context.release.repository import (
    InMemoryReleaseRepository,
    ReleaseRepository,
)
from slove_context.release.routes import router as release_router
from slove_context.repair.repository import (
    InMemoryRepairRepository,
    RepairRepository,
)
from slove_context.repair.routes import router as repair_router
from slove_context.review_queue.repository import (
    InMemoryReviewQueueRepository,
    ReviewQueueRepository,
)
from slove_context.review_queue.routes import router as review_queue_router
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
from slove_context.scheduler.repository import (
    InMemoryScheduleRepository,
    ScheduleRepository,
)
from slove_context.scheduler.routes import router as scheduler_router
from slove_context.shuttle.routes import router as shuttle_router
from slove_context.story.repository import InMemoryStoryRepository, StoryRepository
from slove_context.story.routes import router as story_router
from slove_context.style.repository import InMemoryStyleRepository, StyleRepository
from slove_context.style.routes import router as style_router
from slove_context.style_validation.repository import (
    InMemoryStyleValidationRepository,
    StyleValidationRepository,
)
from slove_context.style_validation.routes import router as style_validation_router
from slove_context.summary.models import (
    DEFAULT_CHAPTER_TASK_TYPE as CHAPTER_SUMMARY_TASK_TYPE,
)
from slove_context.summary.models import (
    DEFAULT_SCENE_TASK_TYPE as SCENE_SUMMARY_TASK_TYPE,
)
from slove_context.summary.repository import (
    InMemorySummaryRepository,
    SummaryRepository,
)
from slove_context.summary.routes import router as summary_router
from slove_context.validation.repository import (
    InMemoryValidationRepository,
    ValidationRepository,
)
from slove_context.validation.routes import router as validation_router
from slove_context.validation.rules import DeterministicRuleEngine, RuleEngine

configure_json_logging()


def create_app(
    *,
    repository: StoryRepository | None = None,
    canon_repository: CanonRepository | None = None,
    scene_repository: SceneRepository | None = None,
    scene_plan_repository: ScenePlanRepository | None = None,
    scene_draft_repository: SceneDraftRepository | None = None,
    candidate_change_repository: CandidateChangeRepository | None = None,
    summary_repository: SummaryRepository | None = None,
    validation_repository: ValidationRepository | None = None,
    repair_repository: RepairRepository | None = None,
    context_pack_repository: ContextPackRepository | None = None,
    outline_repository: OutlineRepository | None = None,
    style_repository: StyleRepository | None = None,
    style_validation_repository: StyleValidationRepository | None = None,
    review_queue_repository: ReviewQueueRepository | None = None,
    job_repository: JobRepository | None = None,
    agent_repository: AgentRepository | None = None,
    dag_repository: DagRepository | None = None,
    schedule_repository: ScheduleRepository | None = None,
    experiment_repository: ExperimentRepository | None = None,
    release_repository: ReleaseRepository | None = None,
    validation_rule_engine: RuleEngine | None = None,
    audit_writer: AuditWriter | None = None,
    llm_gateway: LlmGateway | None = None,
    scene_plan_task_type: str = DEFAULT_TASK_TYPE,
    scene_plan_repair_task_type: str = DEFAULT_REPAIR_TASK_TYPE,
    scene_draft_task_type: str = DRAFT_TASK_TYPE,
    scene_draft_auto_run: bool = True,
    extract_task_type: str = EXTRACT_TASK_TYPE,
    extract_repair_task_type: str = EXTRACT_REPAIR_TASK_TYPE,
    extract_auto_run: bool = True,
    scene_summary_task_type: str = SCENE_SUMMARY_TASK_TYPE,
    chapter_summary_task_type: str = CHAPTER_SUMMARY_TASK_TYPE,
    summary_auto_run: bool = True,
    validation_auto_run: bool = True,
    style_validation_auto_run: bool = True,
    job_auto_run: bool = False,
    agent_run_auto_run: bool = True,
    job_timeout_s: float = 30.0,
    job_base_backoff_s: float = 0.0,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Build the app. Tests inject in-memory repositories and an audit sink.

    Node UI.1: optional development CORS for the Vite origin. Production
    does not open ``*``. There is no production seed-status route.
    """
    application = FastAPI(title="slove-context", version=__version__)
    origins = list(cors_origins) if cors_origins is not None else cors_origins_for_env()
    if origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )
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
    application.state.summary_repository = (
        summary_repository or InMemorySummaryRepository()
    )
    application.state.validation_repository = (
        validation_repository or InMemoryValidationRepository()
    )
    application.state.repair_repository = (
        repair_repository or InMemoryRepairRepository()
    )
    application.state.context_pack_repository = (
        context_pack_repository or InMemoryContextPackRepository()
    )
    application.state.outline_repository = (
        outline_repository or InMemoryOutlineRepository()
    )
    application.state.style_repository = style_repository or InMemoryStyleRepository()
    application.state.style_validation_repository = (
        style_validation_repository or InMemoryStyleValidationRepository()
    )
    application.state.review_queue_repository = (
        review_queue_repository or InMemoryReviewQueueRepository()
    )
    application.state.job_repository = job_repository or InMemoryJobRepository()
    application.state.agent_repository = (
        agent_repository or InMemoryAgentRunRepository()
    )
    application.state.dag_repository = dag_repository or InMemoryDagRepository()
    application.state.schedule_repository = (
        schedule_repository or InMemoryScheduleRepository()
    )
    application.state.experiment_repository = (
        experiment_repository or InMemoryExperimentRepository()
    )
    application.state.release_repository = (
        release_repository or InMemoryReleaseRepository()
    )
    application.state.validation_rule_engine = (
        validation_rule_engine or DeterministicRuleEngine()
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
    application.state.scene_summary_task_type = scene_summary_task_type
    application.state.chapter_summary_task_type = chapter_summary_task_type
    application.state.summary_auto_run = summary_auto_run
    application.state.validation_auto_run = validation_auto_run
    application.state.style_validation_auto_run = style_validation_auto_run
    application.state.job_auto_run = job_auto_run
    application.state.agent_run_auto_run = agent_run_auto_run
    application.state.job_timeout_s = job_timeout_s
    application.state.job_base_backoff_s = job_base_backoff_s
    application.state.worker = Worker(
        job_repository=application.state.job_repository,
        audit_writer=writer,
        services=services_from_state(application.state),
        timeout_s=job_timeout_s,
        base_backoff_s=job_base_backoff_s,
    )
    application.include_router(story_router)
    application.include_router(canon_router)
    application.include_router(scene_router)
    application.include_router(scene_plan_router)
    application.include_router(scene_draft_router)
    application.include_router(shuttle_router)
    application.include_router(candidate_change_router)
    application.include_router(summary_router)
    application.include_router(validation_router)
    application.include_router(repair_router)
    application.include_router(context_pack_router)
    application.include_router(outline_router)
    application.include_router(style_router)
    application.include_router(style_validation_router)
    application.include_router(review_queue_router)
    application.include_router(jobs_router)
    application.include_router(agents_router)
    application.include_router(dags_router)
    application.include_router(scheduler_router)
    application.include_router(experiments_router)
    application.include_router(release_router)

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/version")
    def version() -> dict[str, str]:
        return {"version": __version__}

    return application


app = create_app()
