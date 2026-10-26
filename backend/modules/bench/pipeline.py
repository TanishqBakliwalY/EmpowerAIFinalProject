"""A Bench Optimizer run: who hands work to whom.

    forecast (code) -> Matcher -> match checks (code) -> Upskilling Planner (+ code checks) -> Bench Brief
        -> waiting for a director / HR decision

Agents propose; calculators validate every match and course and compute hours and costs; a person approves.

Command line (no web server):  python -m backend.modules.bench.pipeline --weeks 12
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import timedelta
from typing import Any

from pydantic_ai.exceptions import UsageLimitExceeded

from ...core import store
from ...core.company import CompanyData, company
from ...core.config import MODEL_NAME
from ...core.runner import RunRecorder
from . import calculators as calc
from .agents import SPECS, build_agent
from .data import courses, internal_work
from .models import BenchBrief, MatchPlan, UpskillPlan
from .tools import BenchDeps

MODULE_KEY = "bench"
ACTIVE: dict[str, dict[str, Any]] = {}
_TASKS: set[asyncio.Task] = set()

STEP_ORDER = [
    ("forecast", "Bench forecast", "code", "Who comes free when, bench FTE and cost, demand from deals and internal work."),
    ("matcher", SPECS["matcher"].label, "agent", SPECS["matcher"].job),
    ("checks", "Match checks", "code", "Checks every match: person, role, free time, skills, capacity; counts hours and cost."),
    ("upskill", SPECS["upskill"].label, "agent", SPECS["upskill"].job),
    ("brief", SPECS["brief"].label, "agent", SPECS["brief"].job),
]


def deal_states() -> list[dict]:
    from ..deal_desk import pipeline as deal_pipeline  # deals are read-only here

    rows = store.list_runs("deal_desk", 200)
    return [deal_pipeline.ACTIVE.get(d["id"]) or d for d in rows]


def forecast_bundle(c: CompanyData, horizon: int, min_free_pct: int, deals_raw: list[dict] | None = None) -> dict:
    """Everything the forecast view and the first pipeline step need (no model calls)."""
    rolls = calc.rolloffs(c, horizon, min_free_pct)
    weekly = calc.weekly_forecast(c, horizon)
    deals = calc.deal_demand(c, deal_states() if deals_raw is None else deals_raw)
    internal = calc.internal_demand(internal_work())
    gaps = calc.skills_gap(c, deals, rolls, courses())
    return {
        "as_of": c.as_of.isoformat(), "horizon_weeks": horizon, "min_free_pct": min_free_pct,
        "horizon_end": (c.as_of + timedelta(weeks=horizon)).isoformat(),
        "rolloffs": rolls, "weekly": weekly, "deals": deals, "internal": internal, "gaps": gaps,
        "totals": {
            "people_rolling_off": len(rolls),
            "on_bench_now": sum(1 for r in rolls if r["status"] == "on_bench_now"),
            "rolling_off_later": sum(1 for r in rolls if r["status"] == "rolling_off"),
            "bench_fte_avg_8w": calc.r1(sum(w["bench_fte"] for w in weekly[:8]) / max(1, min(8, len(weekly)))),
            "bench_cost_if_nothing_inr": round(sum(w["bench_cost_inr"] for w in weekly)),
            "bench_cost_8w_inr": round(sum(w["bench_cost_inr"] for w in weekly[:8])),
        },
    }


def new_state(run_id: str, inp: dict[str, Any], client_ip: str, user: dict | None) -> dict[str, Any]:
    return {
        "id": run_id, "module": MODULE_KEY, "status": "queued", "created_at": store.now_iso(),
        "title": f"Bench plan · next {inp['horizon_weeks']} weeks", "model": MODEL_NAME, "input": inp,
        "client_ip": client_ip, "created_by": (user or {}).get("name"),
        "steps": {k: {"key": k, "label": label, "kind": kind, "job": job, "status": "pending"} for k, label, kind, job in STEP_ORDER},
        "trace": [], "results": {}, "decision": None, "error": None,
    }


def _numbers(obj: Any) -> list[float]:
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in _numbers(v)]
    if isinstance(obj, (list, tuple)):
        return [n for v in obj for n in _numbers(v)]
    return []


# Self-explanatory names for the brief writer (the UI keeps the short keys).
BRIEF_NAMES = {
    "bench_hours_if_nothing": "idle_hours_if_no_plan",
    "bench_cost_if_nothing_inr": "idle_cost_if_no_plan_inr",
    "billable_hours_expected": "billable_hours_expected_weighted_by_win_chance",
    "bench_cost_covered_by_billable_inr": "idle_cost_turned_billable_inr",
    "idle_cost_remaining_inr": "idle_cost_still_remaining_after_plan_inr",
    "people_without_plan": "people_with_no_match_or_course",
}


class BenchRun:
    def __init__(self, run_id: str, state: dict[str, Any], company_data: CompanyData | None = None, save: bool = True,
                 deals_raw: list[dict] | None = None) -> None:
        self.c = company_data or company()
        self.state = state
        self.run_id = run_id
        self.save = save
        self.deals_raw = deals_raw
        self.rec = RunRecorder(run_id, MODULE_KEY, state, self.persist)
        self.agents = {k: build_agent(self.c, k) for k in SPECS}
        self.deps: BenchDeps | None = None

    def persist(self) -> None:
        if self.save:
            store.save_run(self.run_id, MODULE_KEY, self.state["status"], self.state["title"], self.state,
                           self.state.get("client_ip", ""))

    # ------------------------------------------------------------------ steps

    def forecast(self) -> None:
        inp = self.state["input"]
        self.rec.start_step("forecast")
        b = forecast_bundle(self.c, inp["horizon_weeks"], inp["min_free_pct"], self.deals_raw)
        r = self.state["results"]
        r.update({k: b[k] for k in ("rolloffs", "weekly", "deals", "internal", "gaps", "totals", "horizon_end")})
        from datetime import date

        self.deps = BenchDeps(company=self.c, horizon_weeks=inp["horizon_weeks"], min_free_pct=inp["min_free_pct"],
                              horizon_end=date.fromisoformat(b["horizon_end"]), rolloffs=b["rolloffs"], deals=b["deals"],
                              internal=b["internal"], gaps=b["gaps"])
        t = b["totals"]
        self.rec.event("forecast", "calculator", f"{t['people_rolling_off']} people free (>= {inp['min_free_pct']}%) within "
                                                 f"{inp['horizon_weeks']} weeks; bench cost if nothing is done: INR "
                                                 f"{calc.inr(t['bench_cost_if_nothing_inr'])}", t)
        self.rec.finish_step("forecast", f"{t['people_rolling_off']} people coming free, {len(b['deals'])} deals and "
                                         f"{len(b['internal'])} internal initiatives with demand")

    async def matcher(self) -> None:
        self.rec.start_step("matcher")
        plan: MatchPlan = await self.rec.run_agent(
            "matcher", self.agents["matcher"],
            "Plan matches for everyone in list_rolloffs. Use list_demand for deals and internal work.", self.deps)
        self.state["results"]["match_plan"] = plan.model_dump(mode="json")
        self.rec.finish_step("matcher", f"{len(plan.matches)} matches proposed; {len(plan.left_unmatched)} left unmatched")

    def checks(self) -> None:
        self.rec.start_step("checks")
        r = self.state["results"]
        proposed = r["match_plan"]["matches"]
        kept, rejected = calc.validate_matches(self.c, proposed, self.deps.deals, self.deps.internal, self.deps.rolloffs,
                                               self.deps.horizon_end)
        for v in rejected:
            self.rec.event("checks", "guardrail", f"Rejected {v.get('emp_id')} -> {v.get('target_id')}: " + "; ".join(v["issues"]))
        # Safety net: spare internal capacity goes to people who are still free and fit by role and skills.
        extra = calc.fill_internal_capacity(self.c, kept, self.deps.rolloffs, self.deps.internal, self.deps.horizon_end)
        if extra:
            self.rec.event("checks", "calculator", f"Calculator added {len(extra)} internal-work matches for people still free",
                           [f"{m['name']} -> {m['target_name']} {m['allocation_pct']}%" for m in extra])
        kept = kept + extra
        self.deps.matches = kept
        r["matches"], r["rejected_matches"] = kept, rejected
        flagged = sum(1 for m in kept if m["status"] == "flagged")
        r["value"] = calc.plan_value(self.c, r["weekly"], r["rolloffs"], kept, [])
        self.rec.finish_step("checks", f"{len(kept) - len(extra)} agent matches kept ({flagged} flagged), {len(rejected)} rejected, "
                                       f"{len(extra)} added by the calculator")

    async def upskill(self) -> None:
        self.rec.start_step("upskill")
        plan: UpskillPlan = await self.rec.run_agent(
            "upskill", self.agents["upskill"], "Plan courses for people who are still free after matching.", self.deps)
        r = self.state["results"]
        kept, rejected = calc.validate_upskilling(self.c, [i.model_dump() for i in plan.items], courses(), r["rolloffs"],
                                                  r["matches"], self.deps.horizon_end)
        r["upskilling"], r["rejected_upskilling"] = kept, rejected
        for v in rejected:
            self.rec.event("upskill", "guardrail", f"Rejected course {v.get('course_id')} for {v.get('emp_id')}: " + "; ".join(v["issues"]))
        r["value"] = calc.plan_value(self.c, r["weekly"], r["rolloffs"], r["matches"], kept)
        self.rec.finish_step("upskill", f"{len(kept)} courses planned ({len(rejected)} rejected)")

    async def brief(self) -> None:
        self.rec.start_step("brief")
        r = self.state["results"]
        v = r["value"]
        plan = {
            "horizon_weeks": self.state["input"]["horizon_weeks"],
            "figures": {BRIEF_NAMES.get(k, k): (f"INR {calc.inr(x)}" if k.endswith("_inr") else x) for k, x in v.items()},
            "matches": [{"person": f"{m['name']} ({m['title']})", "to": m["target_name"], "type": m["target_type"],
                         "allocation_pct": m["allocation_pct"], "from": m["start_date"], "weeks": m["weeks"], "fit": m["fit"],
                         "win_probability": m["win_probability"], "issues": m["issues"]} for m in r["matches"]][:20],
            "courses": [{"person": u["name"], "course": u["course"], "skill": u["skill"], "from": u["start_date"]}
                        for u in r["upskilling"]][:12],
            "still_without_plan_count": v["people_without_plan"],
            "still_without_plan_examples": [x["name"] for x in r["rolloffs"]
                                            if x["emp_id"] not in {m["emp_id"] for m in r["matches"]} | {u["emp_id"] for u in r["upskilling"]}][:8],
            "skill_gaps": [g["skill"] for g in r["gaps"] if g["gap"]][:8],
            "pending_deals": [d["title"] for d in r["deals"] if d["status"] != "approved"][:6],
        }
        self.deps.allowed_figures = _numbers(plan) + _numbers(v)
        brief: BenchBrief = await self.rec.run_agent(
            "brief", self.agents["brief"], "<plan>" + json.dumps(plan, ensure_ascii=False) + "</plan>", self.deps)
        r["brief"] = brief.model_dump(mode="json")
        self.rec.finish_step("brief", brief.headline[:140])

    # ------------------------------------------------------------------ the whole run

    async def run(self) -> None:
        st = self.state
        st["status"] = "running"
        self.persist()
        try:
            self.forecast()
            if not st["results"]["rolloffs"]:
                for k in ("matcher", "checks", "upskill", "brief"):
                    self.rec.skip_step(k, "Nobody is coming free in this horizon.")
                st["results"].update(matches=[], rejected_matches=[], upskilling=[], rejected_upskilling=[],
                                     value=calc.plan_value(self.c, st["results"]["weekly"], [], [], []))
            else:
                await self.matcher()
                self.checks()
                await self.upskill()
                await self.brief()
            st["status"] = "ready"
        except UsageLimitExceeded as exc:
            st["status"], st["error"] = "failed", f"Stopped by the per-run safety limit: {exc}"
            store.add_safety_event("run_limit_stop", "high", st["error"], self.run_id)
            self._fail_running_steps(st["error"])
        except Exception as exc:  # noqa: BLE001 -- a failed run must still be saved and shown
            st["status"], st["error"] = "failed", f"{type(exc).__name__}: {exc}"
            self._fail_running_steps(st["error"])
        finally:
            self.persist()
            ACTIVE.pop(self.run_id, None)

    def _fail_running_steps(self, why: str) -> None:
        for s in self.state["steps"].values():
            if s["status"] == "running":
                s.update(status="failed", summary=why)
            elif s["status"] == "pending":
                s["status"] = "skipped"


def start_run(inp: dict[str, Any], client_ip: str, user: dict | None = None) -> str:
    run_id = uuid.uuid4().hex[:10]
    state = new_state(run_id, inp, client_ip, user)
    run = BenchRun(run_id, state)  # builds agents now so a missing key fails the request, not the task
    ACTIVE[run_id] = state
    run.persist()
    task = asyncio.get_running_loop().create_task(run.run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return run_id


def get_state(run_id: str) -> dict | None:
    return ACTIVE.get(run_id) or store.get_run(run_id)


async def _cli() -> None:
    ap = argparse.ArgumentParser(description="Run one Bench Optimizer plan without the web server.")
    ap.add_argument("--weeks", type=int, default=12)
    ap.add_argument("--min-free", type=int, default=50)
    ap.add_argument("--out", help="write the run JSON here")
    args = ap.parse_args()
    run_id = uuid.uuid4().hex[:10]
    state = new_state(run_id, {"horizon_weeks": args.weeks, "min_free_pct": args.min_free}, "cli", None)
    await BenchRun(run_id, state).run()
    print(f"\nRun {run_id}: {state['status']} {state.get('error') or ''}")
    for s in state["steps"].values():
        u = s.get("usage") or {}
        print(f"  {s['label']:<20} {s['status']:<8} {s.get('seconds', 0):>6}s in={u.get('input_tokens', 0):>7} "
              f"cached={u.get('cached_tokens', 0):>7} out={u.get('output_tokens', 0):>6} ${u.get('cost_usd', 0):.5f} | {s.get('summary', '')}")
    u = state["usage"]
    print(f"  TOTAL in={u['input_tokens']} cached={u['cached_tokens']} out={u['output_tokens']} requests={u['requests']} "
          f"tools={u['tool_calls']} cost=${u['cost_usd']:.5f}")
    print("  value:", json.dumps(state["results"].get("value"), indent=1))
    if args.out:
        from pathlib import Path

        Path(args.out).write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(_cli())
