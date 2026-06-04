"""One budget ledger per run. The orchestrator debits it as nodes run."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field


# Indicative per-token costs (USD per 1k tokens) — figures used only for the
# illustrative ledger shown in the UI. Adjust as needed.
PRICING: dict[str, tuple[float, float]] = {
    "none": (0.0, 0.0),
    "mock": (0.0, 0.0),
    "claude-haiku-4-5": (0.001, 0.005),
    "claude-sonnet-4-6": (0.003, 0.015),
    "claude-opus-4-7": (0.015, 0.075),
}


@dataclass
class BudgetSpend:
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    calls: int = 0


class Budget:
    def __init__(
        self,
        max_cost_usd: float = 1.00,
        max_latency_ms: int = 60_000,
    ) -> None:
        self.max_cost_usd = max_cost_usd
        self.max_latency_ms = max_latency_ms
        self._spend = BudgetSpend()
        self._lock = threading.Lock()

    def debit(self, model: str, tokens_in: int, tokens_out: int, latency_ms: int) -> None:
        cost_in, cost_out = PRICING.get(model, (0.0, 0.0))
        cost = (tokens_in / 1000.0) * cost_in + (tokens_out / 1000.0) * cost_out
        with self._lock:
            self._spend.tokens_in += tokens_in
            self._spend.tokens_out += tokens_out
            self._spend.cost_usd += cost
            # Latency is wall-clock-ish — sum is a worst-case upper bound, the
            # real number depends on which nodes ran in parallel. We track
            # both: cumulative work time here, plus wall clock in the run.
            self._spend.latency_ms += latency_ms
            self._spend.calls += 1

    @property
    def spend(self) -> BudgetSpend:
        return self._spend

    @property
    def cost_exhausted(self) -> bool:
        return self._spend.cost_usd >= self.max_cost_usd

    def snapshot(self) -> dict[str, float | int]:
        s = self._spend
        return {
            "tokens_in": s.tokens_in,
            "tokens_out": s.tokens_out,
            "cost_usd": round(s.cost_usd, 6),
            "cumulative_latency_ms": s.latency_ms,
            "calls": s.calls,
            "max_cost_usd": self.max_cost_usd,
            "max_latency_ms": self.max_latency_ms,
        }
