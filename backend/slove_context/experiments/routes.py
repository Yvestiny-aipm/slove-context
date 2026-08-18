"""HTTP routes for Experiment Run (node 9.2).

POST /experiments
GET  /experiments
GET  /experiments/{experiment_id}
PATCH /experiments/{experiment_id}   (default prompt only; not historical runs)
POST /experiments/{experiment_id}/cancel
POST /experiments/{experiment_id}/runs
GET  /experiments/{experiment_id}/runs
GET  /experiments/{experiment_id}/runs/{run_id}
PATCH/PUT /experiments/{experiment_id}/runs/{run_id}  (always 409)
POST /experiments/{experiment_id}/runs/{run_id}/compare
GET  /experiments/{experiment_id}/runs/{run_id}/export
GET  /experiments/{experiment_id}/comparisons/{comparison_id}
GET  /experiments/{experiment_id}/comparisons/{comparison_id}/export
POST /experiments/{experiment_id}/approve-canon  (always 403)
POST /experiments/{experiment_id}/submit-canon   (always 403)

No production seed-status. Fake Provider only. Not a 9.3 release gate.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from slove_context.experiments.repository import (
    InMemoryExperimentRepository,
)
from slove_context.experiments.service import ExperimentService, ExperimentServiceError
from slove_context.llm.fake import FakeProvider
from slove_context.story.actors import (
    ACTOR_ID_HEADER,
    ACTOR_TYPE_HEADER,
    Actor,
    resolve_actor,
)

router = APIRouter(tags=["experiments"])


class ActorBody(BaseModel):
    actor_type: str | None = None
    actor_id: str | None = None
    created_by: str | None = None


class CreateExperimentBody(ActorBody):
    name: str
    case_ids: list[str] | None = None
    model: str | None = None
    prompt_version: str | None = None
    retrieval_strategy: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class PatchExperimentBody(ActorBody):
    prompt_version: str


class ExecuteRunBody(ActorBody):
    model: str | None = None
    prompt_version: str | None = None
    retrieval_strategy: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class CompareBody(ActorBody):
    baseline_run_id: str


def _service(request: Request) -> ExperimentService:
    repository = (
        getattr(request.app.state, "experiment_repository", None)
        or InMemoryExperimentRepository()
    )
    gateway = getattr(request.app.state, "llm_gateway", None)
    inner = getattr(gateway, "_provider", None) if gateway is not None else None
    provider = inner or gateway or FakeProvider()
    return ExperimentService(
        repository=repository,
        audit_writer=request.app.state.audit_writer,
        provider=provider,
    )


def _actor(request: Request, body: ActorBody | None = None) -> Actor:
    body_type = body.actor_type if body is not None else None
    body_id = None
    if body is not None:
        body_id = body.actor_id or body.created_by
    return resolve_actor(
        header_type=request.headers.get(ACTOR_TYPE_HEADER),
        header_id=request.headers.get(ACTOR_ID_HEADER),
        body_type=body_type,
        body_id=body_id,
    )


def _raise(exc: ExperimentServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/experiments", status_code=201)
def create_experiment(request: Request, body: CreateExperimentBody) -> dict[str, Any]:
    try:
        experiment = _service(request).create_experiment(
            actor=_actor(request, body),
            name=body.name,
            case_ids=body.case_ids,
            model=body.model,
            prompt_version=body.prompt_version,
            retrieval_strategy=body.retrieval_strategy,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
    except ExperimentServiceError as exc:
        _raise(exc)
    return experiment.to_public_dict()


@router.get("/experiments")
def list_experiments(request: Request) -> dict[str, Any]:
    items = _service(request).list_experiments()
    return {"items": [item.to_public_dict() for item in items]}


@router.get("/experiments/{experiment_id}")
def get_experiment(request: Request, experiment_id: str) -> dict[str, Any]:
    try:
        experiment = _service(request).get_experiment(experiment_id)
    except ExperimentServiceError as exc:
        _raise(exc)
    return experiment.to_public_dict()


@router.patch("/experiments/{experiment_id}")
def patch_experiment(
    request: Request, experiment_id: str, body: PatchExperimentBody
) -> dict[str, Any]:
    try:
        experiment = _service(request).update_default_prompt(
            experiment_id,
            actor=_actor(request, body),
            prompt_version=body.prompt_version,
        )
    except ExperimentServiceError as exc:
        _raise(exc)
    return experiment.to_public_dict()


@router.post("/experiments/{experiment_id}/cancel")
def cancel_experiment(
    request: Request, experiment_id: str, body: ActorBody | None = None
) -> dict[str, Any]:
    try:
        experiment = _service(request).cancel_experiment(
            experiment_id, actor=_actor(request, body)
        )
    except ExperimentServiceError as exc:
        _raise(exc)
    return experiment.to_public_dict()


@router.post("/experiments/{experiment_id}/runs", status_code=201)
def execute_run(
    request: Request, experiment_id: str, body: ExecuteRunBody | None = None
) -> dict[str, Any]:
    payload = body or ExecuteRunBody()
    try:
        run = _service(request).execute(
            experiment_id,
            actor=_actor(request, payload),
            model=payload.model,
            prompt_version=payload.prompt_version,
            retrieval_strategy=payload.retrieval_strategy,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
        )
    except ExperimentServiceError as exc:
        _raise(exc)
    return run.to_public_dict()


@router.get("/experiments/{experiment_id}/runs")
def list_runs(request: Request, experiment_id: str) -> dict[str, Any]:
    try:
        items = _service(request).list_runs(experiment_id)
    except ExperimentServiceError as exc:
        _raise(exc)
    return {"items": [item.to_public_dict() for item in items]}


@router.get("/experiments/{experiment_id}/runs/{run_id}")
def get_run(request: Request, experiment_id: str, run_id: str) -> dict[str, Any]:
    try:
        run = _service(request).get_run(experiment_id, run_id)
    except ExperimentServiceError as exc:
        _raise(exc)
    return run.to_public_dict()


@router.patch("/experiments/{experiment_id}/runs/{run_id}")
@router.put("/experiments/{experiment_id}/runs/{run_id}")
def mutate_run(
    request: Request,
    experiment_id: str,
    run_id: str,
    body: ExecuteRunBody | None = None,
) -> dict[str, Any]:
    del body
    try:
        _service(request).reject_mutate_run(experiment_id, run_id)
    except ExperimentServiceError as exc:
        _raise(exc)
    raise HTTPException(status_code=409, detail={"error": "experiment_run_immutable"})


@router.post("/experiments/{experiment_id}/runs/{run_id}/compare")
def compare_run(
    request: Request, experiment_id: str, run_id: str, body: CompareBody
) -> dict[str, Any]:
    try:
        comparison = _service(request).compare(
            experiment_id,
            run_id,
            actor=_actor(request, body),
            baseline_run_id=body.baseline_run_id,
        )
    except ExperimentServiceError as exc:
        _raise(exc)
    return comparison.to_public_dict()


@router.get("/experiments/{experiment_id}/runs/{run_id}/export")
def export_run(
    request: Request,
    experiment_id: str,
    run_id: str,
    format: str = Query(default="json", alias="format"),
) -> Response:
    try:
        body, media_type = _service(request).export_run(
            experiment_id, run_id, fmt=format
        )
    except ExperimentServiceError as exc:
        _raise(exc)
    if media_type == "text/csv":
        return PlainTextResponse(content=body, media_type="text/csv")
    return Response(content=body, media_type="application/json")


@router.get("/experiments/{experiment_id}/comparisons/{comparison_id}")
def get_comparison(
    request: Request, experiment_id: str, comparison_id: str
) -> dict[str, Any]:
    try:
        comparison = _service(request).get_comparison(experiment_id, comparison_id)
    except ExperimentServiceError as exc:
        _raise(exc)
    return comparison.to_public_dict()


@router.get("/experiments/{experiment_id}/comparisons/{comparison_id}/export")
def export_comparison(
    request: Request,
    experiment_id: str,
    comparison_id: str,
    format: str = Query(default="json", alias="format"),
) -> Response:
    try:
        body, media_type = _service(request).export_comparison(
            experiment_id, comparison_id, fmt=format
        )
    except ExperimentServiceError as exc:
        _raise(exc)
    if media_type == "text/csv":
        return PlainTextResponse(content=body, media_type="text/csv")
    return Response(content=body, media_type="application/json")


@router.post("/experiments/{experiment_id}/approve-canon")
def approve_canon(
    request: Request, experiment_id: str, body: ActorBody | None = None
) -> dict[str, Any]:
    del experiment_id
    try:
        _service(request).reject_canon_write(
            actor=_actor(request, body), action="approve"
        )
    except ExperimentServiceError as exc:
        _raise(exc)
    raise HTTPException(
        status_code=403, detail={"error": "experiment_cannot_write_canon"}
    )


@router.post("/experiments/{experiment_id}/submit-canon")
def submit_canon(
    request: Request, experiment_id: str, body: ActorBody | None = None
) -> dict[str, Any]:
    del experiment_id
    try:
        _service(request).reject_canon_write(
            actor=_actor(request, body), action="submit"
        )
    except ExperimentServiceError as exc:
        _raise(exc)
    raise HTTPException(
        status_code=403, detail={"error": "experiment_cannot_write_canon"}
    )
