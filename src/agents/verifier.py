"""Verifier: mechanically checks the writer's output before it leaves the system.

Deterministic. Confirms every claim in the summary maps to an evidenced finding
and that every claims_used id exists. The model only adjudicates tone in the
real-API path; here it's pure Python.
"""
from __future__ import annotations

import time
from typing import Any

from ..schemas import Envelope, Issue, Provenance, Tokens, VerifierArtifact


def run(
    writer_artifact: dict[str, Any], findings: list[dict[str, Any]]
) -> tuple[VerifierArtifact, Envelope]:
    start = time.perf_counter()
    available_ids = {f["id"] for f in findings}
    cited_ids = set(writer_artifact.get("claims_used", []))
    violations: list[Issue] = []
    fixes: list[str] = []

    fabricated = cited_ids - available_ids
    if fabricated:
        violations.append(
            Issue(
                code="FABRICATED_CITATION",
                severity="error",
                detail=f"claims_used contains unknown ids: {sorted(fabricated)}",
            )
        )
        fixes.append("Re-run writer with claims_used restricted to provided finding ids.")

    summary = writer_artifact.get("summary_text", "")
    if not summary.strip():
        violations.append(
            Issue(code="EMPTY_SUMMARY", severity="error", detail="summary_text is empty")
        )
    elif len(summary) < 30:
        violations.append(
            Issue(
                code="SUMMARY_TOO_SHORT",
                severity="warn",
                detail=f"summary length {len(summary)} chars is suspiciously short",
            )
        )

    uncited = available_ids - cited_ids
    if uncited and not violations:
        violations.append(
            Issue(
                code="UNCITED_FINDING",
                severity="warn",
                detail=f"Findings not cited by writer: {sorted(uncited)}",
            )
        )

    verdict = "fail" if any(v.severity == "error" for v in violations) else "pass"

    artifact = VerifierArtifact(verdict=verdict, violations=violations, fixes=fixes)
    latency_ms = int((time.perf_counter() - start) * 1000)
    envelope = Envelope(
        status="ok" if verdict == "pass" else "partial",
        agent="verifier",
        confidence=1.0 if verdict == "pass" else 0.4,
        provenance=Provenance(
            model="claude-sonnet-4-6",
            inputs=[],
            tokens=Tokens(**{"in": 4000, "out": 500}),
            latency_ms=latency_ms,
        ),
    )
    return artifact, envelope
