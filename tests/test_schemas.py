"""Schema validation tests — every agent's output round-trips through its pydantic schema.

This is the test the candidate pack explicitly asks for: 'at least one that
checks the AI output is valid against your schema'.
"""
from __future__ import annotations

from src.agents import analyst, cleaner, retriever, verifier, writer
from src.schemas import (
    AnalystArtifact,
    CleanerArtifact,
    Envelope,
    RetrieverArtifact,
    VerifierArtifact,
    WriterArtifact,
)


def test_envelope_minimum():
    e = Envelope(status="ok", agent="t")
    assert e.confidence == 1.0
    assert e.provenance.model == "none"


def test_retriever_artifact_matches_schema(happy_sample):
    src = happy_sample["sources"][0]
    artifact, envelope = retriever.run(src)
    # Round-trip
    RetrieverArtifact.model_validate(artifact.model_dump())
    Envelope.model_validate(envelope.model_dump())
    assert artifact.record_count == len(artifact.records)


def test_cleaner_artifact_matches_schema(happy_sample):
    retr_payloads = []
    for src in happy_sample["sources"]:
        a, _ = retriever.run(src)
        retr_payloads.append(a.model_dump())
    artifact, envelope = cleaner.run(retr_payloads)
    CleanerArtifact.model_validate(artifact.model_dump())
    Envelope.model_validate(envelope.model_dump())
    assert artifact.rows_out <= artifact.rows_in


def test_analyst_artifact_matches_schema(happy_sample):
    payloads = [retriever.run(s)[0].model_dump() for s in happy_sample["sources"]]
    cleaned, _ = cleaner.run(payloads)
    trend, _ = analyst.run_trend("test/cleaner/v1", cleaned.model_dump())
    anomaly, _ = analyst.run_anomaly("test/cleaner/v1", cleaned.model_dump())
    AnalystArtifact.model_validate(trend.model_dump())
    AnalystArtifact.model_validate(anomaly.model_dump())
    assert all(f.evidence_ref for f in trend.findings)


def test_writer_and_verifier_match_schema(happy_sample):
    payloads = [retriever.run(s)[0].model_dump() for s in happy_sample["sources"]]
    cleaned, _ = cleaner.run(payloads)
    trend, _ = analyst.run_trend("test/cleaner/v1", cleaned.model_dump())
    anomaly, _ = analyst.run_anomaly("test/cleaner/v1", cleaned.model_dump())
    findings = [f.model_dump() for f in trend.findings] + [
        f.model_dump() for f in anomaly.findings
    ]
    wr, env = writer.run(findings)
    WriterArtifact.model_validate(wr.model_dump())
    Envelope.model_validate(env.model_dump())
    assert wr.summary_text
    assert set(wr.claims_used) <= {f["id"] for f in findings}

    vf, _ = verifier.run(wr.model_dump(), findings)
    VerifierArtifact.model_validate(vf.model_dump())
    assert vf.verdict in {"pass", "fail", "revise"}
