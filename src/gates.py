"""Validation gates: schema + semantic + recompute.

Layer 1: pydantic round-trip (schema/shape).
Layer 2: invariants and grounding (numbers recomputed, refs resolved).
Nothing reaches the blackboard until both pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from .schemas import (
    AnalystArtifact,
    CleanerArtifact,
    Finding,
    RetrieverArtifact,
    VerifierArtifact,
    WriterArtifact,
)


@dataclass
class GateResult:
    ok: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_violation(self, msg: str) -> None:
        self.ok = False
        self.violations.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# Threshold above which the cleaner is considered to have silently lost data.
DROP_RATE_CEILING = 0.10  # 10%


def _validate_shape(model_cls: type[BaseModel], payload: dict[str, Any]) -> GateResult | BaseModel:
    try:
        return model_cls.model_validate(payload)
    except ValidationError as exc:
        res = GateResult(ok=False)
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            res.add_violation(f"schema: {loc}: {err['msg']}")
        return res


def retriever_gate(payload: dict[str, Any], expected_source: str) -> GateResult:
    parsed = _validate_shape(RetrieverArtifact, payload)
    if isinstance(parsed, GateResult):
        return parsed
    res = GateResult(ok=True)
    if parsed.source_id != expected_source:
        res.add_violation(
            f"source mismatch: expected {expected_source!r}, got {parsed.source_id!r}"
        )
    if parsed.record_count != len(parsed.records):
        res.add_violation(
            f"record_count {parsed.record_count} != len(records) {len(parsed.records)}"
        )
    if parsed.record_count == 0:
        res.add_violation("retriever returned zero records")
    return res


def cleaner_gate(payload: dict[str, Any]) -> GateResult:
    parsed = _validate_shape(CleanerArtifact, payload)
    if isinstance(parsed, GateResult):
        return parsed
    res = GateResult(ok=True)
    if parsed.rows_out > parsed.rows_in:
        res.add_violation(
            f"invariant violated: rows_out ({parsed.rows_out}) > rows_in ({parsed.rows_in})"
        )
    if parsed.rows_in <= 0:
        res.add_violation("rows_in must be positive")
        return res
    drop_rate = (parsed.rows_in - parsed.rows_out) / parsed.rows_in
    if drop_rate > DROP_RATE_CEILING:
        res.add_violation(
            f"drop_rate {drop_rate:.0%} exceeds ceiling {DROP_RATE_CEILING:.0%} — "
            f"{parsed.rows_in - parsed.rows_out} rows silently dropped"
        )
    elif drop_rate > DROP_RATE_CEILING / 2:
        res.add_warning(f"drop_rate {drop_rate:.0%} approaching ceiling")
    return res


def analyst_gate(payload: dict[str, Any], recompute_fn) -> GateResult:
    """recompute_fn(finding) -> recomputed float; gate rejects on mismatch > 1%."""
    parsed = _validate_shape(AnalystArtifact, payload)
    if isinstance(parsed, GateResult):
        return parsed
    res = GateResult(ok=True)
    seen_ids: set[str] = set()
    for f in parsed.findings:
        if f.id in seen_ids:
            res.add_violation(f"duplicate finding id: {f.id}")
        seen_ids.add(f.id)
        try:
            expected = recompute_fn(f)
        except Exception as exc:  # pragma: no cover — defensive
            res.add_violation(f"finding {f.id}: evidence_ref unresolvable ({exc})")
            continue
        if expected is None:
            res.add_violation(f"finding {f.id}: evidence_ref {f.evidence_ref} unresolved")
            continue
        if abs(expected - f.value) > max(0.01 * abs(expected), 0.001):
            res.add_violation(
                f"finding {f.id}: claimed {f.value}, recomputed {expected:.3f}"
            )
    return res


def writer_gate(payload: dict[str, Any], available_finding_ids: set[str]) -> GateResult:
    parsed = _validate_shape(WriterArtifact, payload)
    if isinstance(parsed, GateResult):
        return parsed
    res = GateResult(ok=True)
    if not parsed.summary_text.strip():
        res.add_violation("summary_text is empty")
    fabricated = set(parsed.claims_used) - available_finding_ids
    if fabricated:
        res.add_violation(
            f"claims_used references unknown findings: {sorted(fabricated)}"
        )
    if not parsed.claims_used:
        res.add_warning("writer cited no findings")
    return res


def verifier_gate(payload: dict[str, Any]) -> GateResult:
    parsed = _validate_shape(VerifierArtifact, payload)
    if isinstance(parsed, GateResult):
        return parsed
    return GateResult(ok=True)
