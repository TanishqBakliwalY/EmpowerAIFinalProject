"""Emi's specialist tools: the same code and agents the other modules use, so Emi answers from the shared data.

`capacity_check`, `pipeline_profit`, `upcoming_availability`, `scope_change_queue` and `project_health` are code over the
shared stores. `ask_delivery_risk_agent` delegates to the Delivery Risk Agent (a real sub-agent run whose tokens are
counted on Emi's message).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelResponse

from ...core import store
from ..deal_desk import calculators as calc
from ..project_health import health
from ..project_health.agent import RiskDeps, build_agent as build_risk_agent
from ..staffing import availability as av

ROLES = ("pm", "ba", "uiux", "fe", "be", "mobile", "qa", "devops", "data", "ml", "lead")


def _usd(c, amount: float, cur: str) -> float:
    return round(calc.convert(c, amount, cur, "USD") or 0, 2)


def capacity_check(ctx: RunContext[Any], hours_by_role: dict[str, float], start: str | None = None, weeks: int = 12) -> dict:
    """Can Empower take on work of this size without hiring? Compares required hours per role with the free
    capacity of current staff (from assignments and leave) over the window.

    Args:
        hours_by_role: required hours per role, e.g. {"mobile": 600, "be": 400, "qa": 200}. Roles: pm, ba, uiux, fe, be, mobile, qa, devops, data, ml, lead.
        start: ISO start date (default today).
        weeks: length of the window.
    """
    c = ctx.deps.company
    try:
        s = date.fromisoformat(start) if start else c.as_of
    except ValueError:
        s = c.as_of
    weeks = max(1, min(int(weeks), 52))
    rows, short = [], []
    for role, need in hours_by_role.items():
        if role not in ROLES:
            rows.append({"role": role, "error": "unknown role"})
            continue
        cap = av.team_capacity(c, role, s, weeks)
        free_hours = round(sum(cap["free_fte_by_week"]) * c.policy["hours_per_week"] * c.policy["productive_utilization"])
        gap = round(max(0.0, need - free_hours))
        rows.append({"role": role, "required_hours": need, "free_hours_in_window": free_hours, "headcount": cap["headcount"],
                     "shortfall_hours": gap})
        if gap:
            short.append(role)
    return {"window": f"{s.isoformat()} + {weeks} weeks", "roles": rows,
            "verdict": "fits current capacity" if not short else f"short on {', '.join(short)}: hire, subcontract, extend the timeline or start later",
            "basis": "free capacity = sum of unallocated FTE per week x 40 h x productive utilisation (policy); verified from assignments"}


def pipeline_profit(ctx: RunContext[Any], status: str = "open") -> list[dict]:
    """Deals ranked by gross profit if won at the recommended quote (price minus internal delivery cost, in USD at the
    rate card's exchange rates). This is the profit at the quoted price, not a forecast: win probability is unknown.

    Args:
        status: "open" (awaiting decision or changes requested), "approved", or "all".
    """
    c = ctx.deps.company
    keep = {"open": ("ready", "changes_requested"), "approved": ("approved",), "all": None}.get(status, ("ready", "changes_requested"))
    rows = []
    for d in store.list_runs("deal_desk", 200):
        if keep and d["status"] not in keep:
            continue
        q = (d.get("results") or {}).get("quote") or {}
        opt = next((o for o in q.get("options", []) if o["model"] == q.get("recommended_model")), None)
        if not opt or "internal_cost" not in q:
            continue
        margin = q["margin_pct_fixed"] if q["recommended_model"] == "fixed" else q["margin_pct_tm"]
        profit = opt["price"] - q["internal_cost"]
        rows.append({"deal_id": d["id"], "title": d["title"], "status": d["status"], "currency": q["currency"], "price": opt["price"],
                     "model": q["recommended_model"], "gross_profit_if_won": round(profit), "gross_profit_if_won_usd": _usd(c, profit, q["currency"]),
                     "margin_pct": margin, "needs_director": q["needs_approval"], "budget_fit": q.get("budget_fit")})
    rows.sort(key=lambda r: -r["gross_profit_if_won_usd"])
    return rows[:10]


def upcoming_availability(ctx: RunContext[Any], within_weeks: int = 5, role: str | None = None) -> list[dict]:
    """People whose current project work ends within the window and who have nothing booked after it.

    Args:
        within_weeks: look-ahead in weeks.
        role: optional role filter (pm, ba, uiux, fe, be, mobile, qa, devops, data, ml, lead).
    """
    c = ctx.deps.company
    horizon = c.as_of + timedelta(weeks=max(1, min(within_weeks, 26)))
    out = []
    for e in c.employees.values():
        if role and e.role != role:
            continue
        mine = [a for a in c.assignments if a.emp_id == e.emp_id and a.kind == "project" and a.end >= c.as_of]
        cur = [a for a in mine if a.start <= c.as_of]
        end = max((a.end for a in cur), default=None)
        if end and end <= horizon and not any(a.start > end for a in mine):
            out.append({"emp_id": e.emp_id, "name": e.name, "role": e.role, "level": e.level, "free_from": (end + timedelta(days=1)).isoformat(),
                        "current_project": ", ".join(sorted({a.project_name for a in cur})), "skills": list(e.skills)[:6]})
        elif not cur and not mine:
            out.append({"emp_id": e.emp_id, "name": e.name, "role": e.role, "level": e.level, "free_from": c.as_of.isoformat(),
                        "current_project": "on the bench now", "skills": list(e.skills)[:6]})
    out.sort(key=lambda r: r["free_from"])
    return out[:20]


def scope_change_queue(ctx: RunContext[Any]) -> list[dict]:
    """Client requests checked by Scope Guard that are (or contain) change orders, with status and price."""
    rows = []
    for r in store.list_runs("scope_guard", 100):
        p = (r.get("results") or {}).get("pricing") or {}
        items = p.get("items", [])
        rows.append({"id": r["id"], "title": r["title"], "status": r["status"], "sow_id": (r.get("sow") or {}).get("sow_id"),
                     "change_requests": [{"ask": i["summary"][:140], "hours": i["total_hours"], "price": i["price"]} for i in items],
                     "currency": p.get("currency"), "treat_as_change_order": bool(items)})
    return rows[:20]


def project_health(ctx: RunContext[Any], project_code: str | None = None) -> dict | list[dict]:
    """Delivery risk for active projects (code-computed: CPI/SPI, milestone slip, late dependencies, staffing, scope).
    Without a code, returns all projects ranked by risk; with a code, the full signals and evidence.

    Args:
        project_code: e.g. "A203" (optional).
    """
    c = ctx.deps.company
    rows = health.all_health(c)
    if project_code:
        r = next((x for x in rows if x["code"].lower() == project_code.strip().lower()), None)
        if not r:
            return {"error": f"No active project {project_code}. Codes: {', '.join(x['code'] for x in rows)}"}
        return {**r, "team": health.team_for(c, r["code"]), "data_note": "synthetic delivery tracker"}
    return [{"code": r["code"], "name": r["name"], "client": r["client"], "level": r["level"], "cpi": r["metrics"]["cpi"],
             "spi": r["metrics"]["spi"], "overrun_cost": r["metrics"]["overrun_cost"], "currency": r["currency"],
             "top_signal": r["signals"][0]["finding"] if r["signals"] else None} for r in rows]


async def ask_delivery_risk_agent(ctx: RunContext[Any], project_code: str) -> dict:
    """Ask the Delivery Risk Agent (a specialist sub-agent) to explain a project's risk and propose mitigations.
    Slower than project_health (it runs a model); use it when the user asks why a project is at risk or what to do.

    Args:
        project_code: e.g. "A207".
    """
    c = ctx.deps.company
    p = next((x for x in health.projects(c) if x["code"].lower() == project_code.strip().lower()), None)
    if not p:
        return {"error": f"No active project {project_code}."}
    r = health.assess(c, p)
    facts = {k: r[k] for k in ("code", "name", "client", "status", "contract_type", "currency", "contract_value", "start", "end",
                               "sow_id", "level", "signals", "metrics", "milestones", "dependencies")}
    res = await build_risk_agent().run("Review this project. Facts computed by code:\n<project>" + json.dumps(facts, ensure_ascii=False)
                                       + "</project>\nToday is " + c.as_of.isoformat() + ".", deps=RiskDeps(company=c), usage=ctx.usage)
    for m in res.new_messages():
        if isinstance(m, ModelResponse):
            ctx.deps.extra.add_response(m.usage)
            ctx.deps.extra.tool_calls += sum(1 for part in m.parts if getattr(part, "part_kind", "") == "tool-call")
    return {"agent": "Delivery Risk Agent", "review": res.output.model_dump(), "signals_from_code": r["signals"]}


SPECIALIST_TOOLS = [capacity_check, pipeline_profit, upcoming_availability, scope_change_queue, project_health, ask_delivery_risk_agent]
