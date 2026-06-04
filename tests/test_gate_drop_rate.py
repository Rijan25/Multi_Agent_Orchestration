"""§9.1 walkthrough as a test: a malformed source causes the cleaner to drop too
many rows. The drop-rate gate must reject and the run must degrade — never
silently feed truncated data downstream."""
from __future__ import annotations

import asyncio

from src.gates import cleaner_gate
from src.agents import cleaner, retriever
from src.orchestrator import Orchestrator


def test_cleaner_gate_catches_high_drop_rate(drop_rate_sample):
    payloads = [retriever.run(s)[0].model_dump() for s in drop_rate_sample["sources"]]
    artifact, _ = cleaner.run(payloads)
    gate = cleaner_gate(artifact.model_dump())
    assert gate.ok is False, "expected drop-rate gate to reject the cleaner output"
    assert any("drop_rate" in v for v in gate.violations)


def test_pipeline_degrades_on_drop_rate(drop_rate_sample):
    orch = Orchestrator(drop_rate_sample)
    events = []

    async def drain():
        async for ev in orch.stream():
            events.append(ev.to_dict())

    asyncio.run(drain())

    final = orch.final
    assert final is not None
    assert final["verdict"] == "degraded"
    assert final["code"] == "cleaner_failed"
    # The writer must NEVER have run when the cleaner failed.
    assert not any(e.get("node") == "writer" for e in events)
