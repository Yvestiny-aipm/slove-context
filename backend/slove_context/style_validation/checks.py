"""Deterministic Style Validation checks (node 7.2). No LLM.

Each check is independent, threshold-configurable, and emits warning /
info findings. None of these are 5.x hard rules. None block Canon
submit by default.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from slove_context.style.models import StyleGuide
from slove_context.style_validation.models import (
    RULE_DIALOGUE,
    RULE_FORBIDDEN,
    RULE_LONG_SENTENCE,
    RULE_NGRAM,
    RULE_PARAGRAPH,
    RULE_PERSON,
    RULE_TENSE,
    SEVERITY_WARNING,
    StyleFinding,
    StyleThresholds,
)

_DIALOGUE_RE = re.compile(r"「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"]*\"|'[^']*'")
_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
_FIRST_PERSON = ("我们", "咱们", "俺们", "我", "咱", "俺")
_SECOND_PERSON = ("你们", "您们", "你", "您")
_THIRD_PERSON = ("他们", "她们", "它们", "他", "她", "它")
_PERSON_PATTERN = re.compile(
    "|".join(
        re.escape(token) for token in (*_FIRST_PERSON, *_SECOND_PERSON, *_THIRD_PERSON)
    )
)
_PAST_MARKERS = ("曾经", "已经", "那时", "过了", "了", "过")
_PRESENT_MARKERS = ("正在", "此刻", "如今", "着")
_FUTURE_MARKERS = ("将要", "即将", "将会", "明天")
_WHITESPACE_RE = re.compile(r"[\s\u3000]+")


def run_deterministic_checks(
    body: str,
    *,
    guide: StyleGuide | None,
    thresholds: StyleThresholds | None = None,
) -> list[StyleFinding]:
    cuts = thresholds or StyleThresholds()
    findings: list[StyleFinding] = []
    if guide is not None:
        person = check_person(body, guide.person)
        if person is not None:
            findings.append(person)
        tense = check_tense(body, guide.tense)
        if tense is not None:
            findings.append(tense)
        findings.extend(check_forbidden(body, guide.forbidden_expressions))
    long_sentence = check_long_sentence_ratio(body, cuts)
    if long_sentence is not None:
        findings.append(long_sentence)
    paragraph = check_paragraph_length(body, cuts)
    if paragraph is not None:
        findings.append(paragraph)
    dialogue = check_dialogue_ratio(body, cuts)
    if dialogue is not None:
        findings.append(dialogue)
    ngram = check_repeated_ngram(body, cuts)
    if ngram is not None:
        findings.append(ngram)
    return findings


def check_person(body: str, guide_person: str) -> StyleFinding | None:
    """Detect narrative person drift against the approved Style Guide 人称."""
    expected = classify_person(guide_person)
    narrative = narrative_text(body)
    counts = count_person_markers(narrative)
    drifted = False
    evidence = ""
    if expected == "third":
        if counts["first"] > 0:
            drifted = True
            evidence = _first_marker(narrative, _FIRST_PERSON) or "我"
        elif counts["second"] > 0:
            drifted = True
            evidence = _first_marker(narrative, _SECOND_PERSON) or "你"
    elif expected == "first":
        if counts["first"] == 0 and (counts["second"] > 0 or counts["third"] > 0):
            drifted = True
            evidence = _first_marker(narrative, (*_SECOND_PERSON, *_THIRD_PERSON)) or (
                narrative[:24] if narrative else ""
            )
    elif expected == "second" and counts["second"] == 0:
        drifted = True
        evidence = narrative[:24] if narrative else body[:24]
    if not drifted:
        return None
    return StyleFinding(
        rule_id=RULE_PERSON,
        problem=f"叙述人称与已批准 Style Guide 人称「{guide_person}」不一致。",
        text_evidence=evidence,
        severity=SEVERITY_WARNING,
        minimal_fix=f"把叙述人称改回「{guide_person}」，对话中的人称可保留。",
    )


def check_tense(body: str, guide_tense: str) -> StyleFinding | None:
    """Detect obvious tense-marker drift against the approved Guide 时态."""
    expected = classify_tense(guide_tense)
    narrative = narrative_text(body)
    past = _count_markers(narrative, _PAST_MARKERS)
    present = _count_markers(narrative, _PRESENT_MARKERS)
    future = _count_markers(narrative, _FUTURE_MARKERS)
    drifted = False
    evidence = ""
    if expected == "past" and future > past and future > 0:
        drifted = True
        evidence = _first_marker(narrative, _FUTURE_MARKERS) or "将要"
    elif expected == "present" and (past > present + 1 or future > present + 1):
        drifted = True
        evidence = _first_marker(narrative, (*_PAST_MARKERS, *_FUTURE_MARKERS)) or (
            narrative[:24] if narrative else ""
        )
    elif expected == "future" and future == 0 and past > 0:
        drifted = True
        evidence = _first_marker(narrative, _PAST_MARKERS) or "了"
    if not drifted:
        return None
    return StyleFinding(
        rule_id=RULE_TENSE,
        problem=f"时态标记与已批准 Style Guide 时态「{guide_tense}」明显偏离。",
        text_evidence=evidence,
        severity=SEVERITY_WARNING,
        minimal_fix=f"按「{guide_tense}」调整体貌/时态标记，去掉明显越界的标记。",
    )


def check_forbidden(body: str, forbidden: list[str]) -> list[StyleFinding]:
    """Literal / normalized match against Guide 禁用表达."""
    findings: list[StyleFinding] = []
    if not forbidden:
        return findings
    normalized_body = normalize_text(body)
    seen: set[str] = set()
    for raw in forbidden:
        phrase = raw.strip()
        if not phrase or phrase in seen:
            continue
        seen.add(phrase)
        if phrase in body or normalize_text(phrase) in normalized_body:
            findings.append(
                StyleFinding(
                    rule_id=RULE_FORBIDDEN,
                    problem=f"正文出现 Style Guide 禁用表达「{phrase}」。",
                    text_evidence=phrase,
                    severity=SEVERITY_WARNING,
                    minimal_fix=f"删除或改写「{phrase}」，换用 Guide 允许的词汇。",
                )
            )
    return findings


def check_long_sentence_ratio(
    body: str, thresholds: StyleThresholds
) -> StyleFinding | None:
    sentences = split_sentences(body)
    if not sentences:
        return None
    long_ones = [
        item for item in sentences if len(item) > thresholds.long_sentence_chars
    ]
    ratio = len(long_ones) / len(sentences)
    if ratio <= thresholds.long_sentence_ratio:
        return None
    evidence = long_ones[0][:80]
    return StyleFinding(
        rule_id=RULE_LONG_SENTENCE,
        problem=(
            "超长句比例超过阈值 "
            f"{thresholds.long_sentence_ratio:.2f}（当前 {ratio:.2f}）。"
        ),
        text_evidence=evidence,
        severity=SEVERITY_WARNING,
        minimal_fix="把过长的句子拆成更短的叙述单位，降低超长句比例。",
    )


def check_paragraph_length(
    body: str, thresholds: StyleThresholds
) -> StyleFinding | None:
    paragraphs = split_paragraphs(body)
    if not paragraphs:
        return None
    long_ones = [
        item for item in paragraphs if len(item) > thresholds.max_paragraph_chars
    ]
    ratio = len(long_ones) / len(paragraphs)
    if not long_ones:
        return None
    if (
        ratio <= thresholds.long_paragraph_ratio
        and thresholds.long_paragraph_ratio > 0
        and ratio < 1.0
    ):
        return None
    evidence = long_ones[0][:80]
    return StyleFinding(
        rule_id=RULE_PARAGRAPH,
        problem=(
            "段落长度超过阈值 "
            f"{thresholds.max_paragraph_chars} 字（过长段 {len(long_ones)}）。"
        ),
        text_evidence=evidence,
        severity=SEVERITY_WARNING,
        minimal_fix="在过长段中换行或切段，使单段不超过配置的字数。",
    )


def check_dialogue_ratio(body: str, thresholds: StyleThresholds) -> StyleFinding | None:
    if not body.strip():
        return None
    dialogue_chars = sum(len(item.group(0)) for item in _DIALOGUE_RE.finditer(body))
    ratio = dialogue_chars / max(len(body), 1)
    too_high = ratio > thresholds.max_dialogue_ratio
    too_low = ratio < thresholds.min_dialogue_ratio
    if not too_high and not too_low:
        return None
    evidence = _first_dialogue(body) or body[:24]
    if too_high:
        problem = (
            "对话比例超过阈值 "
            f"{thresholds.max_dialogue_ratio:.2f}（当前 {ratio:.2f}）。"
        )
        fix = "减少对话、补叙述，使对话占比回到阈值以内。"
    else:
        problem = (
            "对话比例低于阈值 "
            f"{thresholds.min_dialogue_ratio:.2f}（当前 {ratio:.2f}）。"
        )
        fix = "补必要对话，或调低 min_dialogue_ratio。"
    return StyleFinding(
        rule_id=RULE_DIALOGUE,
        problem=problem,
        text_evidence=evidence,
        severity=SEVERITY_WARNING,
        minimal_fix=fix,
    )


def check_repeated_ngram(body: str, thresholds: StyleThresholds) -> StyleFinding | None:
    chars = content_chars(body)
    n = thresholds.ngram_n
    if n < 2 or len(chars) < n:
        return None
    grams = [chars[index : index + n] for index in range(len(chars) - n + 1)]
    counts = Counter(grams)
    phrase, count = counts.most_common(1)[0]
    if count < thresholds.ngram_repeat_threshold:
        return None
    return StyleFinding(
        rule_id=RULE_NGRAM,
        problem=(
            f"重复 {n}-gram「{phrase}」出现 {count} 次，"
            f"达到或超过阈值 {thresholds.ngram_repeat_threshold}。"
        ),
        text_evidence=phrase,
        severity=SEVERITY_WARNING,
        minimal_fix=f"改写重复短语「{phrase}」，避免机械复读。",
    )


def classify_person(guide_person: str) -> str:
    text = guide_person.strip()
    if any(token in text for token in ("第一", "一人称")):
        return "first"
    if any(token in text for token in ("第二", "二人称")):
        return "second"
    if any(token in text for token in ("第三", "三人称")):
        return "third"
    return "third"


def classify_tense(guide_tense: str) -> str:
    text = guide_tense.strip()
    if any(token in text for token in ("将来", "未来", "将要")):
        return "future"
    if any(token in text for token in ("现在", "当下", "进行")):
        # 「过去进行」 is past progressive — treat as past.
        if "过去" in text:
            return "past"
        return "present"
    if any(token in text for token in ("过去", "完了", "已然")):
        return "past"
    return "past"


def narrative_text(body: str) -> str:
    return _DIALOGUE_RE.sub(" ", body)


def count_person_markers(text: str) -> dict[str, int]:
    counts = {"first": 0, "second": 0, "third": 0}
    for match in _PERSON_PATTERN.finditer(text):
        token = match.group(0)
        if token in _FIRST_PERSON:
            counts["first"] += 1
        elif token in _SECOND_PERSON:
            counts["second"] += 1
        else:
            counts["third"] += 1
    return counts


def split_sentences(body: str) -> list[str]:
    items = [item.strip() for item in _SENTENCE_RE.findall(body) if item.strip()]
    return items


def split_paragraphs(body: str) -> list[str]:
    items = [item.strip() for item in re.split(r"\n+", body) if item.strip()]
    return items or ([body.strip()] if body.strip() else [])


def content_chars(body: str) -> str:
    chars: list[str] = []
    for char in body:
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if category.startswith(("P", "S")):
            continue
        chars.append(char)
    return "".join(chars)


def normalize_text(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return _WHITESPACE_RE.sub("", folded)


def _count_markers(text: str, markers: tuple[str, ...]) -> int:
    return sum(text.count(marker) for marker in markers)


def _first_marker(text: str, markers: tuple[str, ...]) -> str:
    indexes: list[tuple[int, str]] = []
    for marker in markers:
        found = text.find(marker)
        if found >= 0:
            indexes.append((found, marker))
    if not indexes:
        return ""
    indexes.sort()
    _, marker = indexes[0]
    start = text.find(marker)
    return text[max(0, start - 4) : start + len(marker) + 8]


def _first_dialogue(body: str) -> str:
    match = _DIALOGUE_RE.search(body)
    if match is None:
        return ""
    return match.group(0)[:80]
