"""DeepSeek Provider (node UI.4).

OpenAI-compatible Chat Completions for one-scene Scene Draft prose.
generate_* are idempotent reads: no Canon persist, no draft persist,
no audit+state write. Scene Draft persistence stays in scene_draft.

Official cheap chat model: deepseek-v4-flash.
Do not send retired deepseek-chat / deepseek-reasoner.
Do not send deepseek-v4-pro.

The API key is read only from DEEPSEEK_API_KEY. Empty / missing refuses
before any HTTP. The key is never logged, returned, or stored.
Authorization headers must be redacted by callers (1.3 policy).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import Any
from uuid import uuid4

import httpx

from slove_context.llm.errors import (
    MissingApiKeyError,
    ProviderHttpError,
    ProviderTimeoutError,
    ProviderTransientError,
    StructuredParseError,
)
from slove_context.llm.provider import Provider
from slove_context.llm.types import (
    GenerateError,
    GenerateRequest,
    GenerateResponse,
    Usage,
)

DEEPSEEK_PROVIDER_NAME = "deepseek"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_THINKING_DISABLED: dict[str, str] = {"type": "disabled"}

DeepSeekHttpPost = Callable[
    [str, dict[str, str], dict[str, Any], float],
    "DeepSeekHttpResult",
]


class DeepSeekHttpResult:
    """Transport result. body is parsed JSON when present; never log it."""

    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.text = text


def deepseek_api_key_configured(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """True when DEEPSEEK_API_KEY is non-empty. Never returns the key."""
    env = environ if environ is not None else os.environ
    return bool((env.get(DEEPSEEK_API_KEY_ENV) or "").strip())


def _read_api_key() -> str:
    return (os.environ.get(DEEPSEEK_API_KEY_ENV) or "").strip()


class DeepSeekProvider(Provider):
    """Cheap-chat DeepSeek client. Safe to retry: no persist side effects."""

    name = DEEPSEEK_PROVIDER_NAME

    def __init__(
        self,
        *,
        http_post: DeepSeekHttpPost | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._http_post = http_post or _httpx_post
        self._timeout_s = timeout_s
        self.calls = 0

    def generate_text(self, request: GenerateRequest) -> GenerateResponse:
        self.calls += 1
        payload = self._chat_payload(request)
        raw = self._post_chat(payload)
        text = _message_text(raw)
        error = None
        if not text.strip():
            error = GenerateError(
                code="empty_prose",
                message="DeepSeek returned empty chat content",
            )
            text_out: Any = None
        else:
            text_out = text
        return self._response(request, parsed_output=text_out, raw=raw, error=error)

    def generate_structured(self, request: GenerateRequest) -> GenerateResponse:
        self.calls += 1
        payload = self._chat_payload(request)
        raw = self._post_chat(payload)
        text = _message_text(raw)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StructuredParseError(
                "DeepSeek structured output is not valid JSON"
            ) from exc
        if not isinstance(parsed, (dict, list)):
            raise StructuredParseError(
                "DeepSeek structured output must decode to an object or array"
            )
        return self._response(request, parsed_output=parsed, raw=raw, error=None)

    def _chat_payload(self, request: GenerateRequest) -> dict[str, Any]:
        return {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "thinking": dict(DEEPSEEK_THINKING_DISABLED),
        }

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        key = _read_api_key()
        if not key:
            raise MissingApiKeyError(
                "DEEPSEEK_API_KEY is missing or empty. "
                "DeepSeek generation refused. No HTTP sent. No prose persisted."
            )
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        try:
            result = self._http_post(
                DEEPSEEK_CHAT_URL, headers, payload, self._timeout_s
            )
        except (MissingApiKeyError, ProviderHttpError, ProviderTimeoutError):
            raise
        except ProviderTransientError:
            raise
        except Exception as exc:
            raise ProviderTransientError("deepseek transport failed") from exc
        if result.status_code >= 400:
            raise ProviderHttpError(
                result.status_code,
                f"DeepSeek HTTP {result.status_code}. No prose persisted. Not Canon.",
            )
        if not isinstance(result.payload, dict):
            raise ProviderHttpError(
                result.status_code or 502,
                "DeepSeek response is not a JSON object. No prose persisted.",
            )
        return result.payload

    def _response(
        self,
        request: GenerateRequest,
        *,
        parsed_output: Any,
        raw: dict[str, Any],
        error: GenerateError | None,
    ) -> GenerateResponse:
        usage_value = raw.get("usage")
        usage_raw: dict[str, Any] = usage_value if isinstance(usage_value, dict) else {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
            completion_tokens=int(usage_raw.get("completion_tokens", 0)),
            total_tokens=int(usage_raw.get("total_tokens", 0)),
            cost_amount=float(usage_raw.get("cost_amount", 0.0)),
            cost_currency=str(usage_raw.get("cost_currency", "USD")),
        )
        request_id = str(raw.get("id") or uuid4())
        return GenerateResponse(
            request_id=request_id,
            provider=self.name,
            model=DEEPSEEK_MODEL,
            prompt_version=request.prompt_version,
            usage=usage,
            latency_ms=0.0,
            raw_response_reference=f"deepseek:{request_id}",
            parsed_output=parsed_output,
            error=error,
        )


def _message_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    if isinstance(first.get("text"), str):
        return str(first["text"])
    return ""


def _httpx_post(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_s: float,
) -> DeepSeekHttpResult:
    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ProviderTimeoutError(
            f"DeepSeek chat completions exceeded timeout_s={timeout_s}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderTransientError("deepseek http transport failed") from exc
    parsed: dict[str, Any] | None
    try:
        loaded = response.json()
        parsed = loaded if isinstance(loaded, dict) else None
    except ValueError:
        parsed = None
    return DeepSeekHttpResult(
        status_code=response.status_code,
        payload=parsed,
        text=response.text,
    )
