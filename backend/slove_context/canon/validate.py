"""Explicit field validation for Canon writes (node 2.2).

No approved canon-fact schema exists under contracts/; validation is
local and required. Unvalidated input is rejected.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from slove_context.canon.models import (
    FACT_STATUSES,
    normalize_entity_type,
    normalize_source_type,
)


class CanonValidationError(ValueError):
    def __init__(self, error: str, message: str) -> None:
        self.error = error
        self.message = message
        super().__init__(message)


def require_nonempty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonValidationError(
            "invalid_field",
            f"{field} is required and must be a non-empty string.",
        )
    return value.strip()


def require_uuid(value: Any, field: str) -> str:
    text = require_nonempty_str(value, field)
    try:
        return str(UUID(text))
    except ValueError as exc:
        raise CanonValidationError(
            "invalid_uuid",
            f"{field} must be a UUID.",
        ) from exc


def require_entity_type(value: Any) -> str:
    raw = require_nonempty_str(value, "entity_type")
    normalized = normalize_entity_type(raw)
    if normalized is None:
        raise CanonValidationError(
            "invalid_entity_type",
            "entity_type must be a generic entity "
            "(character/角色, location/地点, item/物品, "
            "organization/组织, world_rule/规则).",
        )
    return normalized


def require_source_type(value: Any) -> str:
    raw = require_nonempty_str(value, "source_type")
    normalized = normalize_source_type(raw)
    if normalized is None:
        raise CanonValidationError(
            "invalid_source_type",
            "source_type must be prose (散文 / 场景草稿) or editor (主编 / 规格).",
        )
    return normalized


def require_value_json(value: Any) -> Any:
    if value is None:
        raise CanonValidationError(
            "invalid_value_json",
            "value_json is required and cannot be null.",
        )
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    raise CanonValidationError(
        "invalid_value_json",
        "value_json must be JSON (object, array, string, number, or bool).",
    )


def reject_create_as_active(status: Any) -> None:
    if status is None:
        return
    if not isinstance(status, str):
        raise CanonValidationError(
            "invalid_fact_status",
            "status must be a string when provided.",
        )
    cleaned = status.strip()
    if not cleaned:
        return
    if cleaned not in FACT_STATUSES:
        raise CanonValidationError(
            "invalid_fact_status",
            "status must be a Canon Fact state from node 0.3.",
        )
    if cleaned != "NotInCanon":
        raise CanonValidationError(
            "unapproved_fact_cannot_be_activated",
            "Creating a Canon Fact always produces NotInCanon. "
            "Only the human 主编 can later approve it to Active. "
            "No auto-approval path exists. Evidence is not Canon.",
        )
