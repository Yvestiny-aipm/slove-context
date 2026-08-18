"""Draft body metrics (node 3.4). Hash + counts; never log the body."""

from __future__ import annotations

import hashlib
import re


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_TOKEN_RE = re.compile(r"\S+")


def content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def character_count(body: str) -> int:
    return len(body)


def word_count_estimate(body: str) -> int:
    """Estimate words for mixed Chinese / whitespace-separated text.

    Each CJK character counts as one unit. Remaining non-CJK tokens
    (Latin words, numbers) are counted separately.
    """
    stripped = body.strip()
    if not stripped:
        return 0
    cjk = len(_CJK_RE.findall(stripped))
    non_cjk = 0
    for token in _TOKEN_RE.findall(stripped):
        leftover = _CJK_RE.sub("", token)
        if leftover:
            non_cjk += 1
    return cjk + non_cjk
