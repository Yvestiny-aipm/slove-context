"""LLM log redaction (node 3.2). Reuses node 1.3 audit.redact.

Full Prompt and prose bodies are never kept in logs. Values become a
reference id or ``[REDACTED]``. raw_response bodies are not logged — only
``raw_response_reference``.
"""

from __future__ import annotations

from typing import Any

from slove_context.audit import redact as audit_redact

# Keys whose values are Prompt or prose if a caller logs a raw request/response.
_LLM_BODY_KEYS = frozenset(
    {
        "parsed_output",
        "output_text",
        "completion",
        "raw_response",
        "raw_body",
        "model_output",
    }
)


def _walk(value: Any) -> Any:
    if isinstance(value, dict):
        walked: dict[str, Any] = {}
        for key, item in value.items():
            norm = str(key).strip().lower().replace("-", "_")
            if norm in _LLM_BODY_KEYS:
                walked[str(key)] = audit_redact({"body": item})["body"]
            else:
                walked[str(key)] = _walk(item)
        return walked
    if isinstance(value, list):
        return [_walk(item) for item in value]
    return value


def redact_llm(value: Any) -> Any:
    """Redact secrets, Prompt, and prose using the 1.3 policy."""
    return audit_redact(_walk(value))
