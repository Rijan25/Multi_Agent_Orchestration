"""Pydantic schemas for the envelope and every artifact written to the blackboard.

The envelope is what an agent returns to the orchestrator (status, refs, provenance).
Artifacts are the bulk data that stays on the blackboard; agents read them by reference.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Status = Literal["ok", "partial", "failed"]
Severity = Literal["info", "warn", "error"]


class Issue(BaseModel):
    code: str
    severity: Severity = "warn"
    detail: str = ""


class Tokens(BaseModel):
    in_: int = Field(0, alias="in")
    out: int = 0

    model_config = {"populate_by_name": True}


class Provenance(BaseModel):
    model: str = "none"
    inputs: list[str] = Field(default_factory=list)
    tokens: Tokens = Field(default_factory=Tokens)
    latency_ms: int = 0


class Envelope(BaseModel):
    """Returned by every agent. The orchestrator reads status / confidence / issues
    to decide pass / re-run / degrade; artifact_ref to locate the payload."""

    status: Status
    agent: str
    schema_version: str = "1.0.0"
    artifact_ref: str | None = None
    confidence: float = 1.0
    issues: list[Issue] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


# ---- Artifacts ------------------------------------------------------------


class Record(BaseModel):
    date: str
    region: str
    revenue: float
    units: int
    currency: str = "USD"


class RetrieverArtifact(BaseModel):
    source_id: str
    record_count: int
    schema_fields: list[str]
    sample: list[Record]
    records: list[Record]


class QualityReport(BaseModel):
    null_rate: float
    coverage_days: int
    dropped_reasons: dict[str, int] = Field(default_factory=dict)


class CleanerArtifact(BaseModel):
    rows_in: int
    rows_out: int
    dedup_count: int
    schema_fields: list[str]
    records: list[Record]
    quality: QualityReport


class Finding(BaseModel):
    id: str
    claim: str
    metric: str
    value: float
    evidence_ref: str
    confidence: float = 0.9


class AnalystArtifact(BaseModel):
    findings: list[Finding]
    method: str
    caveats: list[str] = Field(default_factory=list)


class WriterArtifact(BaseModel):
    summary_text: str
    claims_used: list[str]
    sections: list[str] = Field(default_factory=list)


class VerifierArtifact(BaseModel):
    verdict: Literal["pass", "fail", "revise"]
    violations: list[Issue] = Field(default_factory=list)
    fixes: list[str] = Field(default_factory=list)


# Map artifact type names to their pydantic classes so the blackboard can
# round-trip them generically.
ARTIFACT_TYPES: dict[str, type[BaseModel]] = {
    "retriever": RetrieverArtifact,
    "cleaner": CleanerArtifact,
    "analyst": AnalystArtifact,
    "writer": WriterArtifact,
    "verifier": VerifierArtifact,
}
