"""Evaluate the agent system against a small labelled benchmark and the app's own records.

    python scripts/evaluate.py --live            # runs the model benchmarks too (about $0.03)
    python scripts/evaluate.py                   # free checks only (code, stored runs)

Writes data/evals/results/<timestamp>-<version>.json; the app's Evaluation page shows the latest result and the
history. Sections:
  extraction   Requirements Analyst on 5 sample briefs vs expected fields (live)
  scope        Scope Guard on 12 client messages vs the expected "billable change?" decision (live)
  estimate     estimator backtests on 6 past projects (data/evals/estimate_backtests.json, scripts/backtest.py)
  pricing      calculator vs an independent re-implementation of the pricing policy (code)
  staffing     proposed teams: real people, no double-booking, roles covered (stored deals)
  risk         Project Health detector vs the seeded risks in the synthetic delivery data (precision / recall)
  proposal     required sections present in every generated proposal (stored deals)
  operations   completion / failure, approval and revision rates, latency and cost per workflow (stored runs)
All data is synthetic: results measure the method, not performance on Empower's real projects.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core import guardrails, store  # noqa: E402
from backend.core.company import company  # noqa: E402
from backend.core.usage import reprice  # noqa: E402
from backend.modules.deal_desk import calculators as calc  # noqa: E402
from backend.modules.project_health import health  # noqa: E402

EVALS = ROOT / "data" / "evals"
BENCH = json.loads((EVALS / "benchmarks.json").read_text(encoding="utf-8"))
SAMPLES = {b["id"]: b for b in json.loads((ROOT / "data" / "sample_briefs.json").read_text(encoding="utf-8"))}
PROPOSAL_SECTIONS = {"scope": "## Scope", "exclusions": "Not included", "timeline": "## Timeline", "team": "## Team",
                     "pricing": "## Commercials", "milestones": "payment milestones", "assumptions": "## Assumptions",
                     "questions": "## Questions for you", "risks": "## Risks and how we manage them"}


def pct(a: float, b: float) -> float | None:
    return round(100 * a / b, 1) if b else None


# ---------------------------------------------------------------------------- live benchmarks


async def eval_extraction() -> dict:
    from backend.modules.deal_desk.agents import build_agent
    from backend.modules.deal_desk.tools import DealDeps

    c = company()
    agent = build_agent(c, "analyst")
    rows, cost = [], 0.0
    for exp in BENCH["extraction"]:
        b = SAMPLES[exp["id"]]
        clean, _ = guardrails.redact_ai_directed_lines(guardrails.screen_untrusted(b["brief"]).clean_text)
        prompt = ("Analyse this client request.\n\n" + guardrails.spotlight(clean) + "\n\nDetails entered by Empower staff (trusted): "
                  f"client name: {b['client_name']}; country: {b['client_country']}; quote currency: {b['currency']}.")
        t0 = time.time()
        res = await agent.run(prompt, deps=DealDeps(company=c, currency=b["currency"]))
        spec = res.output
        u = res.usage
        cost += (reprice({"input_tokens": u.input_tokens, "cached_tokens": u.details.get("cached_tokens", 0) if hasattr(u, "details") else 0,
                          "output_tokens": u.output_tokens}) or {}).get("cost_usd", 0)
        text = json.dumps(spec.model_dump()).lower()
        checks = {
            "project_type": spec.project_type in exp["project_type"],
            "compliance": (not exp["compliance_any"]) or any(x.lower() in " ".join(spec.compliance_flags).lower() for x in exp["compliance_any"]),
            "budget": (exp["budget_max"] is None and not spec.constraints.budget_max) or (
                exp["budget_max"] is not None and spec.constraints.budget_max is not None
                and abs(spec.constraints.budget_max - exp["budget_max"]) <= 0.01 * exp["budget_max"]),
            "deadline": bool(spec.constraints.deadline) == exp["deadline"],
            "integrations": (not exp["integrations_any"]) or any(x.lower() in text for x in exp["integrations_any"]),
            "asks_questions": len(spec.open_questions) >= 3,
        }
        rows.append({"id": exp["id"], "checks": checks, "passed": sum(checks.values()), "of": len(checks),
                     "seconds": round(time.time() - t0, 1), "project_type": spec.project_type,
                     "budget_max": spec.constraints.budget_max, "questions": len(spec.open_questions)})
    passed = sum(r["passed"] for r in rows)
    total = sum(r["of"] for r in rows)
    return {"metric": "field accuracy", "value_pct": pct(passed, total), "passed": passed, "total": total, "rows": rows,
            "cost_usd": round(cost, 4), "live": True}


async def eval_scope() -> dict:
    from backend.modules.scope_guard import data
    from backend.modules.scope_guard.pipeline import ScopeRun, new_state

    msgs = {m["id"]: m for m in data.sample_messages()}

    async def one(exp: dict) -> dict:
        m = msgs[exp["id"]]
        sow = data.get_sow(m["sow_id"])
        inp = {"sow_id": m["sow_id"], "subject": m["subject"], "message": m["text"], "source": "evaluation"}
        t0 = time.time()
        for attempt in range(2):  # a run that errors (gateway hiccup) is retried once; it is not a wrong answer
            state = new_state(uuid.uuid4().hex[:10], inp, sow, "eval", {"name": "evaluation"})
            await ScopeRun(state["id"], state, sow, save=False).run()
            if state["status"] != "failed":
                break
        items = ((state.get("results") or {}).get("pricing") or {}).get("items", [])
        got = len(items) > 0
        row = {"id": exp["id"], "expected_billable": exp["billable_change"], "got_billable": got, "correct": got == exp["billable_change"],
               "change_requests": len(items), "status": state["status"], "seconds": round(time.time() - t0, 1),
               "cost_usd": (state.get("usage") or {}).get("cost_usd", 0),
               "injection_removed": (state.get("screen") or {}).get("removed_lines", 0), "attempts": attempt + 1,
               "error": state.get("error")}
        if "expected_change_requests" in exp:
            row["count_correct"] = len(items) == exp["expected_change_requests"]
        return row

    sem = asyncio.Semaphore(4)

    async def guarded(e):
        async with sem:
            return await one(e)

    rows = await asyncio.gather(*(guarded(e) for e in BENCH["scope"]))
    answered = [r for r in rows if r["status"] != "failed"]
    correct = sum(r["correct"] for r in answered)
    return {"metric": "decision accuracy (billable change: yes / no)", "value_pct": pct(correct, len(answered)), "passed": correct,
            "total": len(answered), "errors": len(rows) - len(answered), "rows": rows,
            "cost_usd": round(sum(r["cost_usd"] or 0 for r in rows), 4), "live": True}


# ---------------------------------------------------------------------------- free checks


def eval_estimate() -> dict:
    d = json.loads((EVALS / "estimate_backtests.json").read_text(encoding="utf-8"))
    latest = [h for h in d["history"] if h["estimator_version"] == "v3" and h["effort"] == "low"][0]
    return {"metric": "mean absolute error vs actual hours (lower is better)", "value_pct": latest["app_mape_pct"],
            "baseline_pct": latest["original_mape_pct"], "history": d["history"], "rows": d["latest_rows"], "live": False}


def eval_pricing() -> dict:
    c = company()
    pol = c.policy
    rows = []
    for v in BENCH["pricing"]:
        rates = c.rate_card["billing_rates"][v["currency"]]
        list_tm = sum(h * rates[r] for r, h in v["hours"].items())
        d = min(v["discount_pct"], pol["max_discount_pct"])
        exp_tm = round(list_tm * (1 - d / 100), -2)
        exp_fixed = round(list_tm * (1 + pol["fixed_price_risk_premium_pct"] / 100) * (1 - d / 100), -2)
        cost = sum(h * c.role_cost_inr_per_hour[r] for r, h in v["hours"].items()) / c.rate_card["inr_per_unit"][v["currency"]]
        exp_needs = v["discount_pct"] > 5 or min((exp_fixed - cost) / exp_fixed, (exp_tm - cost) / exp_tm) * 100 < pol["margin_floor_pct"]
        est = SimpleNamespace(hours_by_role=v["hours"], total_hours=sum(v["hours"].values()))
        q = calc.price_options(c, est, v["currency"], v["discount_pct"], 10, "fixed")
        ok = q.options[0].price == exp_fixed and q.options[1].price == exp_tm and q.needs_approval == exp_needs and q.discount_pct == d
        rows.append({"case": f"{sum(v['hours'].values())} h, {v['currency']}, {v['discount_pct']}% asked", "expected_fixed": exp_fixed,
                     "got_fixed": q.options[0].price, "expected_tm": exp_tm, "got_tm": q.options[1].price,
                     "expected_needs_approval": exp_needs, "got_needs_approval": q.needs_approval, "correct": ok})
    ok = sum(r["correct"] for r in rows)
    return {"metric": "calculator matches an independent re-implementation", "value_pct": pct(ok, len(rows)), "passed": ok,
            "total": len(rows), "rows": rows, "live": False}


def eval_staffing() -> dict:
    c = company()
    rows = []
    for d in store.list_runs("deal_desk", 300):
        sch = (d.get("results") or {}).get("schedule")
        if not sch:
            continue
        team = sch["team"]
        bad = [m for m in team if m["emp_id"] not in c.employees or m.get("conflict") or m["allocation_pct"] > m["free_pct"] + 5]
        rows.append({"deal": d["id"], "title": d["title"], "people": len(team), "infeasible": len(bad),
                     "uncovered_roles": sch["uncovered_roles"], "feasible": not bad and not sch["uncovered_roles"]})
    ok = sum(r["feasible"] for r in rows)
    return {"metric": "proposed teams that are real, free and cover every role", "value_pct": pct(ok, len(rows)), "passed": ok,
            "total": len(rows), "rows": rows, "live": False}


def eval_risk() -> dict:
    c = company()
    rows, tp, fp, fn = [], 0, 0, 0
    for p in health.projects(c):
        a = health.assess(c, p)
        flagged, truth = a["level"] != "ok", p["seeded_risk"] != "none"
        tp += flagged and truth
        fp += flagged and not truth
        fn += truth and not flagged
        rows.append({"project": p["code"], "seeded_risk": p["seeded_risk"], "level": a["level"], "flagged": flagged,
                     "correct": flagged == truth})
    prec = round(tp / (tp + fp), 2) if tp + fp else None
    rec = round(tp / (tp + fn), 2) if tp + fn else None
    return {"metric": "risk detection on seeded synthetic projects", "precision": prec, "recall": rec,
            "value_pct": pct(sum(r["correct"] for r in rows), len(rows)), "rows": rows, "live": False,
            "caveat": "The problems were planted by scripts/generate_delivery_data.py, so this checks the detector's logic, not real-world accuracy."}


def eval_proposals() -> dict:
    rows = []
    for d in store.list_runs("deal_desk", 300):
        md = (d.get("results") or {}).get("proposal_markdown")
        if not md:
            continue
        have = {k: (v.lower() in md.lower()) for k, v in PROPOSAL_SECTIONS.items()}
        rows.append({"deal": d["id"], "title": d["title"], "sections": have, "complete_pct": pct(sum(have.values()), len(have))})
    return {"metric": "required proposal sections present", "value_pct": round(statistics.mean(r["complete_pct"] for r in rows), 1) if rows else None,
            "required": list(PROPOSAL_SECTIONS), "rows": rows, "live": False,
            "note": "Proposals generated before the risks section was added score lower on 'risks'."}


def eval_operations() -> dict:
    mods = ("deal_desk", "deal_room", "scope_guard", "project_health", "bench", "appraisals", "staffing")
    out = []
    for m in mods:
        runs = [r for r in store.list_runs(m, 1000) if not r.get("demo")]
        if not runs:
            continue
        done = [r for r in runs if r["status"] in ("ready", "approved", "rejected", "changes_requested", "needs_clarification")]
        failed = [r for r in runs if r["status"] in ("failed", "blocked", "interrupted")]
        secs = [max((s.get("ended_at") or 0) for s in r["steps"].values()) for r in done if r.get("steps")]
        costs = [(reprice(r.get("usage")) or {}).get("cost_usd", 0) for r in done]
        decided = [r for r in runs if r.get("decision")]
        out.append({"module": m, "runs": len(runs), "completed_pct": pct(len(done), len(runs)), "failed_pct": pct(len(failed), len(runs)),
                    "median_seconds": round(statistics.median(secs), 1) if secs else None,
                    "mean_cost_usd": round(statistics.mean(costs), 4) if costs else None,
                    "decided": len(decided),
                    "approved_pct": pct(sum(1 for r in decided if r["decision"].get("action") == "approve"), len(decided)),
                    "revised_pct": pct(sum(1 for r in runs if r.get("revisions") or r.get("orchestrator_revisions")), len(runs)) if m == "deal_desk" else None})
    return {"metric": "workflow operations (this installation's runs, excluding shipped examples)", "rows": out, "live": False}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="also run the model benchmarks (extraction, scope)")
    ap.add_argument("--version", default="v2.0")
    args = ap.parse_args()
    t0 = time.time()
    res = {"version": args.version, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "synthetic": True,
           "estimate": eval_estimate(), "pricing": eval_pricing(), "staffing": eval_staffing(), "risk": eval_risk(),
           "proposal": eval_proposals(), "operations": eval_operations()}
    if args.live:
        res["extraction"] = asyncio.run(eval_extraction())
        res["scope"] = asyncio.run(eval_scope())
    res["seconds"] = round(time.time() - t0, 1)
    out = EVALS / "results"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{res['at'][:19].replace(':', '').replace('-', '')}-{args.version}.json"
    path.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    for k in ("extraction", "scope", "estimate", "pricing", "staffing", "risk", "proposal"):
        if k in res:
            r = res[k]
            extra = f" precision {r['precision']} recall {r['recall']}" if k == "risk" else ""
            print(f"{k:10s} {r.get('value_pct')}%  {r['metric']}{extra}")
    print("saved", path)


if __name__ == "__main__":
    main()
