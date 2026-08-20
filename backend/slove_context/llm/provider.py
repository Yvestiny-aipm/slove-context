"""Swappable Provider interface (node 3.2 + UI.4 DeepSeek).

v1 ships FakeProvider. Node UI.4 adds DeepSeekProvider for Scene Draft
generate_text. generate_* remain idempotent provider-level reads:
they must not persist Canon, Scene Draft, audit+state, or any other write.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from slove_context.llm.types import GenerateRequest, GenerateResponse


class Provider(ABC):
    """One writing-model vendor at a time. Fake plus UI.4 DeepSeek for drafts."""

    name: str

    @abstractmethod
    def generate_text(self, request: GenerateRequest) -> GenerateResponse:
        """Idempotent read. No persist side effects."""

    @abstractmethod
    def generate_structured(self, request: GenerateRequest) -> GenerateResponse:
        """Idempotent read that parses fixture/output JSON. No persist side effects."""
