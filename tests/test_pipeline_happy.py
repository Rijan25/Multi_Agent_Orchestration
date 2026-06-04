"""End-to-end test on the happy sample: the full DAG runs on the mock LLM
and produces a verifier-passed summary citing real findings."""
from __future__ import annotations

import asyncio

from src.orchestrator import Orchestrator


def _drive(orch: Orchestrator) -> list[dict]:
    async def collect():
        events = []
        async for ev in orch.stream():
            events.append(ev.to_dict())
        return events

    return asyncio.run(collect())


def test_happy_pipeline_passes_verifier(happy_sample):
    orch = Orchestrator(happy_sample)
    events = _drive(orch)

    kinds = [e["kind"] for e in events]
    assert "plan" in kinds
    assert "done" in kinds

    final = orch.final
    assert final is not None
    assert final["verdict"] == "pass", f"unexpected verdict: {final}"
    assert final["summary"]
    assert final["claims_used"]
    # provenance_chain must terminate at the writer
    assert final["writer_ref"] == final["provenance_chain"][-1]
    # Budget should have logged at least one call
    assert final["budget"]["calls"] >= 1


def test_pipeline_uses_parallelism(happy_sample, monkeypatch):
    """With a small delay forced into each retriever, both must start before
    either's done event — proving the orchestrator schedules them in parallel
    rather than sequentially."""
    from src.agents import retriever as retriever_mod

    real_run = retriever_mod.run

    def slow_run(src):
        import time as _t
        _t.sleep(0.05)  # 50ms — long enough to interleave reliably
        return real_run(src)

    monkeypatch.setattr(retriever_mod, "run", slow_run)
    orch = Orchestrator(happy_sample)
    events = _drive(orch)

    retriever_starts = [
        i for i, e in enumerate(events)
        if e["kind"] == "node_start" and (e["node"] or "").startswith("retriever:")
    ]
    retriever_dones = [
        i for i, e in enumerate(events)
        if e["kind"] == "node_done" and (e["node"] or "").startswith("retriever:")
    ]
    assert len(retriever_starts) == 2
    assert max(retriever_starts) < min(retriever_dones), (
        "retrievers ran sequentially — both starts should precede both dones"
    )
