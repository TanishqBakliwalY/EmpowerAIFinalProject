"""Cross-module views: the management Home, Agent Activity, recommendation reviews, audit trail and settings.

Every number here is computed from the same stores the agents use (runs, the delivery tracker, assignments, the rate
card). Values are converted to USD with the rate card's own exchange rates so different currencies can be added up.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core import auth, store
from ...core.company import company
from ...core.config import (
    DAILY_BUDGET_USD, MAX_BRIEF_CHARS, MODEL_NAME, RUN_REQUEST_LIMIT, RUN_TOOL_CALLS_LIMIT, RUN_TOTAL_TOKENS_LIMIT,
    RUNS_PER_HOUR_PER_CLIENT,
)
from ...core.usage import prices, reprice, reprice_run
from ..deal_desk import calculators as calc

router = APIRouter(prefix="/api", tags=["ops"])

MODULES_BY_ROLE = {
    "director": ("deal_desk", "deal_room", "scope_guard", "project_health", "staffing", "bench", "appraisals"),
    "sales": ("deal_desk", "deal_room", "scope_guard", "project_health", "staffing"),
    "hr": ("bench", "appraisals", "staffing"),
}
MODULE_LABEL = {"deal_desk": "Deal Desk", "deal_room": "Deal Room", "scope_guard": "Scope Guard", "project_health": "Project Health",
                "staffing": "Staffing", "bench": "Bench Optimizer", "appraisals": "Appraisals & hikes"}
LINKS = {"deal_desk": "#/deals/{}", "deal_room": "#/activity/{}", "scope_guard": "#/scope/{}", "project_health": "#/activity/{}",
         "staffing": "#/activity/{}", "bench": "#/bench", "appraisals": "#/appraisals/{}"}
# One vocabulary for run status across modules.
STATUS = {"queued": "queued", "running": "running", "ready": "awaiting_approval", "approved": "completed",
          "rejected": "completed", "changes_requested": "needs_information", "needs_clarification": "needs_information",
          "failed": "failed", "blocked": "blocked", "interrupted": "failed"}
SEV_RANK = {"critical": 0, "warning": 1, "info": 2}
NO_APPROVAL = ("deal_room", "staffing")  # rehearsals and staffing answers are advice, not decisions


def norm_status(module: str, status: str) -> str:
    if module in NO_APPROVAL and status == "ready":
        return "completed"
    return STATUS.get(status, status)


def usd(amount: float | None, cur: str | None) -> float:
    if not amount:
        return 0.0
    v = calc.convert(company(), float(amount), (cur or "USD").upper(), "USD")
    return round(v or 0.0, 2)


def clip(text: str | None, n: int) -> str:
    """Shorten at a word boundary with an ellipsis, so a card never ends mid-word."""
    text = (text or "").strip()
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _creator(r: dict) -> str:
    return r.get("created_by") or (r.get("input") or {}).get("created_by") or ("example run" if r.get("demo") else "")


def _duration(r: dict) -> float | None:
    ends = [s.get("ended_at") for s in (r.get("steps") or {}).values() if s.get("ended_at")]
    return round(max(ends), 1) if ends else None


def _summary(module: str, r: dict) -> str:
    res = r.get("results") or {}
    if module == "deal_desk":
        rev = res.get("review") or {}
        q = res.get("quote") or {}
        opt = next((o for o in q.get("options", []) if o["model"] == q.get("recommended_model")), None)
        return (f"{q.get('currency', '')} {opt['price']:,.0f} recommended; critic: {rev.get('verdict', 'n/a')}" if opt else r.get("error") or "")
    if module == "deal_room":
        o = res.get("outcome") or {}
        return (res.get("coach") or {}).get("headline") or o.get("result", "")
    if module == "project_health":
        return "; ".join(f"{k}: {v.get('headline', '')}" for k, v in list((res.get("reviews") or {}).items())[:2])
    steps = [s for s in (r.get("steps") or {}).values() if s.get("summary")]
    return steps[-1]["summary"] if steps else (r.get("error") or "")


def _tools(r: dict) -> int:
    return sum(1 for e in r.get("trace", []) if e.get("kind") == "tool_call")


def activity_rows(user: dict, limit: int = 60, module: str | None = None) -> list[dict]:
    mods = [m for m in MODULES_BY_ROLE[user["role"]] if not module or m == module]
    rows = []
    for m in mods:
        for r in store.list_runs(m, limit):
            u = reprice(r.get("usage")) or {}
            agents = [s["label"] for s in (r.get("steps") or {}).values() if s.get("kind") == "agent" and s.get("status") != "skipped"]
            rows.append({
                "id": r["id"], "module": m, "module_label": MODULE_LABEL[m], "title": r.get("title"), "status": norm_status(m, r["status"]),
                "raw_status": r["status"], "created_at": r["created_at"], "trigger": _creator(r) or "unknown",
                "agents": agents, "tool_calls": _tools(r), "seconds": _duration(r), "cost_usd": u.get("cost_usd"),
                "summary": clip(_summary(m, r), 240), "approval": (r.get("decision") or {}).get("action"),
                "approver": (r.get("decision") or {}).get("approver"), "link": LINKS[m].format(r["id"]),
                "retryable": r["status"] in ("failed", "blocked", "interrupted") and m in ("deal_desk", "project_health"),
                "demo": bool(r.get("demo")),
            })
    rows.sort(key=lambda x: x["created_at"], reverse=True)
    return rows[:limit]


# ---------------------------------------------------------------------------- Agent Activity


@router.get("/activity")
def activity(module: str | None = None, user: dict = Depends(auth.current_user)) -> list[dict]:
    return activity_rows(user, 200, module)


@router.get("/activity/{run_id}")
def activity_detail(run_id: str, user: dict = Depends(auth.current_user)) -> dict:
    r = store.get_run(run_id)
    if not r or r.get("module") not in MODULES_BY_ROLE[user["role"]]:
        raise HTTPException(404, "No such run (or not visible to your role).")
    r = reprice_run(r)
    r.pop("client_ip", None)
    r["module_label"] = MODULE_LABEL.get(r["module"], r["module"])
    r["norm_status"] = norm_status(r["module"], r["status"])
    r["audit"] = store.list_audit(50, entity_id=run_id)
    if r["module"] == "deal_desk":
        from ..deal_desk.pipeline import collaboration
        r["collaboration"] = collaboration(r)
    return r


@router.post("/activity/{run_id}/retry")
async def retry(run_id: str, request: Request, user: dict = Depends(auth.require_role("director", "sales"))) -> dict:
    """Safe retry: the same input runs again as a new run; the failed run is kept for the record."""
    r = store.get_run(run_id)
    if not r or r["status"] not in ("failed", "blocked", "interrupted"):
        raise HTTPException(409, "Only failed or blocked runs can be retried.")
    ip = request.client.host if request.client else "unknown"
    if r["module"] == "deal_desk":
        from ..deal_desk import pipeline as dp
        new_id = dp.start_run(dict(r["input"]), ip)
    elif r["module"] == "project_health":
        from ..project_health import pipeline as hp
        new_id = hp.start(r["input"].get("projects"), user, ip)
    else:
        raise HTTPException(409, "Retry is available for Deal Desk and delivery reviews.")
    store.audit(user, "run.retried", r["module"], new_id, f"Retried run {run_id}", {"previous": run_id})
    return {"id": new_id, "module": r["module"]}


# ---------------------------------------------------------------------------- recommendations


class Review(BaseModel):
    status: Literal["accepted", "dismissed", "open"]
    note: str = Field(default="", max_length=1000)


@router.post("/recommendations/{key}/review")
def review_recommendation(key: str, body: Review, user: dict = Depends(auth.current_user)) -> dict:
    if not key or len(key) > 80:
        raise HTTPException(422, "Bad key.")
    store.review_recommendation(key, body.status, user, body.note.strip())
    store.audit(user, f"recommendation.{body.status}", "recommendation", key, f"Recommendation {key} {body.status}",
                {"note": body.note.strip()})
    return {"ok": True}


def priority_actions(user: dict, c) -> list[dict]:
    from ..project_health import health
    from ..project_health.pipeline import latest_reviews
    from ..staffing import availability as av

    role, mods = user["role"], MODULES_BY_ROLE[user["role"]]
    out: list[dict] = []
    if "deal_desk" in mods:
        for d in store.list_runs("deal_desk", 200):
            if d["status"] != "ready":
                continue
            r = d.get("results") or {}
            q, rev, sch = r.get("quote") or {}, r.get("review") or {}, r.get("schedule") or {}
            opt = next((o for o in q.get("options", []) if o["model"] == q.get("recommended_model")), None)
            if not opt:
                continue
            sev = "critical" if q.get("needs_approval") or rev.get("verdict") == "escalate" else "warning"
            ev = [x for x in [q.get("budget_fit"), "Misses the client's deadline" if sch.get("meets_deadline") is False else None,
                              *(q.get("approval_reasons") or [])] if x]
            out.append({"key": f"deal:{d['id']}", "kind": "deal", "severity": sev, "title": f"Decide on {d['title']}",
                        "finding": f"Quote ready: {opt['currency']} {opt['price']:,.0f} ({'fixed' if opt['model'] == 'fixed' else 'T&M'}); "
                                   f"critic verdict {rev.get('verdict', 'n/a')}.",
                        "evidence": ev[:3], "impact": f"{opt['currency']} {opt['price']:,.0f} of new business",
                        "impact_usd": usd(opt["price"], opt["currency"]), "urgency": "this week",
                        "agent": "Deal Desk (7 agents) · Deal Critic", "recommendation": clip(rev.get("go_no_go"), 300),
                        "link": f"#/deals/{d['id']}", "action_label": "Open the deal to decide"})
    if "project_health" in mods:
        reviews = latest_reviews()
        for p in health.all_health(c):
            if p["level"] == "ok":
                continue
            top = sorted(p["signals"], key=lambda s: SEV_RANK[s["severity"]])[0]
            m = p["metrics"]
            impact_usd = usd(m["overrun_cost"], p["currency"]) if m["overrun_cost"] else (
                usd(p["contract_value"], p["currency"]) if p["status"] == "starting" else 0)
            rv = reviews.get(p["code"])
            out.append({"key": f"risk:{p['code']}", "kind": "project", "severity": p["level"],
                        "title": f"{p['code']} {p['name']} ({p['client']}) is at risk",
                        "finding": top["finding"], "evidence": [s["evidence"] for s in p["signals"][:3]],
                        "impact": top["impact"], "impact_usd": impact_usd,
                        "urgency": "today" if p["level"] == "critical" else "this week",
                        "agent": "Project Health · Delivery Risk Agent" if rv else "Project Health (code indicators)",
                        "recommendation": (rv or {}).get("headline") or top["recommendation"],
                        "link": f"#/projects/{p['code']}", "action_label": "Open the project"})
    if "scope_guard" in mods:
        for r in store.list_runs("scope_guard", 200):
            if r["status"] != "ready":
                continue
            items = ((r.get("results") or {}).get("pricing") or {}).get("items", [])
            val = sum(i["price"] for i in items)
            cur = ((r.get("results") or {}).get("pricing") or {}).get("currency", "USD")
            out.append({"key": f"scope:{r['id']}", "kind": "scope", "severity": "warning" if items else "info",
                        "title": f"Scope decision: {r['title']}",
                        "finding": f"{len(items)} change request(s) found" if items else "No billable change found; confirm the reply.",
                        "evidence": [clip(i["summary"], 120) for i in items[:3]],
                        "impact": f"{cur} {val:,.0f} billable if approved" if items else "Client reply pending",
                        "impact_usd": usd(val, cur), "urgency": "this week", "agent": "Scope Guard (4 agents)",
                        "recommendation": "Approve the change request and send the drafted reply, or ask the client to clarify.",
                        "link": f"#/scope/{r['id']}", "action_label": "Review in Scope Guard"})
    if "bench" in mods or role == "director":
        soon = []
        for e in c.employees.values():
            nxt = [a for a in c.assignments if a.emp_id == e.emp_id and a.kind == "project" and a.end >= c.as_of]
            cur_end = max((a.end for a in nxt if a.start <= c.as_of), default=None)
            after = [a for a in nxt if cur_end and a.start > cur_end]
            if cur_end and cur_end <= c.as_of + timedelta(days=28) and not after:
                soon.append((e, cur_end))
        if soon:
            cost_week = sum(c.role_cost_inr_per_hour.get(e.role, 1000) * 40 for e, _ in soon) / c.rate_card["inr_per_unit"]["USD"]
            out.append({"key": f"bench:{c.as_of.isoformat()}", "kind": "bench", "severity": "warning",
                        "title": f"{len(soon)} people roll off in the next 4 weeks with nothing booked",
                        "finding": "Their current assignments end and no next project is assigned.",
                        "evidence": [f"{e.name} ({e.role}) free from {d.isoformat()}" for e, d in sorted(soon, key=lambda x: x[1])[:4]],
                        "impact": f"≈ USD {cost_week:,.0f} of internal cost per idle week (estimate)", "impact_usd": round(cost_week * 4),
                        "urgency": "this week", "agent": "Bench Optimizer · Staffing",
                        "recommendation": "Run a bench plan to match them to pipeline deals or internal work before they go idle.",
                        "link": "#/bench", "action_label": "Plan the bench"})
    if "appraisals" in mods:
        for r in store.list_runs("appraisals", 20):
            if r["status"] == "ready":
                out.append({"key": f"hikes:{r['id']}", "kind": "hikes", "severity": "warning", "title": f"Approve {r['title']}",
                            "finding": "The fairness audit finished; HR approval is needed before managers see anything.",
                            "evidence": [], "impact": "Annual pay decisions for the whole team", "impact_usd": 0,
                            "urgency": "this month", "agent": "Appraisals (4 agents)",
                            "recommendation": "Review the fairness findings and approve or request changes.",
                            "link": f"#/appraisals/{r['id']}", "action_label": "Review the cycle"})
    conf = {
        "deal": ("Model judgement on computed numbers", "Prices, hours and dates are computed by code; the go / no-go is the Deal Critic's judgement."),
        "project": ("Computed from the tracker", "Earned value, milestone and dependency signals are arithmetic on the delivery tracker (synthetic data)."),
        "scope": ("Model classification, clause-checked", "The Scope Matcher's verdicts must cite SOW clauses that exist; prices use the SOW's own rates."),
        "bench": ("Computed from assignments", "Assignment end dates and bookings; the idle cost is an estimate at internal cost rates."),
        "hikes": ("Code-computed, audit by model", "Hikes are split by code to the rupee; the fairness audit is a model's reading of code-computed gaps."),
    }
    reviews_done = store.recommendation_reviews()
    for a in out:
        a["confidence"] = {"label": conf[a["kind"]][0], "why": conf[a["kind"]][1]}
        rv = reviews_done.get(a["key"])
        a["review"] = {"status": rv["status"], "by": rv["actor"], "at": rv["ts"], "note": rv["note"]} if rv and rv["status"] != "open" else None
    out.sort(key=lambda a: (a["review"] is not None, SEV_RANK[a["severity"]] if a["severity"] in SEV_RANK else 1, -a["impact_usd"]))
    return out


# ---------------------------------------------------------------------------- Home


@router.get("/home")
def home(user: dict = Depends(auth.current_user)) -> dict:
    from ..project_health import health
    from ..staffing import availability as av

    c = company()
    mods = MODULES_BY_ROLE[user["role"]]
    actions = priority_actions(user, c)
    open_actions = [a for a in actions if not a["review"]]
    kpis = []
    deals = store.list_runs("deal_desk", 300) if "deal_desk" in mods else []

    def deal_value(d):
        q = (d.get("results") or {}).get("quote") or {}
        opt = next((o for o in q.get("options", []) if o["model"] == q.get("recommended_model")), None)
        return usd(opt["price"], opt["currency"]) if opt else 0.0

    if "deal_desk" in mods:
        pending = [d for d in deals if d["status"] == "ready"]
        kpis.append({"key": "deals", "label": "Deals awaiting approval", "value": len(pending),
                     "foot": f"≈ USD {sum(deal_value(d) for d in pending):,.0f} quoted value", "link": "#/deals?status=ready",
                     "tone": "amber" if pending else "green"})
    risk_rows = health.all_health(c) if "project_health" in mods else []
    if "project_health" in mods:
        at_risk = [p for p in risk_rows if p["level"] != "ok"]
        crit = sum(1 for p in at_risk if p["level"] == "critical")
        kpis.append({"key": "projects", "label": "Projects at risk", "value": len(at_risk),
                     "foot": f"{crit} critical · of {len(risk_rows)} active", "link": "#/projects?level=risk",
                     "tone": "red" if crit else "amber" if at_risk else "green"})
    scope_pending = [r for r in store.list_runs("scope_guard", 300) if r["status"] in ("ready", "needs_clarification")] if "scope_guard" in mods else []
    if "scope_guard" in mods:
        kpis.append({"key": "scope", "label": "Scope changes to review", "value": len(scope_pending),
                     "foot": f"{sum(1 for r in scope_pending if r['status'] == 'needs_clarification')} waiting on the client",
                     "link": "#/scope?status=pending", "tone": "amber" if scope_pending else "green"})
    free4 = sum(1 for e in c.employees if av.free_pct(c, e, None, 4) >= 50)
    week = [min(100, av.weekly_allocation(c, e, None, 1, include_leave=False)[0]) for e in c.employees]
    kpis.append({"key": "available", "label": "Available in the next 4 weeks", "value": free4,
                 "foot": "people at least 50% free", "link": "#/staffing?free=4", "tone": "blue"})
    kpis.append({"key": "bench", "label": "Utilisation this week", "value": f"{round(sum(week) / max(1, len(week)))}%",
                 "foot": f"{sum(1 for a in week if a == 0)} people fully on the bench", "link": "#/bench", "tone": "blue"})
    stake = sum(a["impact_usd"] for a in open_actions)
    kpis.append({"key": "impact", "label": "Value in pending decisions", "value": f"≈ ${stake / 1000:,.0f}k",
                 "foot": "estimate: quotes, change requests, forecast overruns, idle cost", "link": "#/home?section=actions",
                 "tone": "violet", "estimate": True})

    # Business outlook
    outlook = {}
    if deals:
        by = {}
        for d in deals:
            k = {"ready": "Awaiting decision", "approved": "Approved", "rejected": "Rejected", "changes_requested": "Changes requested"}.get(d["status"])
            if k:
                b = by.setdefault(k, {"label": k, "count": 0, "usd": 0.0})
                b["count"] += 1
                b["usd"] += deal_value(d)
        outlook["pipeline"] = {"note": "Quoted value of Deal Desk proposals, converted to USD at the rate card's rates. Not a revenue forecast.",
                               "rows": list(by.values())}
    if risk_rows:
        outlook["delivery"] = {"note": "Code indicators from the delivery tracker (synthetic).",
                               "counts": {lvl: sum(1 for p in risk_rows if p["level"] == lvl) for lvl in ("critical", "warning", "ok")},
                               "projects": [{"code": p["code"], "level": p["level"], "cpi": p["metrics"]["cpi"], "spi": p["metrics"]["spi"]} for p in risk_rows]}
    weeks = av.week_starts(c, None, 12)
    util = [round(sum(min(100, av.weekly_allocation(c, e, w, 1, include_leave=True)[0]) for e in c.employees) / max(1, len(c.employees)))
            for w in weeks]
    free_from = []
    for w in weeks[:8]:
        n = sum(1 for e in c.employees if av.free_pct(c, e, w, 1) >= 50)
        free_from.append(n)
    outlook["utilisation"] = {"note": "Planned allocation from current assignments and leave (a plan, not actuals).",
                              "weeks": [w.isoformat() for w in weeks], "pct": util}
    outlook["availability"] = {"note": "People at least 50% free in that week, from current assignments.",
                               "weeks": [w.isoformat() for w in weeks[:8]], "count": free_from}
    spend = ({"today_usd": round(store.spent_today_usd(), 4), "budget_usd": DAILY_BUDGET_USD} if user["role"] in ("director", "sales") else None)
    return {"user": user, "as_of": c.as_of.isoformat(), "synthetic": c.is_synthetic(), "kpis": kpis, "actions": actions, "ai_spend": spend,
            "outlook": outlook, "activity": activity_rows(user, 8), "allowed": {m: True for m in mods}}


# ---------------------------------------------------------------------------- audit + settings


@router.get("/audit", dependencies=[Depends(auth.require_role("director"))])
def audit_trail(entity_id: str | None = None) -> list[dict]:
    return store.list_audit(300, entity_id)


@router.get("/settings")
def settings(user: dict = Depends(auth.current_user)) -> dict:
    c = company()
    pol = c.policy
    return {
        "editable": False,
        "note": "Policies live in the company data folder (rate_card.json) and change by an audited edit, not from the app.",
        "model": MODEL_NAME, "prices_per_million_tokens_usd": prices(),
        "data": {"folder": c.data_dir.name, "as_of": c.as_of.isoformat(), "synthetic": c.is_synthetic(), "description": c.meta.get("description")},
        "pricing_policy": {
            "margin_floor_pct": pol["margin_floor_pct"], "target_margin_pct": pol["target_margin_pct"],
            "discount_without_director_pct": 5, "max_discount_pct": pol["max_discount_pct"],
            "fixed_price_risk_premium_pct": pol["fixed_price_risk_premium_pct"], "contingency_pct": pol["contingency_pct"],
            "pm_overhead_pct": pol["pm_overhead_pct"], "lead_overhead_pct": pol["lead_overhead_pct"],
            "min_qa_ratio_pct": pol["min_qa_ratio_pct"], "regulated_qa_uplift_pct": pol.get("regulated_qa_uplift_pct"),
            "billing_rates": c.rate_card["billing_rates"],
        },
        "approvals": [
            {"what": "Deal outside pricing policy (discount over 5% or margin below the floor)", "who": "Director, with a written reason"},
            {"what": "Deal within policy", "who": "Director or Sales"},
            {"what": "Scope change request (approve, reject, ask the client)", "who": "Director or Sales"},
            {"what": "Hike cycle", "who": "HR or Director"},
            {"what": "Bench plan", "who": "HR or Director"},
            {"what": "Delivery mitigation plan", "who": "Director or Sales"},
        ],
        "limits": {"model_calls_per_run": RUN_REQUEST_LIMIT, "tool_calls_per_run": RUN_TOOL_CALLS_LIMIT,
                   "tokens_per_run": RUN_TOTAL_TOKENS_LIMIT, "daily_budget_usd": DAILY_BUDGET_USD,
                   "deal_runs_per_hour_per_client": RUNS_PER_HOUR_PER_CLIENT, "max_document_chars": MAX_BRIEF_CHARS},
        "roles": {"director": "Everything, including approvals outside pricing policy and salary data",
                  "sales": "Deal Desk, Deal Room, Emi, Scope Guard, Project Health, Staffing",
                  "hr": "Appraisals & hikes, Bench, Staffing"},
    }


# ---------------------------------------------------------------------------- evaluation


def _eval_files():
    from ...core.config import ROOT
    d = ROOT / "data" / "evals" / "results"
    return sorted(d.glob("*.json")) if d.exists() else []


@router.get("/evaluation", dependencies=[Depends(auth.require_role("director", "sales"))])
def evaluation() -> dict:
    import json as _json

    files = _eval_files()
    results = [_json.loads(f.read_text(encoding="utf-8")) for f in files]
    history = [{"file": f.name, "version": r.get("version"), "at": r.get("at"),
                **{k: (r[k].get("value_pct") if isinstance(r.get(k), dict) else None)
                   for k in ("extraction", "scope", "estimate", "pricing", "staffing", "risk", "proposal")}}
               for f, r in zip(files, results)]
    live = next((r for r in reversed(results) if "scope" in r), None)
    latest = results[-1] if results else None
    if latest and live and "scope" not in latest:  # carry the last model benchmark forward, labelled with its date
        latest = {**latest, "extraction": {**live["extraction"], "from_run": live["at"]}, "scope": {**live["scope"], "from_run": live["at"]}}
    return {"latest": latest, "history": history}


@router.post("/evaluation/run", dependencies=[Depends(auth.require_role("director"))])
def run_free_evaluation(user: dict = Depends(auth.current_user)) -> dict:
    """Re-run the free checks (code and stored runs, no model calls) and save them as a new result."""
    import importlib.util
    import json as _json
    from datetime import datetime as _dt, timezone as _tz

    from ...core.config import ROOT
    spec = importlib.util.spec_from_file_location("evaluate", ROOT / "scripts" / "evaluate.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    res = {"version": "v2.0", "at": _dt.now(_tz.utc).isoformat(timespec="seconds"), "synthetic": True, "trigger": user["name"],
           "estimate": ev.eval_estimate(), "pricing": ev.eval_pricing(), "staffing": ev.eval_staffing(), "risk": ev.eval_risk(),
           "proposal": ev.eval_proposals(), "operations": ev.eval_operations()}
    out = ROOT / "data" / "evals" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{res['at'][:19].replace(':', '').replace('-', '')}-v2.0-app.json").write_text(_json.dumps(res, indent=1, default=str), encoding="utf-8")
    store.audit(user, "evaluation.run", "evaluation", res["at"], "Re-ran the free evaluation checks")
    return {"ok": True}
