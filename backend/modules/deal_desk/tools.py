"""Tools the Deal Desk agents can call. All read-only over company data; none send anything anywhere.

Each agent gets only the tools its job needs (least privilege): the Proposal Writer has none, so it
cannot look up costs or salaries even if a document tells it to.
"""

from __future__ import annotations

import re
from datetime import date
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext

from ...core.company import CompanyData
from ..staffing.tools import check_capability, find_people, person_schedule, role_capacity, skills_inventory  # noqa: F401 (re-exported)
from . import calculators as calc
from .models import Estimate, ProjectSpec, SolutionDesign, StaffingDraft, TeamMember


@dataclass
class DealDeps:
    """What tools can see during one deal run."""

    company: CompanyData
    currency: str
    spec: ProjectSpec | None = None
    design: SolutionDesign | None = None
    estimate: Estimate | None = None
    total_weeks: float | None = None
    notes: dict[str, Any] = field(default_factory=dict)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#.]+", text.lower()) if len(w) > 2}


# =========================================================================== shared


def list_module_catalog(ctx: RunContext[DealDeps]) -> list[dict]:
    """List Empower's standard work modules (key, name, typical keywords). Map features and work packages to these keys."""
    return [{"key": k, "name": v["name"], "keywords": v["tags"][:6]} for k, v in ctx.deps.company.module_catalog.items()]


def find_similar_projects(ctx: RunContext[DealDeps], keywords: list[str], project_type: str | None = None,
                          industry: str | None = None, top_k: int = 5) -> list[dict]:
    """Find Empower's most similar past projects.

    Args:
        keywords: features, technologies or domain words, e.g. ["booking", "react native", "hipaa"].
        project_type: optional: web, mobile, bi, iot, ecommerce, ai, migration, bigdata, crm.
        industry: optional, e.g. "Healthcare".
        top_k: how many to return (max 8).
    """
    c = ctx.deps.company
    want = set()
    for k in keywords:
        want |= _words(k)
    scored = []
    for p in c.projects.values():
        text = " ".join([p["name"], p["stack"], p["industry"], p["project_type"], " ".join(p["modules"])])
        for m in p["modules"]:
            text += " " + " ".join(c.module_catalog.get(m, {}).get("tags", []))
        score = len(want & _words(text))
        if project_type and p["project_type"] == project_type:
            score += 3
        if industry and industry.lower() in p["industry"].lower():
            score += 2
        if score:
            scored.append((score, p))
    scored.sort(key=lambda t: -t[0])
    cx = {(r["project_id"], r["module"]): r["complexity"] for r in c.project_modules}
    return [
        {"project_id": p["project_id"], "name": p["name"], "client": p["client"], "country": p["country"],
         "industry": p["industry"], "type": p["project_type"], "stack": p["stack"],
         "modules_with_complexity": [f'{m} ({cx.get((p["project_id"], m), "medium")})' for m in p["modules"]],
         "estimated_hours": p["est_hours"], "actual_hours": p["actual_hours"],
         "overrun_pct": round(100 * (p["actual_hours"] / p["est_hours"] - 1), 1), "contract": p["contract_type"],
         "price": f'{p["currency"]} {p["price"]:,}', "planned_end": p["planned_end"], "actual_end": p["actual_end"],
         "lesson": p["outcome_notes"], "match_score": s}
        for s, p in scored[: max(1, min(top_k, 8))]
    ]


# =========================================================================== analyst


def lookup_client(ctx: RunContext[DealDeps], client_name: str) -> dict:
    """Check whether a client already worked with Empower, and what the relationship notes say."""
    c = ctx.deps.company
    q = client_name.lower().strip()
    for cl in c.clients:
        name = cl["client"].lower()
        if q and (q in name or name in q or (len(q) > 4 and q.split()[0] in name)):
            past = [{"project_id": p["project_id"], "name": p["name"], "year": p["start_date"][:4]}
                    for p in c.projects.values() if p["client"] == cl["client"]]
            return {"found": True, **cl, "past_projects": past}
    return {"found": False, "note": "No record of this client. Treat as a new client (credit check, deposit)."}


# =========================================================================== estimator


def module_benchmarks(ctx: RunContext[DealDeps], module_keys: list[str]) -> list[dict]:
    """Empower's real history for these modules: median ESTIMATED and median ACTUAL hours by role,
    normalised to medium complexity, plus how often they overran. Base estimates on ACTUALS.

    Args:
        module_keys: keys from the module catalog, e.g. ["booking", "payments", "mobile_app"].
    """
    return [calc.module_benchmark(ctx.deps.company, k) for k in module_keys[:15] if k in ctx.deps.company.module_catalog]


def project_breakdown(ctx: RunContext[DealDeps], project_id: str) -> dict:
    """Module-by-role estimated vs actual hours for one past project (e.g. 'P107')."""
    c = ctx.deps.company
    p = c.projects.get(project_id.strip().upper())
    if not p:
        return {"error": f"No project {project_id}. Use find_similar_projects to get valid ids."}
    rows = [{k: r[k] for k in ("module", "complexity", "role", "est_hours", "actual_hours")}
            for r in c.project_modules if r["project_id"] == p["project_id"]]
    return {"project_id": p["project_id"], "name": p["name"], "type": p["project_type"], "stack": p["stack"],
            "estimated_hours": p["est_hours"], "actual_hours": p["actual_hours"], "lesson": p["outcome_notes"], "rows": rows}


def estimation_track_record(ctx: RunContext[DealDeps], project_type: str) -> dict:
    """How far Empower's past estimates for a project type undershot reality (mean actual/estimate)."""
    return calc.type_accuracy(ctx.deps.company, project_type)


# =========================================================================== staffing


def required_hours(ctx: RunContext[DealDeps]) -> dict:
    """The final estimated hours by role for this deal (including PM, tech lead and contingency)."""
    est = ctx.deps.estimate
    if not est:
        return {"error": "No estimate yet."}
    return {"hours_by_role": est.hours_by_role, "total_hours": est.total_hours,
            "roles": {k: ctx.deps.company.roles.get(k, k) for k in est.hours_by_role},
            "today": ctx.deps.company.as_of.isoformat(),
            "client_go_live_deadline": ctx.deps.spec.constraints.deadline_date if ctx.deps.spec else None,
            "client_requested_start": ctx.deps.spec.constraints.requested_start if ctx.deps.spec else None}


def suggest_team(ctx: RunContext[DealDeps], start_date: str, skills_by_role: dict[str, list[str]] | None = None) -> dict:
    """Get the calculator's baseline team: for each role it adds the best free people (matching skills first)
    until the hours fit before the client's deadline (or a ~20-week build if there is none). Start from this,
    then swap people for better skills or seniority and check with simulate_schedule.

    Args:
        start_date: ISO date the team would start.
        skills_by_role: optional preferred skills per role, e.g. {"mobile": ["React Native"], "be": [".NET Core"]}.
    """
    d = ctx.deps
    if not d.estimate:
        return {"error": "No estimate yet."}
    try:
        start = max(date.fromisoformat(start_date), d.company.as_of)
    except ValueError:
        start = d.company.as_of
    deadline = d.spec.constraints.deadline_date if d.spec else None
    draft = calc.suggest_team(d.company, d.estimate, start, deadline, skills_by_role)
    sched = calc.plan_schedule(d.company, d.estimate, draft, deadline)
    return {"team": [m.model_dump() for m in draft.team], "start": sched.start_date, "go_live": sched.end_date,
            "total_weeks": sched.total_weeks, "weeks_needed_by_role": sched.role_weeks, "bottleneck_role": sched.bottleneck_role,
            "uncovered_roles": sched.uncovered_roles, "meets_client_deadline": sched.meets_deadline, "warnings": sched.warnings}


def simulate_schedule(ctx: RunContext[DealDeps], team: list[TeamMember], start_date: str) -> dict:
    """Test a candidate team before you commit to it. Returns the timeline Empower's calculator would compute:
    total weeks, go-live date, weeks needed per role, the bottleneck role, availability conflicts and whether
    the client's deadline is met. Call it, adjust the team, and call it again (2-4 tries is normal).

    Args:
        team: the people you are considering, each with emp_id, role, allocation_pct and a short reason.
        start_date: ISO date the team would start.
    """
    d = ctx.deps
    if not d.estimate:
        return {"error": "No estimate yet."}
    sched = calc.plan_schedule(d.company, d.estimate, StaffingDraft(team=team, start_date=start_date),
                               d.spec.constraints.deadline_date if d.spec else None)
    return {"start": sched.start_date, "go_live": sched.end_date, "total_weeks": sched.total_weeks,
            "build_weeks": sched.build_weeks, "weeks_needed_by_role": sched.role_weeks, "bottleneck_role": sched.bottleneck_role,
            "uncovered_roles": sched.uncovered_roles, "meets_client_deadline": sched.meets_deadline,
            "client_deadline": d.spec.constraints.deadline_date if d.spec else None, "warnings": sched.warnings}


# =========================================================================== pricing


def get_rate_card(ctx: RunContext[DealDeps]) -> dict:
    """Billing rates per role in the deal currency, and the pricing policy (margin floor, max discount, ...)."""
    c = ctx.deps.company
    pol = c.policy
    return {"currency": ctx.deps.currency, "rates_per_hour": c.rate_card["billing_rates"][ctx.deps.currency],
            "margin_floor_pct": pol["margin_floor_pct"], "target_margin_pct": pol["target_margin_pct"],
            "max_discount_pct": pol["max_discount_pct"], "fixed_price_risk_premium_pct": pol["fixed_price_risk_premium_pct"]}


def quote_calculator(ctx: RunContext[DealDeps], discount_pct: float = 0.0, recommended_model: str = "fixed") -> dict:
    """Compute fixed-price and T&M prices, internal margin and approval flags for a discount.
    Try a few discounts if the client's budget is tight; the calculator enforces policy.

    Args:
        discount_pct: discount on list price (policy max applies).
        recommended_model: 'fixed' or 'tm'.
    """
    d = ctx.deps
    if not d.estimate:
        return {"error": "No estimate yet."}
    budget = d.spec.constraints if d.spec else None
    q = calc.price_options(d.company, d.estimate, d.currency, discount_pct, d.total_weeks, recommended_model,
                           budget.budget_max if budget else None, budget.budget_currency if budget else None)
    return {"options": [{"model": o.model, "price": o.price, "blended_rate": o.blended_rate,
                         "monthly_estimate": o.monthly_estimate} for o in q.options],
            "margin_pct_fixed": q.margin_pct_fixed, "margin_pct_tm": q.margin_pct_tm,
            "margin_floor_pct": q.margin_floor_pct, "needs_approval": q.needs_approval,
            "approval_reasons": q.approval_reasons, "budget_fit": q.budget_fit, "hours": d.estimate.total_hours}


def pricing_history(ctx: RunContext[DealDeps], project_type: str | None = None, country: str | None = None) -> dict:
    """Past deals of a similar type: effective price per hour Empower achieved, and deals we lost and why."""
    c = ctx.deps.company
    usd_per = {cur: c.rate_card["inr_per_unit"].get(cur) for cur in ("USD", "EUR", "GBP")}
    won = []
    for p in c.projects.values():
        if project_type and p["project_type"] != project_type:
            continue
        rate = p["price"] / p["est_hours"] if p["est_hours"] else None
        won.append({"project_id": p["project_id"], "name": p["name"], "country": p["country"], "contract": p["contract_type"],
                    "price": f'{p["currency"]} {p["price"]:,}', "price_per_estimated_hour": f'{p["currency"]} {rate:.1f}' if rate else None})
    lost = [d for d in c.lost_deals
            if (not project_type or d["project_type"] == project_type) or (country and d["country"] == country)]
    return {"won_projects": won[:8], "lost_deals": lost[:6], "fx_inr_per_unit": usd_per}


# =========================================================================== critic


def compliance_checklist(ctx: RunContext[DealDeps], country: str, industry: str, keywords: list[str]) -> list[dict]:
    """Compliance rules triggered by the client's country, industry and feature keywords."""
    c = ctx.deps.company
    kw = " ".join(keywords).lower() + " " + industry.lower()
    hits = []
    for rule in c.compliance_rules:
        by_country = country.upper() in rule.get("countries", [])
        by_industry = any(i in industry.lower() for i in rule.get("industries", []))
        by_kw = any(re.search(rf"\b{re.escape(k)}\b", kw) for k in rule.get("keywords", []))
        needs_country = "countries" in rule
        needs_other = "industries" in rule or "keywords" in rule
        if (not needs_country or by_country) and (not needs_other or by_industry or by_kw):
            hits.append({"rule": rule["name"], "requires": rule["requires"], "effort_hint": rule["effort_hint"]})
    return hits


def deal_checks(ctx: RunContext[DealDeps]) -> dict:
    """Deterministic checks computed in code for this deal: estimate warnings, schedule/staffing warnings,
    margin and approval flags, budget and deadline fit. Always read this before judging the deal."""
    return ctx.deps.notes.get("checks", {"error": "Checks not available yet."})
