"""Real Anthropic API client. Used only when ANTHROPIC_API_KEY is set.

Lazily imports the SDK so a missing dependency falls back to the mock
without breaking `make run`. If you want to use this in production:

    pip install anthropic
    export ANTHROPIC_API_KEY=...
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from .base import LLMResponse


DEFAULT_MODEL = "claude-opus-4-7"


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        # Lazy import keeps make setup minimal — no anthropic SDK required.
        import anthropic  # noqa: F401  (raises ImportError if missing)

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_hint: dict[str, Any],
        model: str = "default",
    ) -> LLMResponse:
        chosen_model = self._model if model == "default" else model
        start = time.perf_counter()
        msg = self._client.messages.create(
            model=chosen_model,
            max_tokens=1024,
            system=system + "\nRespond with valid JSON only.",
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"{user}\n\nSchema hint (informational):\n"
                        f"```json\n{json.dumps(schema_hint, indent=2)}\n```"
                    ),
                }
            ],
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        text = "".join(block.text for block in msg.content if hasattr(block, "text"))
        parsed = _parse_json(text)
        usage = getattr(msg, "usage", None)
        return LLMResponse(
            text=text,
            parsed=parsed,
            model=chosen_model,
            tokens_in=getattr(usage, "input_tokens", 0) if usage else 0,
            tokens_out=getattr(usage, "output_tokens", 0) if usage else 0,
            latency_ms=latency_ms,
        )


def _parse_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
