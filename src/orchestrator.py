"""Orchestrator: plans the DAG, schedules nodes, owns the budget and containment.

Independent nodes run in parallel via asyncio.to_thread (agents are sync, so we
offload them to threads to overlap I/O and CPU). Each node's output passes its
gate before landing on the blackboard. A gate failure routes through the
containment ladder: retry → degrade. Nothing reaches downstream agents until
validated.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from . import log
from .agents import analyst, cleaner, retriever, verifier, writer
from .blackboard import Blackboard
from .budget import Budget
from .gates import (
    GateResult,
    analyst_gate,
    cleaner_gate,
    retriever_gate,
    verifier_gate,
    writer_gate,
)
from .schemas import Envelope


MAX_RETRIES = 2
_logger = log.get("orchestrator")


@dataclass
class TraceEvent:
    """One event in the live trace stream. The UI renders these as they arrive."""

    kind: str  # plan | node_start | node_done | gate | artifact | budget | done | error
    node: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "node": self.node, "payload": self.payload, "ts": self.ts}


class Orchestrator:
    def __init__(self, request: dict[str, Any]) -> None:
        self.request = request
        self.run_id = "run_" + uuid.uuid4().hex[:6]
        self.blackboard = Blackboard(self.run_id)
        self.budget = Budget()
        self._queue: asyncio.Queue[TraceEvent | None] = asyncio.Queue()
        self.final: dict[str, Any] | None = None
        self._log_handler = log.attach_run_log(self.run_id, self.blackboard._root)
        _logger.info(
            "run.start run_id=%s request=%r sources=%d",
            self.run_id,
            request.get("request", "")[:120],
            len(request.get("sources", [])),
        )

    # ---- Public API --------------------------------------------------------

    async def stream(self) -> AsyncIterator[TraceEvent]:
        """Drive the pipeline and yield trace events as they happen."""
        runner = asyncio.create_task(self._run())
        try:
            while True:
                ev = await self._queue.get()
                if ev is None:
                    break
                yield ev
        finally:
            await runner

    async def _emit(self, ev: TraceEvent) -> None:
        self._log_event(ev)
        await self._queue.put(ev)

    def _log_event(self, ev: TraceEvent) -> None:
        node = ev.node or "-"
        p = ev.payload
        if ev.kind == "plan":
            _logger.info("plan run_id=%s shape=%s", self.run_id, p.get("plan", {}).get("shape"))
        elif ev.kind == "node_start":
            _logger.info("node.start node=%s attempt=%s", node, p.get("attempt"))
        elif ev.kind == "gate":
            if p.get("retrying"):
                _logger.warning("gate.retry node=%s attempt=%s", node, p.get("attempt"))
            elif p.get("ok"):
                _logger.info("gate.pass node=%s", node)
            else:
                _logger.error("gate.fail node=%s violations=%s", node, p.get("violations"))
        elif ev.kind == "node_done":
            if p.get("terminal"):
                _logger.error("node.terminal node=%s violations=%s", node, p.get("violations"))
            else:
                _logger.info("node.done node=%s ref=%s", node, p.get("ref"))
        elif ev.kind == "artifact":
            _logger.debug("artifact node=%s ref=%s", node, p.get("ref"))
        elif ev.kind == "budget":
            _logger.debug(
                "budget cost=%.4f tok_in=%s tok_out=%s calls=%s",
                p.get("cost_usd", 0.0),
                p.get("tokens_in"),
                p.get("tokens_out"),
                p.get("calls"),
            )
        elif ev.kind == "done":
            _logger.info("run.done run_id=%s verdict=%s", self.run_id, p.get("verdict"))
        elif ev.kind == "error":
            _logger.exception("run.error run_id=%s message=%s", self.run_id, p.get("message"))

    # ---- Planning ---------------------------------------------------------

    def _plan(self) -> dict[str, Any]:
        """Templated plan — known request shape. The plan is the DAG."""
        sources = self.request.get("sources", [])
        if not sources:
            return {"shape": "clarification", "reason": "no sources provided"}
        return {
            "shape": "retrieve_clean_analyze_write",
            "retrievers": [s["id"] for s in sources],
            "analysts": ["trend", "anomaly"],
        }

    # ---- Run --------------------------------------------------------------

    async def _run(self) -> None:
        try:
            await self._run_pipeline()
        except Exception as exc:  # pragma: no cover — defensive
            await self._emit(TraceEvent("error", payload={"message": str(exc)}))
        finally:
            log.detach_handler(self._log_handler)
            await self._queue.put(None)

    async def _run_pipeline(self) -> None:
        plan = self._plan()
        await self._emit(
            TraceEvent(
                "plan",
                payload={
                    "run_id": self.run_id,
                    "request": self.request.get("request", ""),
                    "plan": plan,
                },
            )
        )

        if plan["shape"] == "clarification":
            self.final = {
                "verdict": "clarification_needed",
                "message": (
                    "The request was too ambiguous to plan a pipeline: no sources "
                    "were provided. Please attach at least one data source."
                ),
                "blackboard": self.blackboard.all_refs(),
                "budget": self.budget.snapshot(),
            }
            await self._emit(TraceEvent("done", payload=self.final))
            return

        sources = self.request["sources"]

        # 1. Retrievers, in parallel.
        retriever_refs = await self._run_parallel(
            [
                (
                    f"retriever:{src['id']}",
                    lambda src=src: retriever.run(src),
                    lambda payload, src=src: retriever_gate(payload, src["id"]),
                    "retriever",
                )
                for src in sources
            ]
        )
        if any(r is None for r in retriever_refs):
            await self._terminate("retriever_failed", "One or more retrievers failed after retries.")
            return

        # 2. Cleaner.
        raw_artifacts = [self.blackboard.read(r) for r in retriever_refs]
        cleaner_ref = await self._run_node(
            "cleaner",
            lambda: cleaner.run(raw_artifacts),
            cleaner_gate,
            "cleaner",
            inputs=retriever_refs,  # type: ignore[arg-type]
        )
        if cleaner_ref is None:
            await self._terminate(
                "cleaner_failed",
                "Cleaner failed validation after retries — the run is degraded "
                "rather than fabricating a summary on partial data (§9.1).",
            )
            return

        # 3. Analysts, in parallel.
        cleaner_artifact = self.blackboard.read(cleaner_ref)
        recompute = analyst.recompute_for(
            [r if isinstance(r, dict) else r.model_dump() for r in cleaner_artifact["records"]]
        )
        analyst_refs = await self._run_parallel(
            [
                (
                    "analyst:trend",
                    lambda: analyst.run_trend(cleaner_ref, cleaner_artifact),
                    lambda payload: analyst_gate(payload, recompute),
                    "analyst",
                ),
                (
                    "analyst:anomaly",
                    lambda: analyst.run_anomaly(cleaner_ref, cleaner_artifact),
                    lambda payload: analyst_gate(payload, recompute),
                    "analyst",
                ),
            ],
            inputs=[cleaner_ref],
        )
        analyst_refs = [r for r in analyst_refs if r is not None]
        if not analyst_refs:
            await self._terminate("analysts_failed", "All analysts failed validation.")
            return

        # 4. Reconcile (fan-in) → Writer.
        findings: list[dict[str, Any]] = []
        for ref in analyst_refs:
            findings.extend(self.blackboard.read(ref)["findings"])

        available_ids = {f["id"] for f in findings}
        writer_ref = await self._run_node(
            "writer",
            lambda: writer.run(findings),
            lambda payload: writer_gate(payload, available_ids),
            "writer",
            inputs=analyst_refs,
        )
        if writer_ref is None:
            await self._terminate("writer_failed", "Writer failed validation after retries.")
            return

        # 5. Verifier.
        writer_artifact = self.blackboard.read(writer_ref)
        verifier_ref = await self._run_node(
            "verifier",
            lambda: verifier.run(writer_artifact, findings),
            verifier_gate,
            "verifier",
            inputs=[writer_ref] + analyst_refs,
        )

        # Final assembly.
        verifier_payload = self.blackboard.read(verifier_ref) if verifier_ref else {}
        provenance_chain = (
            self.blackboard.provenance_chain(writer_ref) if writer_ref else []
        )
        self.final = {
            "verdict": verifier_payload.get("verdict", "unknown"),
            "summary": writer_artifact["summary_text"],
            "claims_used": writer_artifact["claims_used"],
            "sections": writer_artifact["sections"],
            "violations": verifier_payload.get("violations", []),
            "provenance_chain": provenance_chain,
            "writer_ref": writer_ref,
            "budget": self.budget.snapshot(),
        }
        await self._emit(TraceEvent("budget", payload=self.budget.snapshot()))
        await self._emit(TraceEvent("done", payload=self.final))

    async def _terminate(self, code: str, message: str) -> None:
        self.final = {
            "verdict": "degraded",
            "code": code,
            "message": message,
            "blackboard": self.blackboard.all_refs(),
            "budget": self.budget.snapshot(),
        }
        await self._emit(TraceEvent("budget", payload=self.budget.snapshot()))
        await self._emit(TraceEvent("done", payload=self.final))

    # ---- Node execution ---------------------------------------------------

    async def _run_node(
        self,
        node: str,
        run_fn: Callable[[], tuple[Any, Envelope]],
        gate_fn: Callable[[dict[str, Any]], GateResult],
        artifact_kind: str,
        *,
        inputs: list[str] | None = None,
    ) -> str | None:
        """Run one agent node with the containment ladder. Returns the artifact
        ref on success, None on terminal failure."""
        inputs = inputs or []
        for attempt in range(1, MAX_RETRIES + 2):
            await self._emit(
                TraceEvent(
                    "node_start",
                    node=node,
                    payload={"attempt": attempt, "inputs": inputs},
                )
            )
            artifact, envelope = await asyncio.to_thread(run_fn)
            payload = artifact.model_dump(by_alias=True)
            gate = gate_fn(payload)
            await self._emit(
                TraceEvent(
                    "gate",
                    node=node,
                    payload={
                        "ok": gate.ok,
                        "violations": gate.violations,
                        "warnings": gate.warnings,
                    },
                )
            )
            envelope_inputs = list(inputs)
            self.budget.debit(
                envelope.provenance.model,
                envelope.provenance.tokens.in_,
                envelope.provenance.tokens.out,
                envelope.provenance.latency_ms,
            )
            if gate.ok:
                ref = self.blackboard.write(
                    node,
                    artifact,
                    provenance={
                        "agent": node,
                        "model": envelope.provenance.model,
                        "inputs": envelope_inputs,
                        "tokens": envelope.provenance.tokens.model_dump(by_alias=True),
                        "latency_ms": envelope.provenance.latency_ms,
                        "confidence": envelope.confidence,
                    },
                )
                await self._emit(
                    TraceEvent(
                        "node_done",
                        node=node,
                        payload={
                            "ref": ref,
                            "envelope": envelope.model_dump(),
                            "kind": artifact_kind,
                        },
                    )
                )
                await self._emit(
                    TraceEvent("artifact", node=node, payload={"ref": ref, "data": payload})
                )
                await self._emit(TraceEvent("budget", payload=self.budget.snapshot()))
                return ref
            # Gate failed — try again unless we've hit the cap.
            if attempt > MAX_RETRIES:
                await self._emit(
                    TraceEvent(
                        "node_done",
                        node=node,
                        payload={
                            "ref": None,
                            "envelope": envelope.model_dump(),
                            "terminal": True,
                            "violations": gate.violations,
                        },
                    )
                )
                return None
            await self._emit(
                TraceEvent(
                    "gate",
                    node=node,
                    payload={"retrying": True, "attempt": attempt},
                )
            )
        return None

    async def _run_parallel(
        self,
        specs: list[tuple[str, Callable[[], tuple[Any, Envelope]], Callable[[dict[str, Any]], GateResult], str]],
        *,
        inputs: list[str] | None = None,
    ) -> list[str | None]:
        coros: list[Awaitable[str | None]] = [
            self._run_node(name, run_fn, gate_fn, kind, inputs=inputs)
            for (name, run_fn, gate_fn, kind) in specs
        ]
        return list(await asyncio.gather(*coros))
