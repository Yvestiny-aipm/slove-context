"""LLM Gateway request / response types (node 3.2).

GenerateRequest / GenerateResponse are the only I/O shapes the Provider
and LlmGateway accept. This node does not define Scene Plan or Scene Draft
prompts, and does not persist Canon or scene state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


REQUEST_REQUIRED_FIELDS = (
    "model",
    "system_prompt",
    "user_prompt",
    "temperature",
    "max_tokens",
    "correlation_id",
    "task_type",
)

RESPONSE_REQUIRED_FIELDS = (
    "request_id",
    "provider",
    "model",
    "prompt_version",
    "usage",
    "latency_ms",
    "raw_response_reference",
    "parsed_output",
    "error",
)

USAGE_TOKEN_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
)

USAGE_COST_FIELDS = (
    "cost_amount",
    "cost_currency",
)


@dataclass(frozen=True)
class Usage:
    """Token counts and cost recorded for one provider call."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_amount: float
    cost_currency: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GenerateError:
    """Structured error. Message must not include full Prompt or prose."""

    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GenerateRequest:
    """Provider input. All listed fields are required for v1."""

    model: str
    system_prompt: str
    user_prompt: str
    temperature: float
    max_tokens: int
    correlation_id: str
    task_type: str
    prompt_version: str = "fake-v1"

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model is required")
        if not self.correlation_id.strip():
            raise ValueError("correlation_id is required")
        if not self.task_type.strip():
            raise ValueError("task_type is required")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.temperature < 0:
            raise ValueError("temperature must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GenerateResponse:
    """Provider output. raw_response_reference is an id/ref, never a raw body."""

    request_id: str
    provider: str
    model: str
    prompt_version: str
    usage: Usage
    latency_ms: float
    raw_response_reference: str
    parsed_output: Any
    error: GenerateError | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["usage"] = self.usage.to_dict()
        payload["error"] = self.error.to_dict() if self.error is not None else None
        return payload


def request_field_names() -> tuple[str, ...]:
    return tuple(item.name for item in fields(GenerateRequest))


def response_field_names() -> tuple[str, ...]:
    return tuple(item.name for item in fields(GenerateResponse))
