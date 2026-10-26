"""The referee: code that prices every offer in a rehearsal and enforces Empower's pricing policy.

The negotiator agent only chooses a commercial model (fixed / T&M), a scope (full / Phase 1) and a discount. This module
turns that into a price with the same calculator the Deal Desk uses, caps the discount at the policy maximum, checks the
margin floor, and flags anything that needs a Director. No agent ever types a price the client sees.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from ...core.company import CompanyData
from ..deal_desk import calculators as calc
from ..deal_desk.models import Estimate, ProjectSpec, Quote, Schedule

DIRECTOR_DISCOUNT_PCT = 5.0  # above this a Director must approve (same rule as the Deal Desk)
DISCOVERY_TEAM = {"ba": 1.0, "uiux": 0.5, "lead": 0.5, "pm": 0.25}  # share of a week per role during a paid discovery


def deal_facts(deal: dict) -> dict[str, Any]:
    """What the rehearsal needs from a finished deal."""
    r = deal["results"]
    return {
        "spec": ProjectSpec.model_validate(r["spec"]),
        "estimate": Estimate.model_validate(r["estimate"]),
        "schedule": Schedule.model_validate(r["schedule"]),
        "quote": Quote.model_validate(r["quote"]),
        "phase1": r.get("phase1"),
    }


def price_offer(c: CompanyData, facts: dict[str, Any], model: str, scope: str, discount_pct: float) -> dict[str, Any]:
    """Price one offer. Returns what the client sees (price, scope, dates) and what only staff see (margin, flags)."""
    pol = c.policy
    q0: Quote = facts["quote"]
    cur = q0.currency
    notes: list[str] = []
    asked = float(discount_pct or 0)
    disc = max(0.0, min(asked, float(pol["max_discount_pct"])))
    if disc < asked:
        notes.append(f"Discount capped at the {pol['max_discount_pct']}% policy maximum (asked {asked:g}%).")
    p1 = facts.get("phase1")
    if scope == "phase1" and not p1:
        notes.append("No Phase 1 option exists for this deal (every package is a must-have); priced the full scope.")
        scope = "full"

    if scope == "discovery":
        # A paid discovery: requirements, UX prototype and architecture over the policy's discovery weeks, ending in
        # a fixed quote for the build. Priced from the rate card like everything else.
        weeks = float(pol["discovery_weeks"])
        hours_by_role = {r: weeks * pol["hours_per_week"] * share for r, share in DISCOVERY_TEAM.items()}
        rates = c.rate_card["billing_rates"][cur]
        list_price = sum(h * rates[r] for r, h in hours_by_role.items())
        price = round(list_price * (1 + (pol["fixed_price_risk_premium_pct"] / 100 if model == "fixed" else 0)) * (1 - disc / 100), -2)
        cost = calc.internal_cost(c, hours_by_role, cur)
        margin = calc.r1(100 * (price - cost) / price) if price else 0.0
        start = date.fromisoformat(facts["schedule"].start_date)
        hours, go_live = calc.r1(sum(hours_by_role.values())), (start + timedelta(weeks=weeks)).isoformat()
    elif scope == "full":
        est: Estimate = facts["estimate"]
        sch: Schedule = facts["schedule"]
        q = calc.price_options(c, est, cur, disc, sch.total_weeks, model)
        price = next(o.price for o in q.options if o.model == model)
        margin = q.margin_pct_fixed if model == "fixed" else q.margin_pct_tm
        hours, go_live, weeks = est.total_hours, sch.end_date, sch.total_weeks
    else:
        # Phase 1 prices were stored at the deal's own discount; undo it, apply the new one. Cost scales with hours,
        # so the margin follows from the stored Phase 1 margin.
        d0 = q0.discount_pct
        fixed_list = p1["fixed_price"] / (1 - d0 / 100) if d0 < 100 else p1["fixed_price"]
        tm_list = p1["tm_price"] / (1 - d0 / 100) if d0 < 100 else p1["tm_price"]
        cost = p1["fixed_price"] * (1 - p1["margin_pct_fixed"] / 100)
        price = round((fixed_list if model == "fixed" else tm_list) * (1 - disc / 100), -2)
        margin = calc.r1(100 * (price - cost) / price) if price else 0.0
        hours, go_live, weeks = p1["hours"], p1["go_live"], p1["weeks"]

    floor = float(pol["margin_floor_pct"])
    below_floor = margin < floor
    if below_floor:
        notes.append(f"Margin {margin}% is below the {floor:.0f}% floor: the offer is not allowed without a Director.")
    needs_director = disc > DIRECTOR_DISCOUNT_PCT or below_floor
    if disc > DIRECTOR_DISCOUNT_PCT:
        notes.append(f"A {disc:g}% discount needs a Director's approval (over {DIRECTOR_DISCOUNT_PCT:g}%).")

    spec: ProjectSpec = facts["spec"]
    budget = spec.constraints.budget_max
    if budget and spec.constraints.budget_currency and spec.constraints.budget_currency.upper() != cur:
        budget = calc.convert(c, budget, spec.constraints.budget_currency.upper(), cur)
    gap = calc.r1(100 * (price - budget) / budget) if budget else None
    return {
        "model": model, "scope": scope, "discount_pct": disc, "currency": cur, "price": price, "hours": hours,
        "weeks": weeks, "go_live": go_live, "margin_pct": margin, "margin_floor_pct": floor,
        "needs_director": needs_director, "below_floor": below_floor, "budget_gap_pct": gap, "notes": notes,
    }


def offer_card(offer: dict[str, Any], facts: dict[str, Any]) -> str:
    """The one line the client sees with each offer (numbers from code only)."""
    model = "fixed price" if offer["model"] == "fixed" else "time & materials (estimate)"
    disc = f", including a {offer['discount_pct']:g}% discount" if offer["discount_pct"] else ""
    if offer["scope"] == "discovery":
        return (f"Offer: {offer['currency']} {offer['price']:,.0f}, {model}, paid discovery ({offer['weeks']:g} weeks: requirements, "
                f"UX prototype, architecture, and a fixed quote for the build){disc}; results by {offer['go_live']}.")
    scope = "full scope" if offer["scope"] == "full" else "Phase 1 (" + ", ".join((facts.get("phase1") or {}).get("packages", [])[:4]) + ")"
    return f"Offer: {offer['currency']} {offer['price']:,.0f}, {model}, {scope}{disc}; go-live {offer['go_live']}."


_MONEY = re.compile(r"(?:USD|EUR|GBP|US\$|\$|€|£)\s?\d[\d,]*(?:\.\d+)?\s?k?|\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP)\b|\d+(?:\.\d+)?\s?%", re.I)


def scrub_numbers(text: str, allowed: set[str]) -> tuple[str, int]:
    """Remove money amounts and percentages the negotiator typed itself: only the referee's offer card may state them."""
    removed = 0

    def repl(m: re.Match) -> str:
        nonlocal removed
        digits = re.sub(r"[^\d.]", "", m.group(0))
        if any(digits and digits == re.sub(r"[^\d.]", "", a) for a in allowed):
            return m.group(0)
        removed += 1
        return "[see the offer]"

    return _MONEY.sub(repl, text), removed
