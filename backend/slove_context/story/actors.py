"""Actor types for Story Spec writes (node 2.1).

State-machine triggerers (docs/state-machines.md): 系统 / 生成 Agent /
审校 Agent / 人工主编. Only the human 主编 may approve a Spec.
System, generation, and review agents cannot approve. Spec approval is
not Canon approval.
"""

from __future__ import annotations

from dataclasses import dataclass

HUMAN_EDITOR = "human_editor"
SYSTEM = "system"
GENERATION_AGENT = "generation_agent"
REVIEW_AGENT = "review_agent"

ACTOR_TYPE_HEADER = "X-Actor-Type"
ACTOR_ID_HEADER = "X-Actor-Id"

_HUMAN_ALIASES = {
    "human_editor": HUMAN_EDITOR,
    "human": HUMAN_EDITOR,
    "editor": HUMAN_EDITOR,
    "human_chief_editor": HUMAN_EDITOR,
    "人工主编": HUMAN_EDITOR,
    "主编": HUMAN_EDITOR,
}

_NON_HUMAN_ALIASES = {
    "system": SYSTEM,
    "系统": SYSTEM,
    "generation_agent": GENERATION_AGENT,
    "generation": GENERATION_AGENT,
    "generate_agent": GENERATION_AGENT,
    "生成 agent": GENERATION_AGENT,
    "生成agent": GENERATION_AGENT,
    "生成": GENERATION_AGENT,
    "review_agent": REVIEW_AGENT,
    "review": REVIEW_AGENT,
    "审校 agent": REVIEW_AGENT,
    "审校agent": REVIEW_AGENT,
    "审校": REVIEW_AGENT,
}

_ALL_ALIASES = {**_HUMAN_ALIASES, **_NON_HUMAN_ALIASES}

NON_HUMAN_TYPES = frozenset({SYSTEM, GENERATION_AGENT, REVIEW_AGENT})


@dataclass(frozen=True)
class Actor:
    actor_type: str
    actor_id: str | None


class ActorError(ValueError):
    """Actor is missing or not allowed for the requested action."""


def normalize_actor_type(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    if stripped in _ALL_ALIASES:
        return _ALL_ALIASES[stripped]
    lowered = stripped.lower()
    if lowered in _ALL_ALIASES:
        return _ALL_ALIASES[lowered]
    compact = lowered.replace("-", "_").replace(" ", "_")
    if compact in _ALL_ALIASES:
        return _ALL_ALIASES[compact]
    spaced = " ".join(lowered.replace("_", " ").replace("-", " ").split())
    if spaced in _ALL_ALIASES:
        return _ALL_ALIASES[spaced]
    return stripped


def resolve_actor(
    *,
    header_type: str | None,
    header_id: str | None,
    body_type: str | None = None,
    body_id: str | None = None,
) -> Actor:
    actor_type = normalize_actor_type(header_type) or normalize_actor_type(body_type)
    actor_id = _first_nonempty(header_id, body_id)
    if actor_type is None:
        return Actor(actor_type="", actor_id=actor_id)
    return Actor(actor_type=actor_type, actor_id=actor_id)


def require_human_editor(actor: Actor) -> Actor:
    """Approve is a human-only transition. Missing or non-human actors fail."""
    if not actor.actor_type:
        raise ActorError(
            "Approve requires an explicit human actor "
            "(X-Actor-Type: human_editor). System and agents cannot approve."
        )
    if actor.actor_type in NON_HUMAN_TYPES:
        raise ActorError(
            f"Actor '{actor.actor_type}' cannot approve a Story Spec. "
            "Only the human 主编 (human_editor) may approve. "
            "No auto-approval path exists."
        )
    if actor.actor_type != HUMAN_EDITOR:
        raise ActorError(
            f"Actor '{actor.actor_type}' cannot approve a Story Spec. "
            "Only the human 主编 (human_editor) may approve."
        )
    return actor


def _first_nonempty(*values: str | None) -> str | None:
    for value in values:
        if value is None:
            continue
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None
