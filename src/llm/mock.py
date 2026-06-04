"""Deterministic mock LLM.

The writer is the only agent that asks the LLM for free-form output.
The mock parses the findings out of the prompt and emits a structured
summary that cites each finding id. This means `make run` and `make test`
work offline and produce identical output every time.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from .base import LLMResponse


SECTION_TEMPLATES = {
    "headline": "Over the analyzed window, {headline_claim}.",
    "drivers": "Key drivers identified by the analysts: {drivers}.",
    "risks": "Risks and caveats: {risks}.",
}


def _approx_tokens(text: str) -> int:
    # Crude approximation — good enough for a deterministic mock ledger.
    return max(1, len(text) // 4)


class MockLLM:
    name = "mock"

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_hint: dict[str, Any],
        model: str = "default",
    ) -> LLMResponse:
        start = time.perf_counter()
        findings = _extract_findings(user)
        summary, sections, claims_used = _render_summary(findings)
        parsed = {
            "summary_text": summary,
            "claims_used": claims_used,
            "sections": sections,
        }
        text = json.dumps(parsed, indent=2)
        latency_ms = int((time.perf_counter() - start) * 1000) + 12
        return LLMResponse(
            text=text,
            parsed=parsed,
            model=f"mock:{model}",
            tokens_in=_approx_tokens(system) + _approx_tokens(user),
            tokens_out=_approx_tokens(text),
            latency_ms=latency_ms,
        )


def _extract_findings(user_prompt: str) -> list[dict[str, Any]]:
    """The writer prompt embeds the findings list as a fenced JSON block.
    We pull it out and parse — anything else is treated as no findings."""
    match = re.search(r"<findings>(.*?)</findings>", user_prompt, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return []


def _render_summary(findings: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    if not findings:
        return (
            "No findings were available to summarize.",
            ["headline"],
            [],
        )
    headline = findings[0]
    drivers_text = "; ".join(
        f"{f['claim']} ({f['metric']} = {f['value']})" for f in findings
    )
    risks_text = "; ".join(
        c for f in findings for c in f.get("caveats", [])
    ) or "no material risks flagged by the analysts"
    parts = [
        SECTION_TEMPLATES["headline"].format(headline_claim=headline["claim"].lower()),
        SECTION_TEMPLATES["drivers"].format(drivers=drivers_text),
        SECTION_TEMPLATES["risks"].format(risks=risks_text),
    ]
    summary = " ".join(parts)
    return summary, ["headline", "drivers", "risks"], [f["id"] for f in findings]
