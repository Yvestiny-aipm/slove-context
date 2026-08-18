"""Fake Provider (node 3.2). Returns fixed fixtures. No HTTP.

v1 implements only this provider. It does not call OpenAI, Anthropic, or
any other vendor. Fixtures are placeholders, not product Prompt or prose.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from slove_context.llm.errors import StructuredParseError
from slove_context.llm.provider import Provider
from slove_context.llm.types import (
    GenerateError,
    GenerateRequest,
    GenerateResponse,
    Usage,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

TEXT_TASK_TYPES = frozenset({"text", "echo", "fixture_text"})
STRUCTURED_OK_TASK_TYPES = frozenset(
    {"structured", "structured_ok", "fixture_structured"}
)
STRUCTURED_INVALID_TASK_TYPES = frozenset(
    {"structured_invalid", "fixture_structured_invalid"}
)

# Node 3.3 Scene Plan fixtures. Placeholders, not product prose.
SCENE_PLAN_FIXTURES = {
    "scene_plan": "scene_plan_ok.json",
    "scene_plan_ok": "scene_plan_ok.json",
    "scene_plan_invalid_json": "scene_plan_invalid_json.json",
    "scene_plan_invalid_schema": "scene_plan_invalid_schema.json",
    "scene_plan_repair": "scene_plan_ok.json",
    "scene_plan_repair_ok": "scene_plan_ok.json",
    "scene_plan_repair_fail": "scene_plan_repair_fail.json",
    "scene_plan_repair_invalid_schema": "scene_plan_repair_fail.json",
}

# Node 3.4 Scene Draft fixtures. Placeholders, not product prose.
SCENE_DRAFT_FIXTURES = {
    "scene_draft": "scene_draft_ok.json",
    "scene_draft_ok": "scene_draft_ok.json",
    "scene_draft_fail": "scene_draft_fail.json",
}

# Node 4.1 Candidate Change extract fixtures. Placeholders, not product prose.
EXTRACT_CANDIDATE_FIXTURES = {
    "extract_candidates": "extract_candidates_ok.json",
    "extract_candidates_ok": "extract_candidates_ok.json",
    "extract_candidates_invalid_json": "extract_candidates_invalid_json.json",
    "extract_candidates_invalid_schema": "extract_candidates_invalid_schema.json",
    "extract_candidates_repair": "extract_candidates_ok.json",
    "extract_candidates_repair_ok": "extract_candidates_ok.json",
    "extract_candidates_repair_fail": "extract_candidates_repair_fail.json",
}

# Node 4.3 Scene / Chapter summary fixtures. Placeholders, not product prose.
SCENE_SUMMARY_FIXTURES = {
    "scene_summary": "scene_summary_ok.json",
    "scene_summary_ok": "scene_summary_ok.json",
    "scene_summary_fail": "scene_summary_fail.json",
}
CHAPTER_SUMMARY_FIXTURES = {
    "chapter_summary": "chapter_summary_ok.json",
    "chapter_summary_ok": "chapter_summary_ok.json",
    "chapter_summary_fail": "chapter_summary_fail.json",
}

# Node 7.2 Style Validation fixtures. Placeholders, not product prose.
STYLE_VALIDATION_FIXTURES = {
    "style_validation": "style_validation_ok.json",
    "style_validation_ok": "style_validation_ok.json",
}

# Node 9.2 Experiment Run fixtures. Placeholders, not product prose.
EXPERIMENT_EVAL_FIXTURES = {
    "experiment_eval": "experiment_eval_ok.json",
    "experiment_eval_ok": "experiment_eval_ok.json",
    "experiment_eval_invalid": "experiment_eval_invalid.json",
}


class FakeProvider(Provider):
    """Deterministic in-process provider. Safe to retry: no persist side effects."""

    name = "fake"

    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self._fixtures_dir = fixtures_dir or FIXTURES_DIR
        self.calls = 0

    def generate_text(self, request: GenerateRequest) -> GenerateResponse:
        self.calls += 1
        filename = _text_fixture_name(request.task_type)
        data = self._load(filename)
        error = _error_from_fixture(data)
        parsed = None if error is not None else data.get("text")
        return self._response(
            request,
            parsed_output=parsed,
            data=data,
            error=error,
            fixture_name=filename,
        )

    def generate_structured(self, request: GenerateRequest) -> GenerateResponse:
        self.calls += 1
        filename = _structured_fixture_name(request.task_type)
        data = self._load(filename)
        raw_text = data["text"]
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            error = GenerateError(
                code="structured_parse_failed",
                message="Fake Provider fixture is not valid JSON",
            )
            return self._response(
                request,
                parsed_output=None,
                data=data,
                error=error,
                fixture_name=filename,
            )
        if not isinstance(parsed, (dict, list)):
            raise StructuredParseError(
                "structured fixture must decode to an object or array"
            )
        return self._response(
            request,
            parsed_output=parsed,
            data=data,
            error=None,
            fixture_name=filename,
        )

    def _load(self, filename: str) -> dict[str, Any]:
        path = self._fixtures_dir / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError(f"fixture {filename} must be a JSON object")
        return payload

    def _response(
        self,
        request: GenerateRequest,
        *,
        parsed_output: Any,
        data: dict[str, Any],
        error: GenerateError | None,
        fixture_name: str,
    ) -> GenerateResponse:
        usage_raw = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
            completion_tokens=int(usage_raw.get("completion_tokens", 0)),
            total_tokens=int(usage_raw.get("total_tokens", 0)),
            cost_amount=float(usage_raw.get("cost_amount", 0.0)),
            cost_currency=str(usage_raw.get("cost_currency", "USD")),
        )
        request_id = str(uuid4())
        return GenerateResponse(
            request_id=request_id,
            provider=self.name,
            model=request.model,
            prompt_version=str(data.get("prompt_version") or request.prompt_version),
            usage=usage,
            latency_ms=0.0,
            raw_response_reference=f"fake:{fixture_name}:{request_id}",
            parsed_output=parsed_output,
            error=error,
        )


def _text_fixture_name(task_type: str) -> str:
    if task_type in EXPERIMENT_EVAL_FIXTURES:
        return EXPERIMENT_EVAL_FIXTURES[task_type]
    if task_type in STYLE_VALIDATION_FIXTURES:
        return STYLE_VALIDATION_FIXTURES[task_type]
    if task_type in CHAPTER_SUMMARY_FIXTURES:
        return CHAPTER_SUMMARY_FIXTURES[task_type]
    if task_type in SCENE_SUMMARY_FIXTURES:
        return SCENE_SUMMARY_FIXTURES[task_type]
    if task_type in EXTRACT_CANDIDATE_FIXTURES:
        return EXTRACT_CANDIDATE_FIXTURES[task_type]
    if task_type in SCENE_DRAFT_FIXTURES:
        return SCENE_DRAFT_FIXTURES[task_type]
    if task_type in SCENE_PLAN_FIXTURES:
        return SCENE_PLAN_FIXTURES[task_type]
    if task_type in STRUCTURED_INVALID_TASK_TYPES:
        return "structured_invalid.json"
    if task_type in STRUCTURED_OK_TASK_TYPES:
        return "structured_ok.json"
    return "text_ok.json"


def _structured_fixture_name(task_type: str) -> str:
    if task_type in EXPERIMENT_EVAL_FIXTURES:
        return EXPERIMENT_EVAL_FIXTURES[task_type]
    if task_type in STYLE_VALIDATION_FIXTURES:
        return STYLE_VALIDATION_FIXTURES[task_type]
    if task_type in EXTRACT_CANDIDATE_FIXTURES:
        return EXTRACT_CANDIDATE_FIXTURES[task_type]
    if task_type in SCENE_PLAN_FIXTURES:
        return SCENE_PLAN_FIXTURES[task_type]
    if task_type in STRUCTURED_INVALID_TASK_TYPES:
        return "structured_invalid.json"
    return "structured_ok.json"


def _error_from_fixture(data: dict[str, Any]) -> GenerateError | None:
    raw = data.get("error")
    if not isinstance(raw, dict) or not raw.get("code"):
        return None
    return GenerateError(
        code=str(raw["code"]),
        message=str(raw.get("message") or "Fake Provider fixture error"),
    )
