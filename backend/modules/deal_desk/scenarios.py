"""What-if scenarios on a finished deal: change an assumption, and code recomputes everything that depends on it.

Effort (+/- %), risk level (contingency), start date, commercial model and discount feed the same calculators the
pipeline uses: estimate -> schedule (real availability from the new start) -> price, margin and policy check -> Phase 1.
Nothing here calls a model, so a scenario is instant and free; "apply" keeps the result and re-runs only the agents whose
inputs changed (the Deal Critic, then the Proposal Writer and the leak guard).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from ...core.company import CompanyData
from . import calculators as calc
from .models import EstimateDraft, PricingDecision, ProjectSpec, SolutionDesign, StaffingDraft


class Scenario(BaseModel):
    effort_pct: float = Field(default=0, ge=-40, le=60, description="Change to build effort, in percent.")
    risk_level: Literal["low", "medium", "high"] | None = Field(default=None, description="Override risk (sets contingency).")
    start_shift_weeks: int = Field(default=0, ge=-8, le=26, description="Move the start date by whole weeks.")
    model: Literal["fixed", "tm"] | None = None
    discount_pct: float | None = Field(default=None, ge=0, le=30)
    name: str = Field(default="", max_length=80)


def _scaled(draft: EstimateDraft, factor: float, risk: str | None) -> EstimateDraft:
    d = draft.model_copy(deep=True)
    for li in d.line_items:
        for rh in li.hours:
            rh.hours = round(rh.hours * factor, 1)
    if risk:
        d.risk_level = risk
    return d


def _calc(c: CompanyData, deal: dict, sc: Scenario) -> dict[str, Any]:
    r = deal["results"]
    spec = ProjectSpec.model_validate(r["spec"])
    design = SolutionDesign.model_validate(r["design"])
    decision = PricingDecision.model_validate(r["pricing_decision"])
    draft = _scaled(EstimateDraft.model_validate(r["estimate_draft"]), 1 + sc.effort_pct / 100, sc.risk_level)
    est = calc.compute_estimate(c, draft, spec.project_type, spec.compliance_flags)

    staff = StaffingDraft.model_validate(r["staffing_draft"])
    start = max(c.as_of, date.fromisoformat(staff.start_date) + timedelta(weeks=sc.start_shift_weeks))
    staff.start_date = start.isoformat()
    sched = calc.plan_schedule(c, est, staff, spec.constraints.deadline_date)

    model = sc.model or decision.recommended_model
    disc = decision.discount_pct if sc.discount_pct is None else sc.discount_pct
    q = calc.price_options(c, est, r["quote"]["currency"], disc, sched.total_weeks, model,
                           spec.constraints.budget_max, spec.constraints.budget_currency)
    p1 = calc.phase1_option(c, draft, design, est, spec.project_type, q.currency, q.discount_pct, sched,
                            spec.constraints.budget_max, spec.constraints.budget_currency, spec.compliance_flags)
    opt = next(o for o in q.options if o.model == model)
    margin = q.margin_pct_fixed if model == "fixed" else q.margin_pct_tm
    return {
        "params": sc.model_dump(),
        "estimate": {"expected_hours": est.expected_hours, "total_hours": est.total_hours, "contingency_pct": est.contingency_pct,
                     "risk_level": est.risk_level},
        "schedule": {"start": sched.start_date, "go_live": sched.end_date, "weeks": sched.total_weeks,
                     "meets_deadline": sched.meets_deadline, "bottleneck": sched.bottleneck_role,
                     "uncovered_roles": sched.uncovered_roles, "team_size": len(sched.team)},
        "price": {"model": model, "currency": q.currency, "price": opt.price, "discount_pct": q.discount_pct,
                  "fixed": q.options[0].price, "tm": q.options[1].price, "margin_pct": margin,
                  "needs_approval": q.needs_approval, "approval_reasons": q.approval_reasons, "budget_fit": q.budget_fit},
        "phase1": {"price_fixed": p1["fixed_price"], "go_live": p1["go_live"], "hours": p1["hours"]} if p1 else None,
        # the full objects, used when the scenario is applied
        "_apply": {"estimate_draft": draft.model_dump(), "estimate": est.model_dump(), "staffing_draft": staff.model_dump(),
                   "schedule": sched.model_dump(), "model": model, "discount_pct": q.discount_pct},
    }


def compute(c: CompanyData, deal: dict, sc: Scenario) -> dict[str, Any]:
    """A scenario, its change against the deal as it stands today, and any drift from the stored result."""
    out = _calc(c, deal, sc)
    base = _calc(c, deal, Scenario())
    out["delta"] = {
        "hours": round(out["estimate"]["total_hours"] - base["estimate"]["total_hours"], 1),
        "weeks": round(out["schedule"]["weeks"] - base["schedule"]["weeks"], 1),
        "go_live_days": (date.fromisoformat(out["schedule"]["go_live"]) - date.fromisoformat(base["schedule"]["go_live"])).days,
        "price": round(out["price"]["price"] - base["price"]["price"]),
        "margin_pts": round(out["price"]["margin_pct"] - base["price"]["margin_pct"], 1),
    }
    stored = deal["results"]["estimate"]["total_hours"]
    drift = round(base["estimate"]["total_hours"] - stored, 1)
    out["baseline"] = {k: base[k] for k in ("estimate", "schedule", "price")}
    out["policy_drift"] = (
        {"hours": drift, "note": f"This deal was estimated under an earlier version of the policy; recomputed today it is "
                                 f"{drift:+,.0f} h. Apply a scenario to refresh it."} if abs(drift) >= 1 else None)
    return out
