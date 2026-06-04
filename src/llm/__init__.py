"""The swappable AI boundary.

`get_client()` returns a real Anthropic client if ANTHROPIC_API_KEY is set,
otherwise the deterministic mock. This is the single seam where the model
call lives — every other module talks to this interface.
"""
from __future__ import annotations

import os

from .base import LLMClient, LLMResponse
from .mock import MockLLM

__all__ = ["LLMClient", "LLMResponse", "get_client"]


def get_client() -> LLMClient:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return MockLLM()
    try:
        from .anthropic_client import AnthropicLLM

        return AnthropicLLM(api_key=api_key)
    except Exception:
        # If the real client can't load (missing SDK, network, etc.), fall
        # back to the mock — `make run` must work offline.
        return MockLLM()
