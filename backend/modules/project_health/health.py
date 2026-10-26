"""Project Health: deterministic delivery-risk indicators for active projects.

Code computes every number here (earned value, forecast overrun, milestone slip, staffing and scope signals) from the
delivery tracker (data/seed/delivery/projects.json, synthetic), team assignments and the Scope Guard ledger. The
Delivery Risk Agent only explains these signals and proposes mitigations; it cannot change them.

    EV = budget hours x reported completion   PV = budget hours x time elapsed   AC = hours booked
    CPI = EV / AC (cost efficiency)           SPI = EV / PV (schedule efficiency)
    forecast hours at completion = budget / CPI
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...core import store
from ...core.company import CompanyData, company
from ..staffing import availability as av

CRITICAL, WARNING, INFO = "critical", "warning", "info"
CPI_CRITICAL, CPI_WARNING = 0.85, 0.95
SPI_CRITICAL, SPI_WARNING = 0.85, 0.95


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"projects": [], "synthetic": True}


def tracker(c: CompanyData | None = None) -> dict:
    c = c or company()
    return _load(str(c.data_dir / "delivery" / "projects.json"))


def projects(c: CompanyData | None = None) -> list[dict]:
    return tracker(c)["projects"]


def team_for(c: CompanyData, code: str) -> list[dict]:
    out = []
    for a in c.assignments:
        if a.kind == "project" and a.project_code == code and a.emp_id in c.employees:
            e = c.employees[a.emp_id]
            out.append({"emp_id": e.emp_id, "name": e.name, "role": e.role, "title": e.title, "level": e.level,
                        "allocation_pct": a.allocation_pct, "from": a.start.isoformat(), "until": a.end.isoformat()})
    return out


def scope_history(sow_id: str | None) -> dict:
    """Change requests for this project's SOW from the Scope Guard ledger (approved, pending, clarifying)."""
    if not sow_id:
        return {"approved_cr_hours": 0.0, "approved_cr_value": 0.0, "pending_checks": 0, "clarifications": 0, "checks": []}
    hours = value = 0.0
    pending = clar = 0
    checks = []
    for r in store.list_runs("scope_guard", 500):
        if (r.get("sow") or {}).get("sow_id") != sow_id:
            continue
        items = ((r.get("results") or {}).get("pricing") or {}).get("items", [])
        absorbed = set((r.get("decision") or {}).get("absorb_ask_ids", []))
        billable = [i for i in items if i["ask_id"] not in absorbed]
        if r["status"] == "approved":
            hours += sum(i["total_hours"] for i in billable)
            value += sum(i["price"] for i in billable)
        elif r["status"] == "ready":
            pending += 1
        elif r["status"] == "needs_clarification":
            clar += 1
        checks.append({"id": r["id"], "title": r["title"], "status": r["status"], "change_requests": len(items)})
    return {"approved_cr_hours": round(hours, 1), "approved_cr_value": round(value), "pending_checks": pending,
            "clarifications": clar, "checks": checks[:10]}


def _blended_cost_per_hour(c: CompanyData, team: list[dict], currency: str) -> float:
    roles = [m["role"] for m in team] or ["be"]
    inr = sum(c.role_cost_inr_per_hour.get(r, 1000) for r in roles) / len(roles)
    return inr / c.rate_card["inr_per_unit"].get(currency, 88.0)


def assess(c: CompanyData, p: dict, as_of: date | None = None) -> dict[str, Any]:
    """Metrics and evidence-backed signals for one project. Pure code; no model."""
    today = as_of or c.as_of
    start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
    span = max(1, (end - start).days)
    elapsed = min(1.0, max(0.0, (today - start).days / span))
    budget, booked, pct = p["budget_hours"], p["hours_booked"], p["pct_complete"]
    ev, pv = budget * pct, budget * elapsed
    cpi = round(ev / booked, 2) if booked else None
    spi = round(ev / pv, 2) if pv else None
    eac = round(budget / cpi) if cpi else budget
    overrun_h = max(0, eac - budget)
    team = team_for(c, p["code"])
    cost_h = _blended_cost_per_hour(c, team, p["currency"])
    overrun_cost = round(overrun_h * cost_h, -2)
    forecast_end = (start + timedelta(days=round(span / spi))) if spi and spi > 0 else end
    scope = scope_history(p.get("sow_id"))
    signals: list[dict] = []

    def sig(kind, sev, finding, evidence, impact, action):
        signals.append({"kind": kind, "severity": sev, "finding": finding, "evidence": evidence, "impact": impact,
                        "recommendation": action})

    cur = p["currency"]
    if p["status"] == "active" and elapsed >= 0.1:
        if cpi is not None and cpi < CPI_WARNING:
            sig("cost", CRITICAL if cpi < CPI_CRITICAL else WARNING,
                f"Effort is running ahead of progress (CPI {cpi}).",
                f"{booked:,} h booked for {pct:.0%} complete of a {budget:,} h budget (earned {ev:,.0f} h).",
                f"Forecast {eac:,} h at completion, {overrun_h:,} h over budget"
                + (f" ≈ {cur} {overrun_cost:,.0f} of internal cost on a fixed price." if p["contract_type"] == "fixed"
                   else f"; on T&M the client is billed ≈ {overrun_h:,} h more than planned."),
                "Re-baseline remaining work with the team, cut or phase low-value scope, and agree a change request if scope grew.")
        if spi is not None and spi < SPI_WARNING:
            slip = (forecast_end - end).days
            sig("schedule", CRITICAL if spi < SPI_CRITICAL else WARNING,
                f"Progress is behind plan (SPI {spi}).",
                f"{pct:.0%} complete with {elapsed:.0%} of the time used.",
                f"At this pace go-live moves from {end.isoformat()} to about {forecast_end.isoformat()} ({slip} days late).",
                "Re-plan the critical path; add capacity on the bottleneck or move non-critical scope to a later release.")
    for m in p["milestones"]:
        planned, forecast = date.fromisoformat(m["planned"]), date.fromisoformat(m["forecast"])
        if m["status"] == "late":
            days = (today - planned).days
            sig("milestone", CRITICAL if days > 14 else WARNING, f"Milestone overdue: {m['name']}.",
                f"Planned {m['planned']}, not done ({days} days overdue); forecast {m['forecast']}.",
                "Later milestones and the client's acceptance dates move with it.",
                "Agree a recovery date with the client and confirm what blocks completion.")
        elif m["status"] == "at_risk":
            sig("milestone", WARNING, f"Milestone forecast to slip: {m['name']}.",
                f"Planned {m['planned']}, forecast {m['forecast']} ({(forecast - planned).days} days late).",
                "Risk to the release plan.", "Pull the dependency or capacity issue forward now, before it is late.")
    for dep in p["dependencies"]:
        due = date.fromisoformat(dep["due"])
        if dep["status"] == "late" or (dep["status"] == "open" and due < today):
            sig("dependency", WARNING if (today - due).days <= 14 else CRITICAL,
                f"{dep['owner'].title()} dependency late: {dep['item']}.", f"Due {dep['due']}, still open.",
                "Blocks the work that depends on it; the delay is not Empower's, but it lands on the schedule.",
                f"Escalate to the {dep['owner']} with a dated request and log the delay (change-request grounds on a fixed price).")
    if p["status"] == "starting":
        have, want = len(team), p.get("planned_team_size") or len(team)
        if have < want:
            sig("staffing", CRITICAL if have / want < 0.6 else WARNING,
                f"Starts {p['start']} with {have} of {want} planned people assigned.",
                "Assignments: " + (", ".join(f"{m['name']} ({m['role']})" for m in team) or "none"),
                "Without the full team the plan and the signed dates are not achievable.",
                "Assign people who come free before the start date (see Bench), or agree a later start with the client.")
    else:
        early = [m for m in team if date.fromisoformat(m["until"]) < end - timedelta(days=14)]
        if early:
            sig("staffing", WARNING, f"{len(early)} team member(s) roll off before the project ends.",
                "; ".join(f"{m['name']} ({m['role']}) until {m['until']}" for m in early[:4]),
                "Knowledge loss and a capacity drop late in delivery.", "Plan handovers or extend the assignments.")
        on_leave = [m for m in team if av.leave_weeks(c, m["emp_id"], today, 4)]
        if len(on_leave) >= 2:
            sig("staffing", WARNING, f"{len(on_leave)} team members have leave in the next 4 weeks.",
                ", ".join(m["name"] for m in on_leave), "Capacity dip in the next month.", "Check cover for those weeks.")
    if scope["approved_cr_hours"] > 0.1 * budget:
        sig("scope", WARNING, "Approved change requests exceed 10% of the budget.",
            f"{scope['approved_cr_hours']:,} h approved in change requests vs {budget:,} h budget.",
            "Scope has grown; the plan and team may no longer match.", "Re-baseline the plan with the added scope.")
    if scope["pending_checks"]:
        sig("scope", INFO, f"{scope['pending_checks']} client request(s) awaiting a scope decision.",
            "Scope Guard checks with status 'needs decision'.", "Unpriced work may be absorbed by default.",
            "Decide them in Scope Guard (approve, reject or ask for clarification).")

    level = CRITICAL if any(s["severity"] == CRITICAL for s in signals) else WARNING if any(
        s["severity"] == WARNING for s in signals) else "ok"
    return {
        "code": p["code"], "name": p["name"], "client": p["client"], "status": p["status"], "contract_type": p["contract_type"],
        "currency": cur, "contract_value": p["contract_value"], "start": p["start"], "end": p["end"], "sow_id": p.get("sow_id"),
        "level": level, "signals": signals,
        "metrics": {"elapsed_pct": round(100 * elapsed), "complete_pct": round(100 * pct), "budget_hours": budget,
                    "hours_booked": booked, "earned_hours": round(ev), "cpi": cpi, "spi": spi, "forecast_hours": eac,
                    "overrun_hours": overrun_h, "overrun_cost": overrun_cost, "forecast_end": forecast_end.isoformat(),
                    "team_size": len(team), "planned_team_size": p.get("planned_team_size")},
        "milestones": p["milestones"], "dependencies": p["dependencies"], "scope": scope,
    }


def all_health(c: CompanyData | None = None) -> list[dict]:
    c = c or company()
    rank = {CRITICAL: 0, WARNING: 1, "ok": 2}
    rows = [assess(c, p) for p in projects(c)]
    rows.sort(key=lambda r: (rank[r["level"]], -(r["metrics"]["overrun_cost"] or 0)))
    return rows
