"""LLM log redaction (node 3.2). Reuses node 1.3 audit.redact.

Full Prompt and prose bodies are never kept in logs. Values become a
reference id or ``[REDACTED]``. raw_response bodies are not logged — only
``raw_response_reference``.

``prompt_version`` and ``prompt_tokens`` are metadata (version id / count),
not Prompt text. They are renamed around the 1.3 walker so they are not
treated as Prompt bodies.
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

# 1.3 treats any key containing "prompt" as Prompt text. These are not.
_METADATA_AWAY = {
    "prompt_version": "llm_version_id",
    "prompt_tokens": "llm_input_token_count",
}
_METADATA_BACK = {value: key for key, value in _METADATA_AWAY.items()}


def _rename_keys(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, dict):
        renamed: dict[str, Any] = {}
        for key, item in value.items():
            next_key = mapping.get(str(key), str(key))
            renamed[next_key] = _rename_keys(item, mapping)
        return renamed
    if isinstance(value, list):
        return [_rename_keys(item, mapping) for item in value]
    return value


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
    prepared = _rename_keys(_walk(value), _METADATA_AWAY)
    return _rename_keys(audit_redact(prepared), _METADATA_BACK)
