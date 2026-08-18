"""Swappable LLM Gateway (node 3.2). Fake Provider only.

No live vendor HTTP. Scene Plan jobs live in scene_plan (node 3.3) and
call generate_structured. Scene Draft jobs live in scene_draft (node 3.4)
and call generate_text. This package does not persist plans or drafts.
No Canon writes. generate_* are idempotent reads with no persist side effects.
"""

from slove_context.llm.errors import (
    LlmError,
    NonIdempotentRetryError,
    ProviderTimeoutError,
    ProviderTransientError,
    RetriesExhaustedError,
    StructuredParseError,
)
from slove_context.llm.fake import FakeProvider
from slove_context.llm.gateway import IDEMPOTENT_GENERATE_OPS, LlmGateway, RetryPolicy
from slove_context.llm.provider import Provider
from slove_context.llm.types import (
    GenerateError,
    GenerateRequest,
    GenerateResponse,
    Usage,
)

__all__ = [
    "IDEMPOTENT_GENERATE_OPS",
    "FakeProvider",
    "GenerateError",
    "GenerateRequest",
    "GenerateResponse",
    "LlmError",
    "LlmGateway",
    "NonIdempotentRetryError",
    "Provider",
    "ProviderTimeoutError",
    "ProviderTransientError",
    "RetriesExhaustedError",
    "RetryPolicy",
    "StructuredParseError",
    "Usage",
]
