"""Swappable Provider interface (node 3.2).

v1 ships FakeProvider only. No OpenAI / Anthropic / HTTP client.
generate_text and generate_structured are idempotent provider-level reads:
they must not persist Canon, Scene Draft, audit+state, or any other write.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from slove_context.llm.types import GenerateRequest, GenerateResponse


class Provider(ABC):
    """One writing-model vendor at a time. Only Fake is implemented in v1."""

    name: str

    @abstractmethod
    def generate_text(self, request: GenerateRequest) -> GenerateResponse:
        """Idempotent read. No persist side effects."""

    @abstractmethod
    def generate_structured(self, request: GenerateRequest) -> GenerateResponse:
        """Idempotent read that parses fixture/output JSON. No persist side effects."""
