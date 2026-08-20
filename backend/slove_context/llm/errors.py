"""LLM Gateway errors (node 3.2)."""

from __future__ import annotations


class LlmError(Exception):
    """Base error for the LLM Gateway."""


class ProviderTimeoutError(LlmError):
    """A single generate_* attempt exceeded the configured timeout."""


class ProviderTransientError(LlmError):
    """Retryable provider-level failure. Safe only for idempotent generate_*."""


class StructuredParseError(LlmError):
    """generate_structured received a body that could not be parsed.

    Non-retryable: the provider call already completed.
    """


class RetriesExhaustedError(LlmError):
    """Configured max retries were used up on an idempotent generate_* read."""


class NonIdempotentRetryError(LlmError):
    """Retries were refused because the operation is a write or side effect.

    The gateway never blindly retries non-idempotent writes. If a caller has
    already persisted audit + state, they must not ask generate_* to retry
    that persist. Use invoke_once for those paths; it runs exactly once.
    """


class MissingApiKeyError(LlmError):
    """Vendor env key is missing or empty. Refuse before any HTTP."""


class ProviderHttpError(LlmError):
    """Vendor HTTP returned 4xx/5xx. generate_* is still a read: no persist."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)
