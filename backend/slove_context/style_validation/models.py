"""In-process Style Validation run and report records (node 7.2).

Job states: Queued / Running / Succeeded / Failed / Cancelled.
Failure and cancel keep the row. Style findings are not 5.x hard-rule
violations and do not default to blocking Canon submit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RULE_VERSION = "style-rules.v1"
LLM_SCORE_VERSION = "style-llm.v1"
PROMPT_VERSION = "style_validation.v1"
DEFAULT_TASK_TYPE = "style_validation"

RUN_QUEUED = "Queued"
RUN_RUNNING = "Running"
RUN_SUCCEEDED = "Succeeded"
RUN_FAILED = "Failed"
RUN_CANCELLED = "Cancelled"

RUN_STATES = frozenset(
    {RUN_QUEUED, RUN_RUNNING, RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED}
)
RUN_CANCELLABLE_STATES = frozenset({RUN_QUEUED, RUN_RUNNING})
RUN_TERMINAL_STATES = frozenset({RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED})

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_DEFAULT = SEVERITY_WARNING
BLOCKER_SEVERITIES = frozenset(
    {"blocker", "blocking", "Blocker", "Blocking", "error", "Error"}
)

LLM_RAN = "ran"
LLM_SKIPPED = "skipped"
LLM_SKIPPED_NO_GUIDE = "skipped_no_approved_guide"
LLM_REFUSED_UNAPPROVED_GUIDE = "refused_unapproved_guide"
LLM_REFUSED_UNAUTHORIZED_SAMPLE = "refused_unauthorized_sample"
LLM_REFUSED_LIVING_AUTHOR = "refused_living_author_imitation"

RULE_PERSON = "person"
RULE_TENSE = "tense"
RULE_FORBIDDEN = "forbidden_expression"
RULE_LONG_SENTENCE = "long_sentence_ratio"
RULE_PARAGRAPH = "paragraph_length"
RULE_DIALOGUE = "dialogue_ratio"
RULE_NGRAM = "repeated_ngram"
RULE_LLM = "llm_style_conformance"

LIVING_AUTHOR_MARKERS = (
    "在世作家",
    "living author",
    "living_author",
    "imitate_author",
    "imitate_living",
    "仿写在世",
    "模仿在世",
    "仿写作家",
)


@dataclass(frozen=True)
class StyleThresholds:
    """Configurable cut-offs for deterministic checks. Defaults are warnings."""

    long_sentence_chars: int = 80
    long_sentence_ratio: float = 0.35
    max_paragraph_chars: int = 220
    long_paragraph_ratio: float = 0.40
    max_dialogue_ratio: float = 0.55
    min_dialogue_ratio: float = 0.0
    ngram_n: int = 4
    ngram_repeat_threshold: int = 4

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "long_sentence_chars": self.long_sentence_chars,
            "long_sentence_ratio": self.long_sentence_ratio,
            "max_paragraph_chars": self.max_paragraph_chars,
            "long_paragraph_ratio": self.long_paragraph_ratio,
            "max_dialogue_ratio": self.max_dialogue_ratio,
            "min_dialogue_ratio": self.min_dialogue_ratio,
            "ngram_n": self.ngram_n,
            "ngram_repeat_threshold": self.ngram_repeat_threshold,
        }

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> StyleThresholds:
        if not raw:
            return cls()
        defaults = cls()
        return cls(
            long_sentence_chars=_as_int(
                raw.get("long_sentence_chars"), defaults.long_sentence_chars
            ),
            long_sentence_ratio=_as_float(
                raw.get("long_sentence_ratio"), defaults.long_sentence_ratio
            ),
            max_paragraph_chars=_as_int(
                raw.get("max_paragraph_chars"), defaults.max_paragraph_chars
            ),
            long_paragraph_ratio=_as_float(
                raw.get("long_paragraph_ratio"), defaults.long_paragraph_ratio
            ),
            max_dialogue_ratio=_as_float(
                raw.get("max_dialogue_ratio"), defaults.max_dialogue_ratio
            ),
            min_dialogue_ratio=_as_float(
                raw.get("min_dialogue_ratio"), defaults.min_dialogue_ratio
            ),
            ngram_n=_as_int(raw.get("ngram_n"), defaults.ngram_n),
            ngram_repeat_threshold=_as_int(
                raw.get("ngram_repeat_threshold"), defaults.ngram_repeat_threshold
            ),
        )


@dataclass
class StyleFinding:
    rule_id: str
    problem: str
    text_evidence: str
    severity: str
    minimal_fix: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "problem": self.problem,
            "text_evidence": self.text_evidence,
            "severity": coerce_style_severity(self.severity),
            "minimal_fix": self.minimal_fix,
            "blocks_canon_submit": False,
            "is_hard_rule": False,
        }


@dataclass
class StyleValidation:
    id: str
    project_id: str
    scene_id: str
    draft_revision_id: str
    status: str
    created_at: str
    updated_at: str
    created_by: str
    actor_type: str
    rule_version: str = RULE_VERSION
    llm_score_version: str | None = None
    llm_status: str = LLM_SKIPPED
    style_guide_revision_id: str | None = None
    style_sample_ids: list[str] = field(default_factory=list)
    include_llm: bool = False
    thresholds: StyleThresholds = field(default_factory=StyleThresholds)
    findings: list[StyleFinding] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None
    request_refs: list[dict[str, Any]] = field(default_factory=list)
    blocks_canon_submit: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        report = dict(self.report) if self.report else self._build_report()
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "draft_revision_id": self.draft_revision_id,
            "status": self.status,
            "rule_version": self.rule_version,
            "llm_score_version": self.llm_score_version,
            "llm_status": self.llm_status,
            "style_guide_revision_id": self.style_guide_revision_id,
            "style_sample_ids": list(self.style_sample_ids),
            "include_llm": self.include_llm,
            "thresholds": self.thresholds.to_public_dict(),
            "findings": [item.to_public_dict() for item in self.findings],
            "report": report,
            "blocks_canon_submit": False,
            "failure_reason": self.failure_reason,
            "request_refs": [dict(item) for item in self.request_refs],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "actor_type": self.actor_type,
            "is_canon": False,
            "is_approval": False,
            "is_canon_approval": False,
            "writes_canon": False,
            "auto_approved": False,
            "is_validation_run": False,
            "is_hard_rule": False,
            "is_review_queue": False,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        # Never persist 正例 / 反例 / sample body / draft prose / evidence.
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "draft_revision_id": self.draft_revision_id,
            "status": self.status,
            "rule_version": self.rule_version,
            "llm_score_version": self.llm_score_version,
            "llm_status": self.llm_status,
            "style_guide_revision_id": self.style_guide_revision_id,
            "style_sample_ids": list(self.style_sample_ids),
            "include_llm": self.include_llm,
            "finding_count": len(self.findings),
            "finding_rule_ids": [item.rule_id for item in self.findings],
            "finding_severities": [
                coerce_style_severity(item.severity) for item in self.findings
            ],
            "blocks_canon_submit": False,
            "failure_reason": self.failure_reason,
            "request_ref_count": len(self.request_refs),
            "is_canon": False,
            "is_approval": False,
            "is_canon_approval": False,
            "writes_canon": False,
            "auto_approved": False,
            "is_validation_run": False,
            "is_review_queue": False,
        }

    def _build_report(self) -> dict[str, Any]:
        return {
            "rule_version": self.rule_version,
            "llm_score_version": self.llm_score_version,
            "llm_status": self.llm_status,
            "findings": [item.to_public_dict() for item in self.findings],
            "blocks_canon_submit": False,
            "is_validation_run": False,
            "is_hard_rule": False,
            "writes_canon": False,
        }


def coerce_style_severity(raw: str | None) -> str:
    """Style findings default to warning / info. Never a Canon blocker."""
    if raw is None or not str(raw).strip():
        return SEVERITY_DEFAULT
    value = str(raw).strip()
    if value in BLOCKER_SEVERITIES:
        return SEVERITY_WARNING
    lowered = value.lower()
    if lowered == SEVERITY_INFO:
        return SEVERITY_INFO
    if lowered == SEVERITY_WARNING:
        return SEVERITY_WARNING
    return SEVERITY_WARNING


def _as_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _as_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0:
        return default
    return parsed
