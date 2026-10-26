"""Builds the two documents a deal produces: the client proposal and the internal deal memo.

Prose comes from the Proposal Writer; every number and table comes from the calculators, so
figures in the documents always match the computed estimate, schedule and quote.
"""

from __future__ import annotations

from datetime import date, timedelta

from ...core.company import CompanyData
from .models import CriticReview, Estimate, PricingDecision, ProjectSpec, ProposalDraft, Quote, Schedule, SolutionDesign


def money(cur: str, x: float) -> str:
    return f"{cur} {x:,.0f}"


def bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- None"


def proposal_markdown(c: CompanyData, spec: ProjectSpec, design: SolutionDesign, draft: ProposalDraft,
                      est: Estimate, sched: Schedule, quote: Quote, phase1: dict | None = None) -> str:
    start = date.fromisoformat(sched.start_date)
    d1 = start + timedelta(days=round(sched.discovery_weeks * 7))
    d2 = d1 + timedelta(days=round(sched.build_weeks * 7))
    end = date.fromisoformat(sched.end_date)

    # Team by role (client sees roles and allocation, not internal ids)
    by_role: dict[str, list[int]] = {}
    for m in sched.team:
        by_role.setdefault(m.role, []).append(m.allocation_pct)
    team_rows = "\n".join(
        f"| {c.roles.get(r, r)} | {len(a)} | {', '.join(f'{x}%' for x in a)} |" for r, a in by_role.items()
    )
    for r in sched.uncovered_roles:
        team_rows += f"\n| {c.roles.get(r, r)} | 1 | to be confirmed |"

    stack_rows = "\n".join(f"| {s.layer} | {s.technology} | {s.reason} |" for s in design.recommended_stack)
    fixed = next(o for o in quote.options if o.model == "fixed")
    tm = next(o for o in quote.options if o.model == "tm")
    ms_rows = "\n".join(f"| {m.milestone} | {m.pct:.0f}% | {money(quote.currency, m.amount)} |" for m in fixed.milestones)
    rec = "fixed price" if quote.recommended_model == "fixed" else "time & materials"
    pkg_rows = "\n".join(f"| {w.name} | {w.scope_notes} |" for w in design.work_packages)
    phase_block = ""
    if phase1:
        p1_live = date.fromisoformat(phase1["go_live"])
        phase_block = (
            "**Phased option: launch the essentials first**\n\n"
            "| | Phase 1 (launch) | Phase 2 (after launch) |\n|---|---|---|\n"
            f"| Scope | {', '.join(phase1['packages'])} | {', '.join(phase1['later_packages'])} |\n"
            f"| Fixed price | **{money(quote.currency, phase1['fixed_price'])}** | quoted after Phase 1, using real velocity |\n"
            f"| Go-live | {p1_live:%d %B %Y} | to be agreed |\n\n"
        )

    risk_block = ("## Risks and how we manage them\n\n" + bullets(draft.risks) + "\n\n") if draft.risks else ""
    return f"""# {draft.title}

**Prepared for:** {spec.client_name} · **Prepared by:** Empower Solutions · **Date:** {c.as_of.isoformat()}

## Executive summary

{draft.executive_summary}

## Our understanding of your needs

{draft.understanding}

## Proposed approach

{draft.approach}

### Technology

| Layer | Technology | Why |
|---|---|---|
{stack_rows}

### Work packages

| Package | What it covers |
|---|---|
{pkg_rows}

## Scope

**Included**

{bullets(draft.scope_in)}

**Not included (can be quoted separately)**

{bullets(draft.scope_out)}

## Timeline

| Phase | Duration | Dates |
|---|---|---|
| Discovery & design | {sched.discovery_weeks:.0f} weeks | {start:%d %b %Y} to {d1:%d %b %Y} |
| Build & test (iterative, demo every 2 weeks) | {sched.build_weeks:.1f} weeks | {d1:%d %b %Y} to {d2:%d %b %Y} |
| UAT, launch & stabilisation | {sched.stabilization_weeks:.0f} weeks | {d2:%d %b %Y} to {end:%d %b %Y} |

**Planned go-live:** {end:%d %B %Y} ({sched.total_weeks:.1f} weeks from a start on {start:%d %B %Y}).

{risk_block}## Team

| Role | People | Allocation |
|---|---|---|
{team_rows}

A dedicated project manager is your single point of contact, with daily overlap hours in your time zone.

## Commercials

We recommend **{rec}** for this project. Effort is estimated at about **{est.total_hours:,.0f} hours**.

| Option | Price | How it works |
|---|---|---|
| Fixed price | **{money(quote.currency, fixed.price)}** | {fixed.terms} |
| Time & materials | ~{money(quote.currency, tm.price)} forecast (about {money(quote.currency, tm.monthly_estimate or 0)} / month) | {tm.terms} |

**Fixed-price payment milestones**

| Milestone | Share | Amount |
|---|---|---|
{ms_rows}

{phase_block}Prices exclude taxes and third-party fees (cloud hosting, app-store accounts, SMS, licences). This proposal is valid for 30 days.

## Assumptions

{bullets(draft.assumptions)}

## Questions for you

{bullets(draft.questions_for_client)}

## Why Empower

{draft.why_empower}

## Next steps

{bullets(draft.next_steps)}
"""


def memo_markdown(c: CompanyData, spec: ProjectSpec, design: SolutionDesign, est: Estimate, sched: Schedule,
                  quote: Quote, decision: PricingDecision, review: CriticReview, screen_findings: list[dict],
                  phase1: dict | None = None) -> str:
    fixed = next(o for o in quote.options if o.model == "fixed")
    tm = next(o for o in quote.options if o.model == "tm")
    team = "\n".join(
        f"| {m.name} ({m.emp_id}) | {m.title} | {m.office} | {m.allocation_pct}% | {m.free_pct}% | {m.conflict or 'OK'} |"
        for m in sched.team
    ) or "| (no one assigned) | | | | | |"
    issues = "\n".join(
        f"| {i.severity.upper()} | {i.area} | {i.finding} | {i.recommendation} |" for i in review.issues
    ) or "| - | - | No issues | - |"
    hours = "\n".join(f"| {c.roles.get(r, r)} | {h:,.0f} |" for r, h in sorted(est.hours_by_role.items(), key=lambda kv: -kv[1]))
    screen = bullets([f"[{f['severity']}] {f['message']} {('“' + f['snippet'] + '”') if f.get('snippet') else ''}"
                      for f in screen_findings]) if screen_findings else "- Nothing suspicious found."
    approvals = bullets(quote.approval_reasons) if quote.approval_reasons else "- None: within policy."
    phase1_text = (f"{money(quote.currency, phase1['fixed_price'])} fixed for {', '.join(phase1['packages'])} "
                   f"({phase1['hours']:,.0f} h, go-live {phase1['go_live']}, margin {phase1['margin_pct_fixed']:.1f}%). "
                   f"{phase1['budget_fit'] or ''}") if phase1 else "n/a (every work package is a must-have)"
    return f"""# Internal deal memo: {spec.project_title} ({spec.client_name})

**Critic verdict:** {review.verdict.upper()} · **Feasibility:** {design.feasibility.replace('_', ' ')} · **Risk:** {est.risk_level}

{review.go_no_go}

## Numbers

| Item | Value |
|---|---|
| Expected effort | {est.expected_hours:,.0f} h (likely range {est.low_hours:,.0f} to {est.high_hours:,.0f} h) |
| Priced and staffed effort | {est.total_hours:,.0f} h (expected + contingency) |
| Contingency | {est.contingency_pct:.0f}% ({est.contingency_hours:,.0f} h) |
| Past estimates for {spec.project_type} work undershot actuals by | {est.historical_underestimate_pct or 0:.0f}% (this estimate is built on actuals) |
| Fixed price | {money(quote.currency, fixed.price)} (margin {quote.margin_pct_fixed:.1f}%) |
| T&M forecast | {money(quote.currency, tm.price)} (margin {quote.margin_pct_tm:.1f}%) |
| Internal delivery cost | {money(quote.currency, quote.internal_cost)} |
| Margin floor / target | {quote.margin_floor_pct:.0f}% / {quote.target_margin_pct:.0f}% |
| Discount | {quote.discount_pct:.1f}% |
| Budget fit | {quote.budget_fit or 'Client gave no budget.'} |
| Phase-1 option | {phase1_text} |
| Timeline | {sched.start_date} to {sched.end_date} ({sched.total_weeks:.1f} weeks); deadline met: {('yes' if sched.meets_deadline else 'NO') if sched.meets_deadline is not None else 'no deadline given'} |

**Approvals needed**

{approvals}

## Hours by role

| Role | Hours |
|---|---|
{hours}

## Proposed team

| Person | Title | Office | Allocation | Free in window | Check |
|---|---|---|---|---|---|
{team}

Gaps: {', '.join(sched.gaps + [c.roles.get(r, r) for r in sched.uncovered_roles]) or 'none'}

## Critic findings

| Severity | Area | Finding | Recommendation |
|---|---|---|---|
{issues}

## Pricing rationale

{bullets(decision.rationale)}

**Negotiation notes**

{bullets(decision.negotiation_notes)}

## Calculator warnings

{bullets(est.warnings + sched.warnings)}

## Safety screen of the client document

{screen}
"""
