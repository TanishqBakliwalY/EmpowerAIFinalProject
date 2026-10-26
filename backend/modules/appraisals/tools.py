"""Read-only tools for the appraisal agents (least privilege per agent).

The Calibration Analyst and Hike Strategist never see gender. Only the Fairness Auditor gets it,
through aggregate metrics and the members of flagged groups. The Manager Brief Writer gets no tools:
its prompt holds only that manager's own team.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from pydantic_ai import RunContext

from ...core.company import CompanyData
from ..staffing import availability as av
from . import optimizer as opt
from .data import AppraisalData, Person


@dataclass
class AppDeps:
    data: AppraisalData
    company: CompanyData
    pool_pct: float
    strategy: dict | None = None
    allocation: opt.Allocation | None = None
    calibration: dict | None = None
    notes: dict[str, Any] = field(default_factory=dict)


def _evidence_row(p: Person) -> dict:
    """Everything about a person's year except gender and pay (pay is not needed to judge a rating)."""
    return {"emp_id": p.emp_id, "name": p.name, "role": p.role, "level": p.level, "office": p.office,
            "manager": p.manager_emp_id or "(director)", "rating": p.rating, "evidence_score": p.evidence_score,
            "client_feedback": p.client_feedback_score, "utilization_pct": p.utilization_12m_pct,
            "skills_added": p.skills_added, "promotion_recommended": p.promotion_recommended,
            "tenure_years": p.tenure_years, "manager_notes": p.manager_notes}


# =========================================================================== Calibration Analyst


def team_evidence(ctx: RunContext[AppDeps], manager_emp_id: str | None = None) -> list[dict]:
    """Ratings and the evidence behind them (client feedback 1-5, 12-month utilisation, skills added, notes).
    evidence_score is computed in code on the same 1-5 scale as ratings. Omit manager_emp_id for everyone.

    Args:
        manager_emp_id: optional, e.g. "E054", to see one manager's team.
    """
    people = ctx.deps.data.team(manager_emp_id) if manager_emp_id else list(ctx.deps.data.people.values())
    return [_evidence_row(p) for p in sorted(people, key=lambda p: (p.manager_emp_id, p.emp_id))]


def rating_distribution(ctx: RunContext[AppDeps]) -> dict:
    """Rating counts and average (rating - evidence) overall and per manager. Positive = rated above evidence."""
    d = ctx.deps.data
    out = {"overall": {}, "managers": []}
    ps = list(d.people.values())
    out["overall"] = {"counts": {r: sum(1 for p in ps if p.rating == r) for r in range(1, 6)},
                      "avg_rating": round(mean(p.rating for p in ps), 2),
                      "avg_evidence": round(mean(p.evidence_score for p in ps), 2)}
    for m, name in d.managers.items():
        team = d.team(m)
        if team:
            out["managers"].append({"manager_emp_id": m, "manager": name, "team_size": len(team),
                                    "avg_rating": round(mean(p.rating for p in team), 2),
                                    "avg_rating_minus_evidence": round(mean(p.rating - p.evidence_score for p in team), 2)})
    return out


def employee_detail(ctx: RunContext[AppDeps], emp_id: str) -> dict:
    """One person's evidence plus their current and upcoming project assignments (no gender, no pay)."""
    p = ctx.deps.data.people.get(emp_id.strip().upper())
    if not p:
        return {"error": f"No employee {emp_id}."}
    return {**_evidence_row(p), "last_hike_pct": p.last_hike_pct, "months_since_last_hike": p.months_since_last_hike,
            "assignments": av.current_work(ctx.deps.company, p.emp_id)}


# =========================================================================== Hike Strategist


def hike_policy(ctx: RunContext[AppDeps]) -> dict:
    """HR's hike policy: guideline ranges per rating, promotion add-on, caps, compa-ratio rules, strategy bounds."""
    pol = ctx.deps.data.policy
    keys = ("cycle", "pool_pct_of_payroll", "guideline_hike_pct", "promotion_addon_pct", "min_hike_pct", "max_hike_pct",
            "compa_ratio", "retention", "strategy_bounds", "default_strategy")
    return {k: pol[k] for k in keys}


def pool_summary(ctx: RunContext[AppDeps]) -> dict:
    """Payroll, the pool for this cycle, ratings, promotions, retention risk and market position by office."""
    d = ctx.deps.data
    ps = list(d.people.values())
    offices = {}
    for off in sorted({p.office for p in ps}):
        grp = [p for p in ps if p.office == off]
        offices[off] = {"people": len(grp), "avg_compa_ratio": round(mean(p.compa_ratio for p in grp), 3),
                        "below_0_88": sum(1 for p in grp if p.compa_ratio < 0.88)}
    return {"headcount": len(ps), "payroll_inr": d.payroll, "pool_pct": ctx.deps.pool_pct,
            "pool_inr": round(d.payroll * ctx.deps.pool_pct / 100),
            "ratings": {r: sum(1 for p in ps if p.rating == r) for r in range(1, 6)},
            "promotions_recommended": sum(1 for p in ps if p.promotion_recommended),
            "retention_risk": {k: sum(1 for p in ps if p.retention_risk == k) for k in ("high", "medium", "low")},
            "market_position_by_office": offices,
            "calibration_flags": len((ctx.deps.calibration or {}).get("flags", []))}


def simulate_strategy(ctx: RunContext[AppDeps], performance_weight: float, market_weight: float,
                      retention_weight: float, promotion_share_pct: float) -> dict:
    """Run the optimizer with these weights (clamped to policy bounds) and see the outcome. Try 2-3 settings.

    Args:
        performance_weight: weight on the rating guideline.
        market_weight: weight on closing gaps to market band.
        retention_weight: weight on retention-risk bonuses.
        promotion_share_pct: percent of the pool reserved for promotion add-ons.
    """
    d = ctx.deps.data
    s = opt.clamp_strategy(d.policy, {"performance_weight": performance_weight, "market_weight": market_weight,
                                      "retention_weight": retention_weight, "promotion_share_pct": promotion_share_pct})
    a = opt.allocate(d, s, ctx.deps.pool_pct)
    sm = opt.summary(d, a)
    rows = opt.proposal_rows(d, a)
    offices = {}
    for off in sorted({r["office"] for r in rows}):
        grp = [r for r in rows if r["office"] == off]
        offices[off] = round(mean(r["compa_after"] for r in grp), 3)
    high_risk_left = sum(1 for r in rows if r["retention_risk"] == "high" and r["compa_after"] < 0.9)
    return {"strategy_used": s, "avg_hike_by_rating": {b["rating"]: b["avg_hike_pct"] for b in sm["by_rating"]},
            "pool_used_exactly": sm["used_amount"] == sm["pool_amount"], "feasible": sm["feasible"], "note": sm["note"],
            "avg_compa_after_by_office": offices, "high_retention_risk_still_below_0_9": high_risk_left,
            "people_at_cap": sm["people_at_cap"]}


# =========================================================================== Fairness Auditor


def fairness_metrics(ctx: RunContext[AppDeps]) -> dict:
    """Code-computed fairness checks on the CURRENT proposal: gender gaps within each rating, each manager's
    rating-vs-evidence by gender, office market position before/after, tenure gaps, compa-ratio outliers, flags."""
    if not ctx.deps.allocation:
        return {"error": "No proposal yet."}
    return opt.fairness_metrics(ctx.deps.data, ctx.deps.allocation)


def proposal_for(ctx: RunContext[AppDeps], emp_ids: list[str]) -> list[dict]:
    """Proposed hike rows for specific people (members of a flagged group), including gender for the audit."""
    if not ctx.deps.allocation:
        return [{"error": "No proposal yet."}]
    want = {e.strip().upper() for e in emp_ids[:30]}
    return [r for r in opt.proposal_rows(ctx.deps.data, ctx.deps.allocation, include_gender=True) if r["emp_id"] in want]


def calibration_findings(ctx: RunContext[AppDeps]) -> dict:
    """What the Calibration Analyst flagged (ratings vs evidence), to connect rating issues with pay outcomes."""
    return ctx.deps.calibration or {"flags": []}
