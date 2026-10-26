"""The arithmetic of a hike cycle. Agents pick strategy weights and propose adjustments; this code
turns them into rupee amounts that use the budget pool exactly and respect HR's caps, and computes
the fairness metrics the auditor reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from .data import AppraisalData, Person

# ---------------------------------------------------------------------------- strategy


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def clamp_strategy(policy: dict, s: dict) -> dict:
    """Keep agent-chosen weights inside HR's allowed bounds."""
    b = policy["strategy_bounds"]
    out = {k: round(clamp(float(s.get(k, policy["default_strategy"][k])), *b[k]), 3) for k in b}
    return out


# ---------------------------------------------------------------------------- per-person raw score


def bounds_for(policy: dict, p: Person) -> tuple[float, float]:
    """Allowed hike range for one person: the rating guideline with some slack, inside global caps."""
    lo, hi = policy["guideline_hike_pct"][str(p.rating)]
    slack = policy["guideline_slack_pp"]
    if p.rating <= 1:
        return 0.0, 0.0
    lo_b = max(policy["min_hike_pct"], lo - slack)
    hi_b = min(policy["max_hike_pct"], hi + slack + (policy["promotion_addon_pct"][1] if p.promotion_recommended else 0))
    return lo_b, hi_b


def raw_hike(policy: dict, strat: dict, p: Person) -> float:
    lo, hi = policy["guideline_hike_pct"][str(p.rating)]
    perf = (lo + hi) / 2
    cr = policy["compa_ratio"]
    market = clamp((cr["target"] - p.compa_ratio) * 100 * cr["market_gap_factor"], *cr["market_component_bounds_pct"])
    ret = {"high": policy["retention"]["high_risk_bonus_pct"], "medium": policy["retention"]["medium_risk_bonus_pct"]}.get(p.retention_risk, 0.0)
    return max(0.0, strat["performance_weight"] * perf + strat["market_weight"] * market + strat["retention_weight"] * ret)


# ---------------------------------------------------------------------------- allocation


@dataclass
class Allocation:
    hikes_pct: dict[str, float]
    amounts: dict[str, int]
    promotion_addon_pct: dict[str, float]
    pool_amount: int
    used_amount: int
    feasible: bool
    note: str = ""
    locked: set[str] = field(default_factory=set)


def _fill(weights: dict[str, float], ctc: dict[str, int], lo: dict[str, float], hi: dict[str, float], target: float) -> dict[str, float]:
    """Find hike % per person proportional to `weights`, clipped to [lo, hi], whose total cost is `target` INR.
    Bisection on a common scale factor (monotone because every clip is monotone)."""
    def cost(scale: float) -> float:
        return sum(ctc[e] * clamp(weights[e] * scale, lo[e], hi[e]) / 100 for e in weights)

    low, high = 0.0, 1.0
    while cost(high) < target and high < 1e6:
        high *= 2
    for _ in range(200):
        mid = (low + high) / 2
        if cost(mid) < target:
            low = mid
        else:
            high = mid
    return {e: clamp(weights[e] * high, lo[e], hi[e]) for e in weights}


def allocate(d: AppraisalData, strat: dict, pool_pct: float | None = None,
             overrides_pp: dict[str, float] | None = None) -> Allocation:
    """Hike per person that spends the pool exactly (to the rupee) within each person's bounds.

    overrides_pp: fairness adjustments in percentage points; those people are locked at
    (their fair-share hike + adjustment) and the rest of the pool is rebalanced around them.
    """
    pol = d.policy
    strat = clamp_strategy(pol, strat)
    pool_pct = float(pool_pct if pool_pct is not None else pol["pool_pct_of_payroll"])
    people = d.people
    ctc = {e: p.ctc for e, p in people.items()}
    pool = int(round(sum(ctc.values()) * pool_pct / 100))

    # 1) promotion add-ons from a reserved share of the pool
    promoted = [e for e, p in people.items() if p.promotion_recommended and p.rating >= 3]
    promo_budget = pool * strat["promotion_share_pct"] / 100 if promoted else 0.0
    a_lo, a_hi = pol["promotion_addon_pct"]
    promo_pct: dict[str, float] = {}
    if promoted:
        per = promo_budget / sum(ctc[e] for e in promoted) * 100
        for e in promoted:
            promo_pct[e] = clamp(per, a_lo, a_hi)
    promo_cost = sum(ctc[e] * promo_pct[e] / 100 for e in promo_pct)

    # 2) merit/market/retention hikes for everyone from the rest of the pool
    bounds = {e: bounds_for(pol, p) for e, p in people.items()}
    lo = {e: bounds[e][0] for e in people}
    hi = {e: max(bounds[e][0], bounds[e][1] - promo_pct.get(e, 0.0)) for e in people}
    weights = {e: raw_hike(pol, strat, p) for e, p in people.items()}
    remaining = pool - promo_cost
    base = _fill(weights, ctc, lo, hi, remaining)

    locked: set[str] = set()
    if overrides_pp:
        adj_lo, adj_hi = pol["max_adjustment_pp"]
        fixed: dict[str, float] = {}
        for e, pp in overrides_pp.items():
            if e not in people:
                continue
            fixed[e] = clamp(base[e] + clamp(pp, adj_lo, adj_hi), lo[e], hi[e])
            locked.add(e)
        free = [e for e in people if e not in locked]
        rest = remaining - sum(ctc[e] * fixed[e] / 100 for e in fixed)
        refill = _fill({e: weights[e] for e in free}, ctc, lo, hi, rest) if free else {}
        base = {**refill, **fixed}

    hikes = {e: base[e] + promo_pct.get(e, 0.0) for e in people}
    amounts = {e: int(round(ctc[e] * hikes[e] / 100)) for e in people}

    # 3) settle rounding to the rupee on whoever has the most headroom
    diff = pool - sum(amounts.values())
    min_total = sum(int(round(ctc[e] * (lo[e] + promo_pct.get(e, 0.0)) / 100)) for e in people)
    max_total = sum(int(round(ctc[e] * (hi[e] + promo_pct.get(e, 0.0)) / 100)) for e in people)
    feasible = min_total <= pool <= max_total
    if feasible and diff:
        order = sorted((e for e in people if e not in locked), reverse=True,
                       key=lambda e: (ctc[e] * (hi[e] + promo_pct.get(e, 0)) / 100 - amounts[e]) if diff > 0 else amounts[e])
        for e in order:
            room = int(ctc[e] * (hi[e] + promo_pct.get(e, 0)) / 100) - amounts[e] if diff > 0 else amounts[e] - int(ctc[e] * lo[e] / 100)
            step = min(abs(diff), max(0, room))
            if step:
                amounts[e] += step if diff > 0 else -step
                diff += -step if diff > 0 else step
            if not diff:
                break
    hikes = {e: round(100 * amounts[e] / ctc[e], 2) if ctc[e] else 0.0 for e in people}
    note = "" if feasible else ("The pool is larger than the caps allow everyone to receive." if pool > max_total
                                else "The pool is smaller than the minimum guideline hikes require.")
    return Allocation(hikes_pct=hikes, amounts=amounts, promotion_addon_pct={e: round(v, 2) for e, v in promo_pct.items()},
                      pool_amount=pool, used_amount=sum(amounts.values()), feasible=feasible, note=note, locked=locked)


def proposal_rows(d: AppraisalData, a: Allocation, include_gender: bool = False) -> list[dict]:
    rows = []
    for e, p in sorted(d.people.items(), key=lambda kv: kv[1].name):
        new_ctc = p.ctc + a.amounts[e]
        row = {"emp_id": e, "name": p.name, "title": p.title, "role": p.role, "level": p.level, "office": p.office,
               "manager_emp_id": p.manager_emp_id, "rating": p.rating, "evidence_score": p.evidence_score,
               "promotion_recommended": p.promotion_recommended, "retention_risk": p.retention_risk,
               "ctc": p.ctc, "hike_pct": a.hikes_pct[e], "increase": a.amounts[e], "new_ctc": new_ctc,
               "promotion_addon_pct": a.promotion_addon_pct.get(e, 0.0),
               "compa_before": p.compa_ratio, "compa_after": round(new_ctc / p.band_p50, 3) if p.band_p50 else None,
               "adjusted": e in a.locked}
        if include_gender:
            row["gender"] = p.gender
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------- fairness metrics


def fairness_metrics(d: AppraisalData, a: Allocation) -> dict:
    """Aggregate checks the Fairness Auditor reads. Gender is used only here, in aggregate."""
    pol = d.policy["fairness"]
    n_min = pol["min_group_size"]
    rows = proposal_rows(d, a, include_gender=True)
    flags: list[dict] = []

    # 1) gender gap in proposed hike within the same rating
    by_rating = []
    for r in sorted({x["rating"] for x in rows}):
        f = [x for x in rows if x["rating"] == r and x["gender"] == "F"]
        m = [x for x in rows if x["rating"] == r and x["gender"] == "M"]
        if len(f) >= n_min and len(m) >= n_min:
            gap = round(mean(x["hike_pct"] for x in m) - mean(x["hike_pct"] for x in f), 2)
            by_rating.append({"rating": r, "women": len(f), "men": len(m), "avg_hike_women": round(mean(x["hike_pct"] for x in f), 2),
                              "avg_hike_men": round(mean(x["hike_pct"] for x in m), 2), "gap_pp_men_minus_women": gap})
            if abs(gap) > pol["gender_gap_pp_within_rating"]:
                flags.append({"kind": "gender_gap", "group": f"rating {r}", "value": gap,
                              "members": [x["emp_id"] for x in (f if gap > 0 else m)]})

    # 2) manager patterns: rating minus evidence, by gender, per manager
    managers = []
    for mgr in sorted({x["manager_emp_id"] for x in rows if x["manager_emp_id"]}):
        team = [x for x in rows if x["manager_emp_id"] == mgr]
        f = [x for x in team if x["gender"] == "F"]
        m = [x for x in team if x["gender"] == "M"]
        entry = {"manager_emp_id": mgr, "manager": d.managers.get(mgr, mgr), "team_size": len(team),
                 "avg_rating_minus_evidence": round(mean(x["rating"] - x["evidence_score"] for x in team), 2)}
        if len(f) >= n_min and len(m) >= n_min:
            fr = round(mean(x["rating"] - x["evidence_score"] for x in f), 2)
            mr = round(mean(x["rating"] - x["evidence_score"] for x in m), 2)
            entry.update(women=len(f), men=len(m), women_rating_minus_evidence=fr, men_rating_minus_evidence=mr,
                         gap=round(mr - fr, 2))
            if mr - fr > pol["manager_rating_gap_vs_evidence"]:
                flags.append({"kind": "manager_pattern", "group": f"women on {mgr}'s team", "value": round(mr - fr, 2),
                              "members": [x["emp_id"] for x in f]})
        managers.append(entry)

    # 3) office: compa-ratio before and after the cycle (a structural gap is flagged even if this cycle closes it)
    offices = []
    all_before = mean(x["compa_before"] for x in rows)
    all_after = mean(x["compa_after"] for x in rows if x["compa_after"])
    for off in sorted({x["office"] for x in rows}):
        grp = [x for x in rows if x["office"] == off]
        avg_b = round(mean(x["compa_before"] for x in grp), 3)
        avg_a = round(mean(x["compa_after"] for x in grp if x["compa_after"]), 3)
        gap_b, gap_a = round(all_before - avg_b, 3), round(all_after - avg_a, 3)
        offices.append({"office": off, "people": len(grp), "avg_compa_before": avg_b, "avg_compa_after": avg_a,
                        "gap_vs_company_before": gap_b, "gap_vs_company_after": gap_a,
                        "avg_hike_pct": round(mean(x["hike_pct"] for x in grp), 2)})
        if max(gap_b, gap_a) > pol["office_compa_gap"]:
            flags.append({"kind": "office_gap", "group": f"{off} office", "value": gap_a, "before": gap_b,
                          "resolved_by_this_cycle": gap_a <= pol["office_compa_gap"],
                          "members": [x["emp_id"] for x in grp]})

    # 4) tenure buckets within rating
    tenure = []
    for r in sorted({x["rating"] for x in rows}):
        new = [x for x in rows if x["rating"] == r and d.people[x["emp_id"]].tenure_years < 2]
        old = [x for x in rows if x["rating"] == r and d.people[x["emp_id"]].tenure_years >= 2]
        if len(new) >= n_min and len(old) >= n_min:
            gap = round(mean(x["hike_pct"] for x in old) - mean(x["hike_pct"] for x in new), 2)
            tenure.append({"rating": r, "under_2y": len(new), "over_2y": len(old), "gap_pp_long_minus_short": gap})
            if abs(gap) > pol["tenure_gap_pp_within_rating"]:
                flags.append({"kind": "tenure_gap", "group": f"rating {r}", "value": gap, "members": []})

    # 5) compa-ratio outliers after the cycle
    outliers = [{"emp_id": x["emp_id"], "name": x["name"], "office": x["office"], "rating": x["rating"],
                 "compa_after": x["compa_after"]} for x in rows if x["compa_after"] and
                (x["compa_after"] < pol["compa_outlier_low"] or x["compa_after"] > pol["compa_outlier_high"])]
    if outliers:
        flags.append({"kind": "compa_outlier", "group": f"{len(outliers)} people outside {pol['compa_outlier_low']}-{pol['compa_outlier_high']}",
                      "value": len(outliers), "members": [o["emp_id"] for o in outliers]})
    return {"gender_gap_within_rating": by_rating, "managers": managers, "offices": offices, "tenure": tenure,
            "compa_outliers": outliers, "flags": flags, "thresholds": pol}


def summary(d: AppraisalData, a: Allocation) -> dict:
    rows = proposal_rows(d, a)
    by_rating = []
    for r in sorted({x["rating"] for x in rows}, reverse=True):
        grp = [x for x in rows if x["rating"] == r]
        by_rating.append({"rating": r, "people": len(grp), "avg_hike_pct": round(mean(x["hike_pct"] for x in grp), 2),
                          "min_hike_pct": min(x["hike_pct"] for x in grp), "max_hike_pct": max(x["hike_pct"] for x in grp)})
    return {"pool_amount": a.pool_amount, "used_amount": a.used_amount, "feasible": a.feasible, "note": a.note,
            "payroll": sum(x["ctc"] for x in rows), "avg_hike_pct": round(100 * a.used_amount / max(1, sum(x["ctc"] for x in rows)), 2),
            "by_rating": by_rating, "promotions": len(a.promotion_addon_pct),
            "people_at_cap": sum(1 for x in rows if x["hike_pct"] >= bounds_for(d.policy, d.people[x["emp_id"]])[1] - 0.01 and x["rating"] > 1),
            "adjusted": len(a.locked)}
