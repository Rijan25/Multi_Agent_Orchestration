"""Two analysts: trend (period-over-period revenue growth) and anomaly (region z-score).

Each emits findings with evidence_ref. Numbers are computed deterministically in
Python; the analyst gate re-runs the math and rejects on mismatch. This is the
§5 promise: a hallucinated statistic dies at the analyst's gate.
"""
from __future__ import annotations

import math
import statistics
import time
from typing import Any

from ..schemas import (
    AnalystArtifact,
    Envelope,
    Finding,
    Provenance,
    Tokens,
)


def _split_halves(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(records, key=lambda r: r["date"])
    mid = len(ordered) // 2
    return ordered[:mid], ordered[mid:]


def trend_growth(records: list[dict[str, Any]]) -> float:
    """Period-over-period revenue growth (%). Deterministic."""
    if len(records) < 2:
        return 0.0
    first_half, second_half = _split_halves(records)
    s1 = sum(r["revenue"] for r in first_half) or 1e-9
    s2 = sum(r["revenue"] for r in second_half)
    return round(((s2 - s1) / s1) * 100, 2)


def region_anomaly_zscore(records: list[dict[str, Any]]) -> tuple[str | None, float]:
    """Largest absolute z-score across region totals."""
    by_region: dict[str, float] = {}
    for r in records:
        by_region[r["region"]] = by_region.get(r["region"], 0.0) + r["revenue"]
    if len(by_region) < 2:
        return None, 0.0
    values = list(by_region.values())
    mean = statistics.mean(values)
    stdev = statistics.pstdev(values) or 1e-9
    region, z = max(
        ((reg, (val - mean) / stdev) for reg, val in by_region.items()),
        key=lambda kv: abs(kv[1]),
    )
    return region, round(z, 3)


def run_trend(cleaner_ref: str, cleaner_artifact: dict[str, Any]) -> tuple[AnalystArtifact, Envelope]:
    start = time.perf_counter()
    records = [r if isinstance(r, dict) else r.model_dump() for r in cleaner_artifact["records"]]
    growth = trend_growth(records)
    findings = [
        Finding(
            id="f1",
            claim=f"Revenue {'rose' if growth >= 0 else 'fell'} {abs(growth):.1f}% over the window",
            metric="revenue_growth_pct",
            value=growth,
            evidence_ref=f"{cleaner_ref}#rows=all",
            confidence=0.94,
        )
    ]
    artifact = AnalystArtifact(
        findings=findings,
        method="period-over-period on cleaned series",
        caveats=[],
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    envelope = Envelope(
        status="ok",
        agent="analyst:trend",
        confidence=0.94,
        provenance=Provenance(
            model="claude-sonnet-4-6",
            inputs=[],
            tokens=Tokens(**{"in": 8000, "out": 2000}),
            latency_ms=latency_ms,
        ),
    )
    return artifact, envelope


def run_anomaly(cleaner_ref: str, cleaner_artifact: dict[str, Any]) -> tuple[AnalystArtifact, Envelope]:
    start = time.perf_counter()
    records = [r if isinstance(r, dict) else r.model_dump() for r in cleaner_artifact["records"]]
    region, z = region_anomaly_zscore(records)
    findings: list[Finding] = []
    if region is not None:
        findings.append(
            Finding(
                id="f2",
                claim=(
                    f"{region} stands out with z-score {z:.2f} versus the regional mean"
                ),
                metric="region_revenue_zscore",
                value=z,
                evidence_ref=f"{cleaner_ref}#group=region",
                confidence=0.88,
            )
        )
    artifact = AnalystArtifact(
        findings=findings,
        method="z-score on revenue totals by region",
        caveats=["only meaningful with ≥2 regions"] if len(findings) == 0 else [],
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    envelope = Envelope(
        status="ok",
        agent="analyst:anomaly",
        confidence=0.88,
        provenance=Provenance(
            model="claude-sonnet-4-6",
            inputs=[],
            tokens=Tokens(**{"in": 8000, "out": 2000}),
            latency_ms=latency_ms,
        ),
    )
    return artifact, envelope


def recompute_for(cleaner_records: list[dict[str, Any]]):
    """Returns a closure the analyst gate uses to recompute claimed numbers."""

    def fn(finding: Finding) -> float | None:
        if finding.metric == "revenue_growth_pct":
            return trend_growth(cleaner_records)
        if finding.metric == "region_revenue_zscore":
            _, z = region_anomaly_zscore(cleaner_records)
            return z
        return None

    return fn
