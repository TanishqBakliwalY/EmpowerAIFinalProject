"""Deterministic math for the Deal Desk. The agents choose; this code counts.

Hours totals, overheads, contingency, schedule, prices and margins are computed here from the
agents' structured choices and Empower's policy file, so a model can never invent a number that
reaches the client, and a prompt injection cannot "set the price".
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import mean, median, pstdev

from ...core.company import CompanyData
from ..staffing import availability as av
from .models import (
    Estimate,
    EstimateDraft,
    SolutionDesign,
    EstimateLine,
    Milestone,
    PriceOption,
    Quote,
    Schedule,
    StaffedMember,
    StaffingDraft,
    TeamMember,
)

DEV_ROLES = ("fe", "be", "mobile", "data", "ml", "devops")
OVERHEAD_ROLES = ("pm", "lead")


def r1(x: float) -> float:
    return round(x, 1)


# =========================================================================== history lookups


def module_benchmark(c: CompanyData, module_key: str) -> dict:
    """Median past hours per role for one module, normalised to MEDIUM complexity."""
    cat = c.module_catalog.get(module_key)
    rows = [r for r in c.project_modules if r["module"] == module_key]
    by_role: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        mult = c.complexity_multipliers.get(r["complexity"], 1.0)
        d = by_role.setdefault(r["role"], {"est": [], "act": []})
        d["est"].append(r["est_hours"] / mult)
        d["act"].append(r["actual_hours"] / mult)
    projects = sorted({r["project_id"] for r in rows})
    role_stats = {
        role: {"median_estimated": r1(median(v["est"])), "median_actual": r1(median(v["act"]))}
        for role, v in by_role.items()
    }
    est_total = sum(s["median_estimated"] for s in role_stats.values())
    act_total = sum(s["median_actual"] for s in role_stats.values())
    return {
        "module_key": module_key,
        "name": cat["name"] if cat else module_key,
        "past_projects": projects,
        "observations": len(projects),
        "medium_complexity_hours_by_role": role_stats,
        "median_actual_total_medium": r1(act_total),
        "historical_overrun_pct": r1(100 * (act_total / est_total - 1)) if est_total else None,
        "catalog_base_hours_medium": cat["base_hours_medium"] if cat else None,
        "complexity_multipliers": c.complexity_multipliers,
    }


def type_accuracy(c: CompanyData, project_type: str) -> dict:
    """How far Empower's past estimates for this project type were from actuals."""
    ps = [p for p in c.projects.values() if p["project_type"] == project_type] or list(c.projects.values())
    ratios = [p["actual_hours"] / p["est_hours"] for p in ps if p["est_hours"]]
    return {
        "project_type": project_type,
        "projects": len(ps),
        "mean_actual_over_estimate": round(mean(ratios), 3),
        "underestimate_pct": r1(100 * (mean(ratios) - 1)),
        "spread_std": round(pstdev(ratios), 3) if len(ratios) > 1 else 0.08,
        "examples": [
            {"project_id": p["project_id"], "name": p["name"], "est_hours": p["est_hours"], "actual_hours": p["actual_hours"],
             "note": p["outcome_notes"]}
            for p in ps[:5]
        ],
    }


def expected_line_hours(c: CompanyData, module_key: str, complexity: str) -> float | None:
    b = module_benchmark(c, module_key)
    if not b["observations"]:
        base = (c.module_catalog.get(module_key) or {}).get("base_hours_medium")
        return r1(sum(base.values()) * c.complexity_multipliers.get(complexity, 1.0)) if base else None
    build = sum(v["median_actual"] for k, v in b["medium_complexity_hours_by_role"].items() if k not in OVERHEAD_ROLES)
    return r1(build * c.complexity_multipliers.get(complexity, 1.0))


# =========================================================================== estimate


REGULATED = ("hipaa", "pci", "gdpr")


def compute_estimate(c: CompanyData, draft: EstimateDraft, project_type: str,
                     compliance_flags: list[str] | None = None) -> Estimate:
    pol = c.policy
    warnings: list[str] = []
    lines: list[EstimateLine] = []
    build: dict[str, float] = {}
    for item in draft.line_items:
        hours: dict[str, float] = {}
        for rh in item.hours:
            if rh.role in OVERHEAD_ROLES:
                warnings.append(f"'{item.work_package}': {rh.role} hours ignored (PM and tech-lead overhead is added by policy).")
                continue
            hours[rh.role] = hours.get(rh.role, 0) + rh.hours
        total = r1(sum(hours.values()))
        expected = expected_line_hours(c, item.module_key, item.complexity) if item.module_key != "custom" else None
        dev = r1(100 * (total - expected) / expected) if expected else None
        if dev is not None and abs(dev) > 40:
            warnings.append(
                f"'{item.work_package}' is {dev:+.0f}% vs Empower's history for {item.module_key} at {item.complexity} complexity "
                f"({total:.0f} h vs ~{expected:.0f} h)."
            )
        unknown = [p for p in item.reference_projects if p not in c.projects]
        if unknown:
            warnings.append(f"'{item.work_package}' cites unknown project ids {unknown}; ignored.")
        lines.append(EstimateLine(
            work_package=item.work_package, module_key=item.module_key, complexity=item.complexity,
            hours_by_role={k: r1(v) for k, v in hours.items()}, total_hours=total, basis=item.basis,
            reference_projects=[p for p in item.reference_projects if p in c.projects],
            benchmark_hours=expected, deviation_pct=dev,
        ))
        for k, v in hours.items():
            build[k] = build.get(k, 0) + v

    build_hours = sum(build.values())
    dev_hours = sum(build.get(r, 0) for r in DEV_ROLES)
    qa_needed = dev_hours * pol["min_qa_ratio_pct"] / 100
    qa_topup = max(0.0, qa_needed - build.get("qa", 0))
    if qa_topup > 0:
        warnings.append(f"QA raised by {qa_topup:.0f} h to meet the {pol['min_qa_ratio_pct']}% minimum QA policy.")
    # Regulated data (HIPAA / PCI-DSS / GDPR) needs extra verification: audit-log, access-control and data-handling tests.
    regulated = [f for f in (compliance_flags or []) if any(r in f.lower() for r in REGULATED)]
    uplift_pct = float(pol.get("regulated_qa_uplift_pct", 0))
    if regulated and uplift_pct:
        extra = (build.get("qa", 0) + qa_topup) * uplift_pct / 100
        qa_topup += extra
        warnings.append(f"QA raised by {extra:.0f} h ({uplift_pct:.0f}%) for regulated data: {', '.join(regulated)}.")
    base = build_hours + qa_topup
    pm = base * pol["pm_overhead_pct"] / 100
    lead = base * pol["lead_overhead_pct"] / 100
    subtotal = base + pm + lead
    cont_pct = float(pol["contingency_pct"][draft.risk_level])
    cont = subtotal * cont_pct / 100
    total = subtotal + cont

    by_role = dict(build)
    by_role["qa"] = by_role.get("qa", 0) + qa_topup
    by_role["pm"] = pm
    by_role["lead"] = lead
    scale = total / subtotal if subtotal else 1
    by_role = {k: r1(v * scale) for k, v in by_role.items() if v > 0}

    acc = type_accuracy(c, project_type)
    spread = max(0.08, acc["spread_std"])
    return Estimate(
        lines=lines,
        build_hours_by_role={k: r1(v) for k, v in build.items()},
        hours_by_role=by_role,
        build_hours=r1(build_hours),
        qa_topup_hours=r1(qa_topup),
        pm_hours=r1(pm * scale),
        lead_hours=r1(lead * scale),
        contingency_pct=cont_pct,
        contingency_hours=r1(cont),
        expected_hours=r1(subtotal),
        total_hours=r1(total),
        low_hours=r1(subtotal * (1 - spread)),
        high_hours=r1(total * (1 + spread)),
        risk_level=draft.risk_level,
        historical_underestimate_pct=acc["underestimate_pct"],
        warnings=warnings,
    )


# =========================================================================== schedule


def plan_schedule(c: CompanyData, est: Estimate, draft: StaffingDraft, deadline: str | None = None) -> Schedule:
    pol = c.policy
    warnings: list[str] = []
    try:
        start = date.fromisoformat(draft.start_date)
    except ValueError:
        start = c.as_of
        warnings.append(f"Start date '{draft.start_date}' unreadable; using {start.isoformat()}.")
    if start < c.as_of:
        warnings.append(f"Start date moved from {start.isoformat()} to today ({c.as_of.isoformat()}).")
        start = c.as_of

    est_weeks = max(4, math.ceil(est.total_hours / (pol["hours_per_week"] * 3)))  # rough window to check availability in
    team: list[StaffedMember] = []
    capacity: dict[str, float] = {}
    seen: set[str] = set()
    for m in draft.team:
        e = c.employees.get(m.emp_id)
        if not e:
            warnings.append(f"{m.emp_id} is not an Empower employee; removed from the team.")
            continue
        if m.emp_id in seen:
            warnings.append(f"{e.name} listed twice; kept once.")
            continue
        seen.add(m.emp_id)
        window = min(est_weeks, 26)
        free = av.free_pct(c, e.emp_id, start, window)
        effective = min(m.allocation_pct, free)
        conflict = None
        if effective < m.allocation_pct:
            conflict = f"only {free}% free in the window (asked {m.allocation_pct}%)"
            warnings.append(f"{e.name}: {conflict}.")
        off = av.leave_weeks(c, e.emp_id, start, window)
        if off:
            effective *= 1 - off / window  # planned leave reduces capacity, it doesn't block the person
            warnings.append(f"{e.name} has planned leave in {off} of the first {window} weeks; capacity reduced accordingly.")
        if e.role != m.role:
            warnings.append(f"{e.name} is a {e.title} but was planned as '{m.role}'.")
        team.append(StaffedMember(emp_id=e.emp_id, name=e.name, title=e.title, role=m.role, office=e.office,
                                  allocation_pct=m.allocation_pct, free_pct=free, conflict=conflict))
        capacity[m.role] = capacity.get(m.role, 0) + effective / 100 * pol["hours_per_week"] * pol["productive_utilization"]

    role_weeks: dict[str, float] = {}
    uncovered: list[str] = []
    hiring_lag = 3.0
    for role, hours in est.hours_by_role.items():
        if role in OVERHEAD_ROLES or hours <= 0:
            continue
        cap = capacity.get(role, 0)
        if cap <= 0:
            uncovered.append(role)
            cap = pol["hours_per_week"] * pol["productive_utilization"]  # assume one new hire/contractor at 100%
            role_weeks[role] = r1(hiring_lag + hours / cap)
        else:
            role_weeks[role] = r1(hours / cap)
    for role in OVERHEAD_ROLES:
        if est.hours_by_role.get(role, 0) > 0 and capacity.get(role, 0) <= 0:
            uncovered.append(role)
    if uncovered:
        warnings.append("No one assigned for: " + ", ".join(c.roles.get(r, r) for r in uncovered)
                        + f". Timeline assumes a hire/contractor joins after ~{hiring_lag:.0f} weeks.")

    build_weeks = max(role_weeks.values()) if role_weeks else 0.0
    bottleneck = max(role_weeks, key=role_weeks.get) if role_weeks else None
    disc, stab = float(pol["discovery_weeks"]), float(pol["stabilization_weeks"])
    total_weeks = r1(disc + build_weeks + stab)
    end = start + timedelta(days=math.ceil(total_weeks * 7))
    meets = None
    if deadline:
        try:
            meets = end <= date.fromisoformat(deadline)
            if not meets:
                warnings.append(f"Planned go-live {end.isoformat()} is after the client's deadline {deadline}.")
        except ValueError:
            pass
    return Schedule(
        team=team, start_date=start.isoformat(), end_date=end.isoformat(), total_weeks=total_weeks,
        discovery_weeks=disc, build_weeks=r1(build_weeks), stabilization_weeks=stab, bottleneck_role=bottleneck,
        role_weeks=role_weeks, uncovered_roles=uncovered, gaps=draft.gaps, warnings=warnings, meets_deadline=meets,
    )


# =========================================================================== pricing


def convert(c: CompanyData, amount: float, from_cur: str, to_cur: str) -> float | None:
    rates = c.rate_card["inr_per_unit"]
    if from_cur == to_cur:
        return amount
    if from_cur not in rates or to_cur not in rates:
        return None
    return amount * rates[from_cur] / rates[to_cur]


def internal_cost(c: CompanyData, hours_by_role: dict[str, float], currency: str) -> float:
    inr = sum(h * c.role_cost_inr_per_hour.get(role, 0) for role, h in hours_by_role.items())
    return inr / c.rate_card["inr_per_unit"][currency]


def price_options(c: CompanyData, est: Estimate, currency: str, discount_pct: float, total_weeks: float | None,
                  recommended_model: str = "fixed", budget_max: float | None = None,
                  budget_currency: str | None = None) -> Quote:
    pol = c.policy
    rates = c.rate_card["billing_rates"][currency]
    approval: list[str] = []
    if discount_pct > pol["max_discount_pct"]:
        approval.append(f"Requested discount {discount_pct:.1f}% capped at the {pol['max_discount_pct']}% policy maximum.")
        discount_pct = float(pol["max_discount_pct"])
    elif discount_pct > 5:
        approval.append(f"Discount of {discount_pct:.1f}% needs a director's approval (over 5%).")

    list_tm = sum(h * rates[role] for role, h in est.hours_by_role.items())
    tm_price = round(list_tm * (1 - discount_pct / 100), -2)
    fixed_price = round(list_tm * (1 + pol["fixed_price_risk_premium_pct"] / 100) * (1 - discount_pct / 100), -2)
    hours = est.total_hours
    cost = internal_cost(c, est.hours_by_role, currency)
    m_fixed = r1(100 * (fixed_price - cost) / fixed_price) if fixed_price else 0.0
    m_tm = r1(100 * (tm_price - cost) / tm_price) if tm_price else 0.0
    floor = float(pol["margin_floor_pct"])
    if m_fixed < floor or m_tm < floor:
        approval.append(f"Margin below the {floor:.0f}% floor (fixed {m_fixed}%, T&M {m_tm}%).")

    months = max(1.0, (total_weeks or hours / 120) / 4.33)
    milestones = [Milestone(milestone=m["milestone"], pct=m["pct"], amount=round(fixed_price * m["pct"] / 100, -1))
                  for m in pol["payment_milestones_fixed"]]
    options = [
        PriceOption(model="fixed", label="Fixed price", currency=currency, price=fixed_price,
                    blended_rate=round(fixed_price / hours, 2) if hours else 0, hours=hours, milestones=milestones,
                    terms=f"Fixed scope as described; change requests quoted separately; {pol['warranty_days']}-day warranty."),
        PriceOption(model="tm", label="Time & materials", currency=currency, price=tm_price,
                    blended_rate=round(tm_price / hours, 2) if hours else 0, hours=hours,
                    monthly_estimate=round(tm_price / months, -2),
                    terms=f"{pol['tm_billing']}; estimate shown is a forecast, not a cap."),
    ]

    fit = None
    if budget_max:
        b = convert(c, budget_max, (budget_currency or currency).upper(), currency) if budget_currency else budget_max
        if b:
            gap = 100 * (fixed_price - b) / b
            fit = (f"Fixed price is {gap:.0f}% above the client's stated maximum ({currency} {b:,.0f})." if gap > 0
                   else f"Fixed price is within the client's stated budget ({currency} {b:,.0f}).")
    return Quote(
        currency=currency, recommended_model=recommended_model, discount_pct=discount_pct, options=options,
        rate_card={k: float(v) for k, v in rates.items()}, internal_cost=round(cost, 2),
        margin_pct_fixed=m_fixed, margin_pct_tm=m_tm, margin_floor_pct=floor,
        target_margin_pct=float(pol["target_margin_pct"]), needs_approval=bool(approval), approval_reasons=approval,
        budget_fit=fit,
    )


# =========================================================================== phased option


def phase1_option(c: CompanyData, draft: EstimateDraft, design: SolutionDesign, full: Estimate, project_type: str,
                  currency: str, discount_pct: float, full_sched: Schedule, budget_max: float | None,
                  budget_currency: str | None, compliance_flags: list[str] | None = None) -> dict | None:
    """Price a first launch with only the must-have work packages, for clients whose budget or deadline
    cannot take the full scope. Returns None when every package is a must-have (nothing to phase)."""
    must = {w.name.strip().lower() for w in design.work_packages if w.priority == "must"}
    later = [w.name for w in design.work_packages if w.priority != "must"]
    lines = [li for li in draft.line_items if li.work_package.strip().lower() in must]
    if not lines or not later or len(lines) == len(draft.line_items):
        return None
    est1 = compute_estimate(c, EstimateDraft(line_items=lines, risk_level=draft.risk_level, risk_reasons=draft.risk_reasons),
                            project_type, compliance_flags)
    share = est1.total_hours / full.total_hours if full.total_hours else 1
    weeks = r1(full_sched.discovery_weeks + full_sched.build_weeks * share + full_sched.stabilization_weeks)
    go_live = date.fromisoformat(full_sched.start_date) + timedelta(days=math.ceil(weeks * 7))
    q = price_options(c, est1, currency, discount_pct, weeks, "fixed", budget_max, budget_currency)
    return {
        "packages": [li.work_package for li in lines],
        "later_packages": later,
        "hours": est1.total_hours,
        "weeks": weeks,
        "go_live": go_live.isoformat(),
        "fixed_price": q.options[0].price,
        "tm_price": q.options[1].price,
        "margin_pct_fixed": q.margin_pct_fixed,
        "budget_fit": q.budget_fit,
        "share_of_full_scope_pct": r1(100 * share),
    }


# =========================================================================== team suggestion


def suggest_team(c: CompanyData, est: Estimate, start: date, deadline: str | None = None,
                 skills_by_role: dict[str, list[str]] | None = None, default_build_weeks: float = 20.0) -> StaffingDraft:
    """Greedy baseline team: for each role, add the best free people (skill match, then free %, then seniority)
    until the role's hours fit in the target build window. The Staffing Planner starts from this and adjusts."""
    pol = c.policy
    weekly = pol["hours_per_week"] * pol["productive_utilization"]
    build_target = default_build_weeks
    if deadline:
        try:
            weeks_left = (date.fromisoformat(deadline) - start).days / 7
            build_target = max(6.0, weeks_left - pol["discovery_weeks"] - pol["stabilization_weeks"])
        except ValueError:
            pass
    window = max(4, min(26, math.ceil(build_target + pol["discovery_weeks"])))
    level_rank = {"Lead": 3, "Senior": 2, "Mid": 1, "Junior": 0}
    team: list[TeamMember] = []
    for role, hours in sorted(est.hours_by_role.items(), key=lambda kv: -kv[1]):
        if hours <= 0:
            continue
        wanted = (skills_by_role or {}).get(role, [])
        cands = []
        for e in c.employees.values():
            if e.role != role:
                continue
            free = av.free_pct(c, e.emp_id, start, window)
            if free < 25:
                continue
            cands.append((len(av.matched_skills(e, wanted)), free, level_rank.get(e.level, 0), e))
        cands.sort(key=lambda t: (-t[0], -t[1], -t[2]))
        if role in OVERHEAD_ROLES:  # one PM / tech lead, part-time, sized to the project
            if cands:
                need_pct = min(100, max(25, round(100 * hours / (build_target * weekly) / 25) * 25))
                e = cands[0][3]
                team.append(TeamMember(emp_id=e.emp_id, role=role, allocation_pct=min(need_pct, cands[0][1]),
                                       reason="calculator baseline: most suitable free person"))
            continue
        need_fte = hours / (build_target * weekly)
        got = 0.0
        for _, free, _, e in cands:
            if got >= need_fte - 0.05:
                break
            alloc = min(free, 100, max(25, math.ceil((need_fte - got) * 4) * 25))
            team.append(TeamMember(emp_id=e.emp_id, role=role, allocation_pct=alloc,
                                   reason="calculator baseline: matching skills and free capacity"))
            got += alloc / 100
    return StaffingDraft(team=team, start_date=start.isoformat(), gaps=[], notes=["Greedy baseline from the calculator."])
