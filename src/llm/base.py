"""LLMClient interface. Every model call goes through this seam."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class LLMResponse:
    text: str
    parsed: dict[str, Any]
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


class LLMClient(Protocol):
    name: str

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_hint: dict[str, Any],
        model: str = "default",
    ) -> LLMResponse:
        """Return a JSON-shaped response. The schema_hint tells the model what
        fields and types are expected; callers still validate the result at
        the gate. Mocks may use the hint to fabricate a plausible payload."""
        ...
