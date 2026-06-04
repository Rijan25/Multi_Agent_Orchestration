"""A fabricated claims_used id must be rejected by the writer gate (schema layer)
AND by the verifier (semantic layer). This is the §5 promise: hallucinations
die at a gate, not in front of a customer."""
from __future__ import annotations

from src.agents import verifier
from src.gates import writer_gate


FINDINGS = [
    {
        "id": "f1",
        "claim": "Revenue rose 18% over the window",
        "metric": "revenue_growth_pct",
        "value": 18.2,
        "evidence_ref": "test/cleaner/v1#rows=all",
        "confidence": 0.94,
    }
]


def test_writer_gate_rejects_fabricated_citation():
    bad_writer_output = {
        "summary_text": "Revenue grew 18% (per f1) and customer NPS hit 70 (per f99).",
        "claims_used": ["f1", "f99"],  # f99 was never produced
        "sections": ["headline"],
    }
    gate = writer_gate(bad_writer_output, available_finding_ids={"f1"})
    assert gate.ok is False
    assert any("f99" in v for v in gate.violations)


def test_verifier_flags_fabricated_citation():
    bad_writer_output = {
        "summary_text": "Revenue grew 18% (per f1) and customer NPS hit 70 (per f99).",
        "claims_used": ["f1", "f99"],
        "sections": ["headline"],
    }
    artifact, _ = verifier.run(bad_writer_output, FINDINGS)
    assert artifact.verdict == "fail"
    assert any(v.code == "FABRICATED_CITATION" for v in artifact.violations)
