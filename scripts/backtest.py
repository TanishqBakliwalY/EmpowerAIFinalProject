"""Backtest the estimate against what past projects ACTUALLY took.

For each chosen past project, the project is removed from the company history (so the agents cannot
look up its own answer), its original client brief is run through the Analyst -> Architect -> Estimator,
and the estimate is compared with (a) the hours the project really took and (b) the estimate Empower
made at the time. Token use and cost are recorded too, so the same script can test cost cuts such as
lower reasoning effort.

    python scripts/backtest.py --projects P102 P107 P112 P116 P121 P127
    python scripts/backtest.py --effort low --out data/runtime/backtest_low.json

On the synthetic demo data this only checks the mechanics. Run it with EMPOWER_DATA_DIR pointing at
real exports to measure real accuracy.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
import time
import uuid
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.company import CompanyData, company  # noqa: E402
from backend.modules.deal_desk import pipeline  # noqa: E402

DEFAULT = ["P102", "P107", "P112", "P116", "P121", "P127"]


def without(c: CompanyData, pid: str) -> CompanyData:
    """A copy of the company that has never heard of project `pid`."""
    c2 = copy.copy(c)
    c2.projects = {k: v for k, v in c.projects.items() if k != pid}
    c2.project_modules = [r for r in c.project_modules if r["project_id"] != pid]
    return c2


async def one(pid: str, effort: str | None) -> dict:
    c = company()
    p = c.projects[pid]
    cur = p["currency"] if p["currency"] in ("USD", "EUR", "GBP") else "USD"
    inp = {"brief": p["brief"], "client_name": p["client"], "client_country": p["country"], "currency": cur, "desired_start": ""}
    run_id = "bt-" + uuid.uuid4().hex[:8]
    state = pipeline.new_state(run_id, inp, "backtest")
    eff = {k: effort for k in ("analyst", "architect", "estimator")} if effort else None
    run = pipeline.DealRun(run_id, state, company_data=without(c, pid), effort=eff, save=False)
    run.rec.module = "backtest"
    t0 = time.monotonic()
    clean = run.screen()
    await run.run_analyst(clean)
    await run.run_architect()
    await run.run_estimator()
    est = run.deps.estimate
    app_err = 100 * (est.expected_hours - p["actual_hours"]) / p["actual_hours"]  # most-likely vs actual
    old_err = 100 * (p["est_hours"] - p["actual_hours"]) / p["actual_hours"]
    u = state["usage"]
    row = {
        "project_id": pid, "name": p["name"], "type": p["project_type"],
        "actual_hours": p["actual_hours"], "original_estimate": p["est_hours"], "app_estimate": round(est.expected_hours),
        "app_quoted_hours_incl_contingency": round(est.total_hours), "risk_level": est.risk_level,
        "packages": [f"{l.module_key}/{l.complexity}:{l.total_hours:.0f}" for l in est.lines],
        "app_range": [round(est.low_hours), round(est.high_hours)],
        "actual_in_app_range": est.low_hours <= p["actual_hours"] <= est.high_hours,
        "original_error_pct": round(old_err, 1), "app_error_pct": round(app_err, 1),
        "seconds": round(time.monotonic() - t0, 1), "usage": u,
    }
    print(f"{pid} {p['name'][:30]:<30} actual {p['actual_hours']:>5}  original {p['est_hours']:>5} ({old_err:+.0f}%)  "
          f"app {est.expected_hours:>6.0f} ({app_err:+.0f}%)  in-range={row['actual_in_app_range']}  "
          f"${u['cost_usd']:.4f}  {row['seconds']}s", flush=True)
    return row


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", nargs="*", default=DEFAULT)
    ap.add_argument("--effort", choices=["low", "medium", "high"], help="override reasoning effort for the 3 agents")
    ap.add_argument("--out", default="data/runtime/backtest.json")
    args = ap.parse_args()
    rows = []
    for pid in args.projects:  # sequential: keeps the cache warm and the output readable
        rows.append(await one(pid, args.effort))
    summary = {
        "effort": args.effort or "default (medium)",
        "projects": len(rows),
        "original_mape_pct": round(mean(abs(r["original_error_pct"]) for r in rows), 1),
        "app_mape_pct": round(mean(abs(r["app_error_pct"]) for r in rows), 1),
        "original_mean_bias_pct": round(mean(r["original_error_pct"] for r in rows), 1),
        "app_mean_bias_pct": round(mean(r["app_error_pct"] for r in rows), 1),
        "actual_within_app_range": sum(r["actual_in_app_range"] for r in rows),
        "avg_cost_usd": round(mean(r["usage"]["cost_usd"] for r in rows), 5),
        "avg_input_tokens": round(mean(r["usage"]["input_tokens"] for r in rows)),
        "avg_cached_tokens": round(mean(r["usage"]["cached_tokens"] for r in rows)),
        "avg_output_tokens": round(mean(r["usage"]["output_tokens"] for r in rows)),
        "avg_seconds": round(mean(r["seconds"] for r in rows), 1),
    }
    print("\n" + json.dumps(summary, indent=2))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    print(f"saved -> {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
