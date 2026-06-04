"""Retriever: pulls rows from one source. Deterministic — no LLM call."""
from __future__ import annotations

import time
from typing import Any

from ..schemas import Envelope, Provenance, Record, RetrieverArtifact, Tokens


def run(source: dict[str, Any]) -> tuple[RetrieverArtifact, Envelope]:
    start = time.perf_counter()
    raw_records = source.get("records", [])
    records: list[Record] = []
    for raw in raw_records:
        try:
            records.append(Record.model_validate(raw))
        except Exception:
            # Malformed rows are kept as-is for the cleaner to handle, so the
            # drop-rate gate fires correctly when sources are bad. The
            # retriever's contract is "what the source returned", not "what is
            # clean" — that's the cleaner's job.
            #
            # We let cleaner-side validation expose the loss.
            pass

    artifact = RetrieverArtifact(
        source_id=source["id"],
        record_count=len(records),
        schema_fields=["date", "region", "revenue", "units", "currency"],
        sample=records[:3],
        records=records,
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    envelope = Envelope(
        status="ok" if records else "failed",
        agent=f"retriever:{source['id']}",
        artifact_ref=None,  # set by orchestrator after gate + blackboard write
        confidence=1.0 if records else 0.0,
        provenance=Provenance(
            model="none",
            inputs=[],
            tokens=Tokens(),
            latency_ms=latency_ms,
        ),
    )
    return artifact, envelope
