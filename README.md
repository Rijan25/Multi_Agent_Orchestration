# Multi-Agent Orchestration — Working Implementation

Case Study C from the ABC AI/ML Candidate Pack. This is a runnable implementation of the design described in `Multi_Agent_Orchestration_Design_Rijan_Pokhrel.docx`.

## Demo

**UI overview — sample picker and empty state**
![UI overview](Screenshot%202026-06-04%20222455.png)

**Happy path — full DAG run with live trace and budget**
![Happy path run](Screenshot%202026-06-04%20222507.png)

**Edge case — drop-rate gate rejects malformed source (§9.1)**
![Drop-rate gate failure](Screenshot%202026-06-04%20222524.png)

## Prerequisites

The Makefile uses [uv](https://docs.astral.sh/uv/) for dependency management. Install it once before running `make setup`:

```
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

`uv` is a fast, cross-platform Python package manager — it handles the venv and all dependencies automatically. No separate Python version management needed.

## Quickstart

```
make setup   # create venv, install deps (via uv)
make test    # run the test suite (schema + pipeline + gate + verifier tests)
make run     # serve the UI on http://localhost:8080
```

Open http://localhost:8080, pick a sample (or paste your own JSON), and click **Run pipeline**. The UI streams a live trace of every agent, gate verdict, and artifact written to the blackboard, and renders the final summary with its provenance chain.

## What this implements

An orchestrator–worker architecture over a shared blackboard:

- **Planner** decomposes the request into a typed DAG.
- **Retrievers (×N, parallel)** pull rows from each source.
- **Cleaner** normalizes, dedupes, emits a quality report.
- **Analysts (×2, parallel)** compute trend and anomaly findings — every numeric claim carries an `evidence_ref` and the gate recomputes it.
- **Writer** drafts the customer summary, reading only the findings (never raw data).
- **Verifier** mechanically checks `claims_used ⊆ findings`.

Every hand-off crosses a validation gate. Bad outputs are quarantined at the boundary and routed into the containment ladder (retry → fallback → degrade → escalate). No agent ever talks to another directly; they read scoped references from, and write versioned, immutable artifacts to, the blackboard.

## The AI boundary (swappable)

The model boundary is one file: `src/llm/base.py` defines `LLMClient`. Two implementations ship:

- `src/llm/mock.py` — deterministic mock, used by default. `make run` works offline.
- `src/llm/anthropic_client.py` — real Anthropic API client, used automatically if `ANTHROPIC_API_KEY` is set.

The writer is the only agent that uses the LLM. Everything else is deterministic by design (see §11 of the design doc — Opus runs once, over a small context).

## Logs

Two destinations, both written to disk:

- `logs/app.log` — the rotating application log (every request, every node, every gate verdict). Rolls at 2 MB with 5 backups.
- `runs/<run_id>/run.log` — the per-run log, attached only while that run is executing. Sits alongside `runs/<run_id>/blackboard.jsonl` (the artifact append log) so the run is fully reconstructable from disk.

The UI surfaces the current run's log via the **View log** button in the top bar (or hit `GET /api/logs/<run_id>` directly).

## Sample data

`data/` ships three samples, accessible in one click from the UI:

- `happy_q3_revenue.json` — clean US + EU sources, runs straight through.
- `edge_drop_rate.json` — malformed source: the cleaner drops 40% of rows, the drop-rate gate rejects it, and the run degrades with a flagged failure rather than fabricating a summary. This is the §9.1 walkthrough made executable.
- `edge_ambiguous.json` — unclear ask with no usable sources: the planner refuses to fabricate a DAG and returns a clarification.

## Code layout — finding the AI boundary

```
src/
  app.py                  FastAPI server + SSE trace stream
  orchestrator.py         DAG executor, parallelism, containment ladder, budget
  blackboard.py           Versioned, immutable artifact store
  schemas.py              Pydantic models for envelope + every artifact
  gates.py                Validation gates: schema + semantic + recompute
  budget.py               Cost and latency ledger
  llm/
    base.py               LLMClient interface  <-- the swappable AI boundary
    mock.py               Deterministic mock
    anthropic_client.py   Real API client (used if ANTHROPIC_API_KEY set)
  agents/
    retriever.py          Reads source data
    cleaner.py            Normalizes, dedupes, emits quality report
    analyst.py            Trend + anomaly findings with evidence_ref
    writer.py             Reads findings only; the LLM call lives here
    verifier.py           Deterministic claim-to-evidence checks
ui/
  index.html              Single-page UI
  styles.css              Plain CSS, no framework
  app.js                  Vanilla JS for fetch + SSE rendering
data/                     Bundled samples (happy + 2 edge cases)
tests/                    pytest suite: schemas, end-to-end, gates, verifier
```

## Tests

`make test` runs:

- `test_schemas.py` — every agent's output validates against its declared schema.
- `test_pipeline_happy.py` — full DAG runs end-to-end on the happy sample under the mock LLM.
- `test_gate_drop_rate.py` — the drop-rate scenario is caught by the gate and never reaches downstream agents.
- `test_verifier_catches_hallucination.py` — a fabricated `claims_used` id is rejected at the verifier gate.

## Choices I made

- **Python + FastAPI + plain HTML/CSS/JS.** Minimal deps, no build step, runs anywhere with Python 3.10+. The UI is one HTML file, one CSS file, one JS file — no framework.
- **uv for dependency management.** `uv venv` + `uv pip install` replaces the OS-specific venv path detection that pip requires. `uv run` resolves the correct interpreter automatically on Windows, Mac, and Linux — the Makefile has zero platform-conditional logic for running commands.
- **Mock LLM by default.** The case study insists `make run` must work offline; I made that the default path rather than an afterthought.
- **In-memory blackboard with JSONL append on disk.** Per-run JSONL in `runs/` makes traces replayable from the filesystem; the in-memory layer keeps the UI fast. Garbage collection is out of scope for a single-run demo.
- **Deterministic agents wherever possible.** Cleaner, analysts, and verifier are pure Python. Only the writer goes through the LLM — that mirrors the design's "Opus runs once over a small context" decision.
- **SSE for the trace stream.** Lets the UI render node-by-node progress without a WebSocket dependency.

## What I'd do with more time

- **Per-agent eval suite** (§10 of the design): pin contracts, run labeled tests in CI, drift dashboard.
- **Real DAG executor with thread/process isolation** instead of asyncio fan-out — would matter once agents call expensive tools.
- **Tenant-scoped long-term memory** (§14.3) — explicitly excluded from SDE2 scope, would be the first SDE3 addition.
- **Real provider fallback ladder** — currently the LLM client is one provider; production would fan out across providers when a model is degraded.
- **Tool-use layer** — analysts currently compute numbers in Python; in production the model would call tools and the orchestrator would log every call as part of provenance.
