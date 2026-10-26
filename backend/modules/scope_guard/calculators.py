"""Deterministic checks and money for the Scope-Creep Guard. The agents classify; this code verifies and counts.

- validate(): every verdict must cite SOW clauses that exist and that can support it (an "in scope" verdict
  needs an S-clause, "out of scope" an X/A/C-clause, "warranty fix" a W-clause). Anything else is
  downgraded to "ambiguous", so a hallucinated or manipulated verdict never becomes a commitment.
- price(): change-request hours x the SOW's own rates, plus PM overhead from company policy.
- ledger(): what was billed vs absorbed per project, from approved analyses.
"""

from __future__ import annotations

from statistics import mean

from .models import Ask, CheckedItem, CREstimate, MatchResult, Pricing, PricedCR

SUPPORT = {  # verdict -> clause types that can justify it
    "in_scope": {"in_scope"},
    "out_of_scope": {"out_of_scope", "assumption", "change_control"},
    "warranty_fix": {"warranty"},
}
OVERHEAD_ROLES = {"pm", "lead"}
MIN_BUILD_HOURS = 2.0


def _round_half(x: float) -> float:
    return round(x * 2) / 2


def validate(sow: dict, asks: list[Ask], result: MatchResult) -> list[CheckedItem]:
    types = {c["id"]: c["type"] for c in sow["clauses"]}
    by_ask = {m.ask_id: m for m in result.matches}
    out: list[CheckedItem] = []
    for a in asks:
        m = by_ask.get(a.id)
        if not m:
            out.append(CheckedItem(ask_id=a.id, quote=a.quote, summary=a.summary, kind=a.kind, verdict="ambiguous",
                                   downgraded=True, downgrade_reason="The Scope Matcher returned no verdict for this ask."))
            continue
        cited = [c.strip().upper() for c in m.clause_ids]
        valid = [c for c in cited if c in types]
        invalid = [c for c in cited if c not in types]
        verdict, reason = m.verdict, None
        if m.verdict in SUPPORT:
            support = [c for c in valid if types[c] in SUPPORT[m.verdict]]
            if not support:
                reason = (f"'{m.verdict}' must cite a {' / '.join(sorted(SUPPORT[m.verdict]))} clause that exists"
                          + (f"; cited {', '.join(cited)}" if cited else "; none cited") + ".")
            elif m.verdict == "in_scope" and any(types[c] == "out_of_scope" for c in valid):
                reason = "Cites both an in-scope and an out-of-scope clause; a person must decide."
        if reason:
            verdict = "ambiguous"
        out.append(CheckedItem(
            ask_id=a.id, quote=a.quote, summary=a.summary, kind=a.kind, verdict=verdict, model_verdict=m.verdict,
            clause_ids=valid, invalid_clause_ids=invalid, reasoning=m.reasoning, confidence=m.confidence,
            question_for_client=m.question_for_client or (
                "Could you confirm whether this is covered by the signed scope or should be quoted separately?"
                if reason else None),
            downgraded=bool(reason), downgrade_reason=reason,
        ))
    return out


def price(sow: dict, items: list[CheckedItem], estimate: CREstimate | None, pm_overhead_pct: float) -> Pricing:
    rates: dict[str, float] = sow["cr_rates"]
    fallback = mean(rates.values()) if rates else 0.0
    est = {e.ask_id: e for e in (estimate.items if estimate else [])}
    priced: list[PricedCR] = []
    warnings: list[str] = []
    for it in items:
        if it.verdict != "out_of_scope":
            continue
        e = est.get(it.ask_id)
        hours: dict[str, float] = {}
        if e:
            for rh in e.hours:
                if rh.role in OVERHEAD_ROLES:
                    warnings.append(f"{it.ask_id}: {rh.role} hours ignored (PM overhead is added by policy).")
                    continue
                hours[rh.role] = hours.get(rh.role, 0) + rh.hours
        else:
            warnings.append(f"{it.ask_id} is out of scope but was not estimated; a person must estimate it.")
        build = sum(hours.values())
        if e and build < MIN_BUILD_HOURS:
            warnings.append(f"{it.ask_id}: raised to the {MIN_BUILD_HOURS:.0f}-hour minimum for a change request.")
            role = next(iter(hours), "be")
            hours[role] = hours.get(role, 0) + (MIN_BUILD_HOURS - build)
            build = MIN_BUILD_HOURS
        pm = _round_half(build * pm_overhead_pct / 100) if build else 0.0
        value = sum(h * rates.get(r, fallback) for r, h in hours.items()) + pm * rates.get("pm", fallback)
        priced.append(PricedCR(
            ask_id=it.ask_id, summary=it.summary, hours_by_role={k: round(v, 1) for k, v in hours.items()},
            build_hours=round(build, 1), pm_hours=pm, total_hours=round(build + pm, 1), price=round(value, -1),
            currency=sow["currency"], basis=e.basis if e else "", assumptions=e.assumptions if e else [], estimated=bool(e),
        ))
    counts = {v: sum(1 for i in items if i.verdict == v) for v in ("in_scope", "out_of_scope", "ambiguous", "warranty_fix")}
    return Pricing(currency=sow["currency"], items=priced, total_hours=round(sum(p.total_hours for p in priced), 1),
                   total_price=round(sum(p.price for p in priced), -1), counts=counts, warnings=warnings)


def ledger(runs: list[dict], sows: dict[str, dict]) -> dict:
    """Per-project totals from analyses a person approved: billed vs absorbed change-request work."""
    projects: dict[str, dict] = {}
    for run in runs:
        sow_id = run.get("input", {}).get("sow_id")
        sow = sows.get(sow_id, {})
        p = projects.setdefault(sow_id, {
            "sow_id": sow_id, "project_name": sow.get("project_name", sow_id), "client": sow.get("client", ""),
            "currency": sow.get("currency", ""), "analyses": 0, "approved": 0, "asks": 0, "in_scope": 0, "warranty_fix": 0,
            "ambiguous": 0, "out_of_scope": 0, "billable_hours": 0.0, "billable_value": 0.0, "absorbed_hours": 0.0,
            "absorbed_value": 0.0,
        })
        p["analyses"] += 1
        dec = run.get("decision") or {}
        if dec.get("action") != "approve":
            continue
        p["approved"] += 1
        res = run.get("results") or {}
        for it in res.get("items", []):
            p["asks"] += 1
            p[it["verdict"]] = p.get(it["verdict"], 0) + 1
        absorbed = set(dec.get("absorb_ask_ids") or [])
        for cr in (res.get("pricing") or {}).get("items", []):
            if cr["ask_id"] in absorbed:
                p["absorbed_hours"] += cr["total_hours"]
                p["absorbed_value"] += cr["price"]
            else:
                p["billable_hours"] += cr["total_hours"]
                p["billable_value"] += cr["price"]
    rows = sorted(projects.values(), key=lambda r: -r["billable_value"])
    for r in rows:
        for k in ("billable_hours", "billable_value", "absorbed_hours", "absorbed_value"):
            r[k] = round(r[k], 1)
        r["margin_protected"] = r["billable_value"]
    return {"projects": rows,
            "totals": {"analyses": sum(r["analyses"] for r in rows), "approved": sum(r["approved"] for r in rows),
                       "out_of_scope_asks": sum(r["out_of_scope"] for r in rows),
                       "billable_hours": round(sum(r["billable_hours"] for r in rows), 1),
                       "absorbed_hours": round(sum(r["absorbed_hours"] for r in rows), 1)}}
