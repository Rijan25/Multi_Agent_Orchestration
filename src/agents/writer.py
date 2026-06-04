"""Writer: drafts the customer-facing summary.

This is the only agent that calls the LLM. It is handed the findings reference
only — never raw or cleaned data — so messy input physically cannot reach the
writer's context. The prompt embeds findings as a fenced JSON block so the
mock LLM can parse them deterministically; a real model receives the same.
"""
from __future__ import annotations

import json
import time
from typing import Any

from ..llm import get_client
from ..schemas import Envelope, Provenance, Tokens, WriterArtifact


SYSTEM_PROMPT = (
    "You are the Writer agent in a multi-agent pipeline. You receive a list of "
    "findings, each with an id, a claim, a metric value, and an evidence_ref. "
    "Your job is to write a brief, customer-ready summary that cites only the "
    "findings provided. You MUST set claims_used to the exact list of finding "
    "ids you cite — you may not invent ids."
)


def build_user_prompt(findings: list[dict[str, Any]]) -> str:
    return (
        "Write a summary citing only the findings below. Return JSON with "
        "summary_text, claims_used (list of finding ids), and sections.\n\n"
        "<findings>\n"
        + json.dumps(findings, indent=2)
        + "\n</findings>"
    )


def run(findings: list[dict[str, Any]]) -> tuple[WriterArtifact, Envelope]:
    client = get_client()
    user = build_user_prompt(findings)
    schema_hint = {
        "summary_text": "string",
        "claims_used": ["string"],
        "sections": ["string"],
    }
    start = time.perf_counter()
    resp = client.complete_json(
        system=SYSTEM_PROMPT,
        user=user,
        schema_hint=schema_hint,
        model="claude-opus-4-7",
    )
    artifact = WriterArtifact(
        summary_text=resp.parsed.get("summary_text", ""),
        claims_used=resp.parsed.get("claims_used", []),
        sections=resp.parsed.get("sections", []),
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    envelope = Envelope(
        status="ok" if artifact.summary_text else "failed",
        agent="writer",
        confidence=0.9 if artifact.summary_text else 0.0,
        provenance=Provenance(
            model=resp.model,
            inputs=[],
            tokens=Tokens(**{"in": resp.tokens_in, "out": resp.tokens_out}),
            latency_ms=latency_ms,
        ),
    )
    return artifact, envelope
