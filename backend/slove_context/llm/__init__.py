"""Swappable LLM Gateway (node 3.2 + UI.4 DeepSeek).

Fake Provider remains the default for plan / extract / summary / style /
eval jobs. Node UI.4 adds DeepSeekProvider for one-scene Scene Draft
generate_text only. generate_* stay idempotent reads: no Canon persist,
no draft persist. Scene Draft persistence stays in scene_draft.
"""

from slove_context.llm.deepseek import (
    DEEPSEEK_API_KEY_ENV,
    DEEPSEEK_CHAT_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_PROVIDER_NAME,
    DeepSeekProvider,
    deepseek_api_key_configured,
)
from slove_context.llm.errors import (
    LlmError,
    MissingApiKeyError,
    NonIdempotentRetryError,
    ProviderHttpError,
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
    "DEEPSEEK_API_KEY_ENV",
    "DEEPSEEK_CHAT_URL",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_PROVIDER_NAME",
    "IDEMPOTENT_GENERATE_OPS",
    "DeepSeekProvider",
    "FakeProvider",
    "GenerateError",
    "GenerateRequest",
    "GenerateResponse",
    "LlmError",
    "LlmGateway",
    "MissingApiKeyError",
    "NonIdempotentRetryError",
    "Provider",
    "ProviderHttpError",
    "ProviderTimeoutError",
    "ProviderTransientError",
    "RetriesExhaustedError",
    "RetryPolicy",
    "StructuredParseError",
    "Usage",
    "deepseek_api_key_configured",
]
