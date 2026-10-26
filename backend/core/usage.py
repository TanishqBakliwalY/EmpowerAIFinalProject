"""Token accounting and spend limits.

Every model response's usage is added to the step that made it, so each run can show
input / cached input / output tokens and dollars per agent, and the daily budget can stop
new runs before a bug or an abuser burns through the key.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from . import store
from .config import (
    DAILY_BUDGET_USD,
    PRICE_CACHED_INPUT_PER_M,
    PRICE_INPUT_PER_M,
    PRICE_OUTPUT_PER_M,
)


def cost_usd(input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    """OpenAI-style billing: input_tokens includes the cached ones, which are billed at the cached rate."""
    uncached = max(0, input_tokens - cached_tokens)
    return (
        uncached * PRICE_INPUT_PER_M + cached_tokens * PRICE_CACHED_INPUT_PER_M + output_tokens * PRICE_OUTPUT_PER_M
    ) / 1_000_000


@dataclass
class Tally:
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    requests: int = 0
    tool_calls: int = 0

    def add_response(self, usage: Any) -> None:
        """Add one model response's RequestUsage."""
        if usage is None:
            return
        self.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        self.cached_tokens += int(getattr(usage, "cache_read_tokens", 0) or 0)
        self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        details = getattr(usage, "details", None) or {}
        self.reasoning_tokens += int(details.get("reasoning_tokens", 0) or 0)
        self.requests += 1

    def add(self, other: "Tally") -> None:
        for k in asdict(self):
            setattr(self, k, getattr(self, k) + getattr(other, k))

    @property
    def cost_usd(self) -> float:
        return cost_usd(self.input_tokens, self.cached_tokens, self.output_tokens)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["cost_usd"] = round(self.cost_usd, 6)
        d["cache_hit_pct"] = round(100 * self.cached_tokens / self.input_tokens, 1) if self.input_tokens else 0.0
        return d


class BudgetExceeded(RuntimeError):
    pass


def check_daily_budget() -> dict[str, float]:
    spent = store.spent_today_usd()
    if spent >= DAILY_BUDGET_USD:
        raise BudgetExceeded(
            f"Daily AI budget of ${DAILY_BUDGET_USD:.2f} is used up (${spent:.2f} spent today). "
            "New runs are paused until tomorrow (UTC) or until an admin raises DAILY_BUDGET_USD."
        )
    return {"spent_today_usd": round(spent, 4), "daily_budget_usd": DAILY_BUDGET_USD}


def prices() -> dict[str, float]:
    return {
        "input_per_m": PRICE_INPUT_PER_M,
        "cached_input_per_m": PRICE_CACHED_INPUT_PER_M,
        "output_per_m": PRICE_OUTPUT_PER_M,
    }


def reprice(u: dict[str, Any] | None) -> dict[str, Any] | None:
    """Recompute a stored usage dict's cost at the current prices (token counts are the source of truth)."""
    if not u:
        return u
    u = dict(u)
    u["cost_usd"] = round(cost_usd(int(u.get("input_tokens", 0) or 0), int(u.get("cached_tokens", 0) or 0),
                                   int(u.get("output_tokens", 0) or 0)), 6)
    return u


def reprice_run(state: dict[str, Any]) -> dict[str, Any]:
    """Reprice a stored run (whole-run usage and every step) for display."""
    state = dict(state)
    if state.get("usage"):
        state["usage"] = reprice(state["usage"])
    if state.get("steps"):
        state["steps"] = {k: ({**v, "usage": reprice(v.get("usage"))} if v.get("usage") else v)
                          for k, v in state["steps"].items()}
    return state
