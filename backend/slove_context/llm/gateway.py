"""LLM Gateway: timeout, backoff, and retry around a Provider (node 3.2).

Retries are allowed only for idempotent generate_* reads that have no
persist side effects. generate_text / generate_structured are provider-level
reads: they do not write Canon, Scene Draft, or audit+state. If a generate
call is retried, the same request is sent again and that must be safe.

The gateway does not blindly retry non-idempotent writes. A future write
or side-effect operation (persist, commit, approve, Canon write, save draft)
must use invoke_once, which runs exactly once. If audit+state has already
been written, do not retry that write.

v1 wraps FakeProvider only. No live vendor HTTP. No Scene Plan job.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, replace
from typing import TypeVar
from uuid import uuid4

from slove_context.audit import AuditWriter
from slove_context.llm.errors import (
    NonIdempotentRetryError,
    ProviderTimeoutError,
    ProviderTransientError,
    RetriesExhaustedError,
    StructuredParseError,
)
from slove_context.llm.provider import Provider
from slove_context.llm.redact import redact_llm
from slove_context.llm.types import GenerateRequest, GenerateResponse
from slove_context.logging import get_llm_logger

T = TypeVar("T")

IDEMPOTENT_GENERATE_OPS = frozenset({"generate_text", "generate_structured"})

# Writes / side effects are never retried, even if they raise a transient error.
WRITE_OPERATIONS = frozenset(
    {
        "write",
        "persist",
        "commit",
        "approve",
        "canon_write",
        "save_draft",
        "persist_generation_state",
        "audit_and_state",
    }
)

RETRYABLE_ERROR_CODES = frozenset({"timeout", "transient", "provider_timeout"})
NON_RETRYABLE_ERROR_CODES = frozenset({"structured_parse_failed", "invalid_request"})


@dataclass(frozen=True)
class RetryPolicy:
    """Timeout, exponential backoff, and max retries for generate_* only."""

    timeout_s: float = 5.0
    max_retries: int = 2
    backoff_base_s: float = 0.05
    backoff_multiplier: float = 2.0
    max_backoff_s: float = 2.0


def backoff_delay_s(attempt: int, policy: RetryPolicy) -> float:
    """Delay after a failed attempt (1-based) before the next try."""
    delay = policy.backoff_base_s * (policy.backoff_multiplier ** (attempt - 1))
    return min(delay, policy.max_backoff_s)


class LlmGateway(Provider):
    """Single-vendor wrapper. Retries only idempotent generate_* reads."""

    def __init__(
        self,
        provider: Provider,
        *,
        policy: RetryPolicy | None = None,
        audit_writer: AuditWriter | None = None,
        sleep: Callable[[float], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._provider = provider
        self.policy = policy or RetryPolicy()
        self._audit_writer = audit_writer
        self._sleep = sleep or time.sleep
        self._logger = logger or get_llm_logger()

    @property
    def name(self) -> str:
        return self._provider.name

    def generate_text(self, request: GenerateRequest) -> GenerateResponse:
        return self._run_generate("generate_text", self._provider.generate_text, request)

    def generate_structured(self, request: GenerateRequest) -> GenerateResponse:
        return self._run_generate(
            "generate_structured",
            self._provider.generate_structured,
            request,
        )

    def invoke_once(self, operation: str, fn: Callable[[], T]) -> T:
        """Run a write / side-effect path exactly once. Never retried.

        Use this when the callback already writes audit+state, or when a
        future persist / Canon / draft write is added. generate_* must not
        be used as a persist wrapper.
        """
        if operation in IDEMPOTENT_GENERATE_OPS:
            raise ValueError("use generate_text / generate_structured for reads")
        if not _is_write_operation(operation):
            raise NonIdempotentRetryError(
                f"Operation '{operation}' is not an idempotent generate_* read "
                "and is not a documented write. Refusing to retry or guess."
            )
        return fn()

    def _run_generate(
        self,
        operation: str,
        fn: Callable[[GenerateRequest], GenerateResponse],
        request: GenerateRequest,
    ) -> GenerateResponse:
        if operation not in IDEMPOTENT_GENERATE_OPS:
            raise NonIdempotentRetryError(
                f"Retries are allowed only for {sorted(IDEMPOTENT_GENERATE_OPS)}"
            )
        if _is_write_operation(operation):
            raise NonIdempotentRetryError(
                f"Refusing to retry write operation '{operation}'"
            )

        last_error: BaseException | None = None
        max_attempts = self.policy.max_retries + 1
        request_id = str(uuid4())
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._call_with_timeout(fn, request)
            except Exception as exc:
                last_error = exc
                retryable = _is_retryable_exception(exc)
                if retryable and attempt < max_attempts:
                    self._log_attempt(operation, request, request_id, attempt, error=exc)
                    self._sleep(backoff_delay_s(attempt, self.policy))
                    continue
                if retryable:
                    exhausted = RetriesExhaustedError(
                        f"{operation} failed after {attempt} attempt(s)"
                    )
                    exhausted.__cause__ = exc
                    self._finish(operation, request, request_id, attempt, error=exhausted)
                    raise exhausted from exc
                self._finish(operation, request, request_id, attempt, error=exc)
                raise

            if response.error is not None and _is_retryable_error_code(response.error.code):
                last_error = ProviderTransientError(response.error.code)
                if attempt < max_attempts:
                    self._log_attempt(
                        operation, request, request_id, attempt, error=last_error
                    )
                    self._sleep(backoff_delay_s(attempt, self.policy))
                    continue
                exhausted = RetriesExhaustedError(
                    f"{operation} failed after {attempt} attempt(s)"
                )
                self._finish(operation, request, request_id, attempt, response=response)
                raise exhausted from last_error

            finalized = replace(response, request_id=request_id)
            self._finish(operation, request, request_id, attempt, response=finalized)
            return finalized

        raise RetriesExhaustedError(f"{operation} failed") from last_error

    def _call_with_timeout(
        self,
        fn: Callable[[GenerateRequest], GenerateResponse],
        request: GenerateRequest,
    ) -> GenerateResponse:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn, request)
            started = time.perf_counter()
            try:
                response = future.result(timeout=self.policy.timeout_s)
            except FuturesTimeout as exc:
                future.cancel()
                raise ProviderTimeoutError(
                    f"generate exceeded timeout_s={self.policy.timeout_s}"
                ) from exc
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            return replace(response, latency_ms=latency_ms)

    def _log_attempt(
        self,
        operation: str,
        request: GenerateRequest,
        request_id: str,
        attempt: int,
        *,
        error: BaseException,
    ) -> None:
        payload = redact_llm(
            {
                "operation": f"llm.{operation}",
                "request_id": request_id,
                "correlation_id": request.correlation_id,
                "provider": self.name,
                "model": request.model,
                "task_type": request.task_type,
                "prompt_version": request.prompt_version,
                "attempt": attempt,
                "system_prompt": request.system_prompt,
                "user_prompt": request.user_prompt,
                "error": type(error).__name__,
            }
        )
        self._logger.info("llm generate retry", extra={"log_payload": payload})

    def _finish(
        self,
        operation: str,
        request: GenerateRequest,
        request_id: str,
        attempt: int,
        *,
        response: GenerateResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        payload = redact_llm(_finish_payload(operation, request, request_id, attempt, response, error))
        self._logger.info("llm generate complete", extra={"log_payload": payload})
        if self._audit_writer is None:
            return
        # One audit write after the retry loop. Never written mid-retry.
        after_json = payload if isinstance(payload, dict) else {"payload": payload}
        self._audit_writer.write(
            actor_type="system",
            action=f"llm.{operation}",
            resource_type="llm_generate",
            resource_id=request_id,
            after_json=after_json,
            correlation_id=request.correlation_id,
        )


def _finish_payload(
    operation: str,
    request: GenerateRequest,
    request_id: str,
    attempt: int,
    response: GenerateResponse | None,
    error: BaseException | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "operation": f"llm.{operation}",
        "request_id": request_id,
        "correlation_id": request.correlation_id,
        "provider": response.provider if response is not None else None,
        "model": request.model,
        "task_type": request.task_type,
        "prompt_version": (
            response.prompt_version if response is not None else request.prompt_version
        ),
        "attempt": attempt,
        "system_prompt": request.system_prompt,
        "user_prompt": request.user_prompt,
        "parsed_output": response.parsed_output if response is not None else None,
    }
    if response is not None:
        payload["usage"] = response.usage.to_dict()
        payload["latency_ms"] = response.latency_ms
        payload["raw_response_reference"] = response.raw_response_reference
        payload["error"] = response.error.to_dict() if response.error is not None else None
    if error is not None:
        payload["error"] = {"code": type(error).__name__, "message": str(error)}
    return payload


def _is_write_operation(operation: str) -> bool:
    norm = operation.strip().lower().replace("-", "_")
    if norm in WRITE_OPERATIONS:
        return True
    return any(token in norm for token in ("write", "persist", "commit", "approve", "save"))


def _is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, (StructuredParseError, NonIdempotentRetryError, ValueError)):
        return False
    return isinstance(exc, (ProviderTimeoutError, ProviderTransientError, TimeoutError))


def _is_retryable_error_code(code: str) -> bool:
    if code in NON_RETRYABLE_ERROR_CODES:
        return False
    return code in RETRYABLE_ERROR_CODES
