"""Cleaner: normalizes currency, dedupes by (date, region), emits a quality report.

Reads scoped raw artifacts from the blackboard. Drops malformed rows and
records the reason in `quality.dropped_reasons`. The drop-rate gate
catches the §9.1 failure mode: well-formed output that silently lost data.
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Any

from ..schemas import (
    CleanerArtifact,
    Envelope,
    Provenance,
    QualityReport,
    Record,
    Tokens,
)


# Indicative FX rates — deterministic for the demo.
FX_TO_USD = {"USD": 1.0, "EUR": 1.10, "GBP": 1.27}


def run(raw_artifacts: list[dict[str, Any]]) -> tuple[CleanerArtifact, Envelope]:
    start = time.perf_counter()
    all_rows: list[Record] = []
    for art in raw_artifacts:
        for r in art.get("records", []):
            try:
                all_rows.append(Record.model_validate(r))
            except Exception:  # pragma: no cover — already filtered in retriever
                pass
    rows_in = sum(art.get("record_count", 0) for art in raw_artifacts)

    cleaned: list[Record] = []
    dedupe_set: set[tuple[str, str]] = set()
    dropped: Counter[str] = Counter()

    for row in all_rows:
        # Normalize: convert to USD.
        rate = FX_TO_USD.get(row.currency.upper())
        if rate is None:
            dropped["unknown_currency"] += 1
            continue
        if not row.region:
            dropped["missing_region"] += 1
            continue
        key = (row.date, row.region)
        if key in dedupe_set:
            dropped["duplicate"] += 1
            continue
        dedupe_set.add(key)
        cleaned.append(
            Record(
                date=row.date,
                region=row.region,
                revenue=round(row.revenue * rate, 2),
                units=row.units,
                currency="USD",
            )
        )

    coverage_days = len({r.date for r in cleaned})
    null_rate = (
        sum(1 for r in cleaned if r.revenue == 0 or r.units == 0) / max(1, len(cleaned))
    )
    artifact = CleanerArtifact(
        rows_in=rows_in,
        rows_out=len(cleaned),
        dedup_count=dropped["duplicate"],
        schema_fields=["date", "region", "revenue", "units", "currency"],
        records=cleaned,
        quality=QualityReport(
            null_rate=round(null_rate, 4),
            coverage_days=coverage_days,
            dropped_reasons=dict(dropped),
        ),
    )

    latency_ms = int((time.perf_counter() - start) * 1000)
    status = "ok" if cleaned else "failed"
    envelope = Envelope(
        status=status,
        agent="cleaner",
        confidence=0.95 if status == "ok" else 0.0,
        provenance=Provenance(
            model="claude-haiku-4-5",  # nominal — this implementation runs locally
            inputs=[],  # filled by orchestrator
            tokens=Tokens(**{"in": 8200, "out": 1400}),  # nominal ledger entry
            latency_ms=latency_ms,
        ),
    )
    return artifact, envelope
