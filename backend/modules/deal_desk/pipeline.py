"""The Deal Desk run: who hands work to whom.

    screen (code) -> Analyst -> Architect -> Estimator -> [Staffing || Pricing] -> checks (code)
        -> Critic --(revise, once)--> Estimator / Staffing / Pricing -> Critic
        -> Writer -> leak guard (code) -> waiting for a human decision

The order is fixed in code because each step needs the previous one's output; Staffing and Pricing
are independent given the estimate, so they run in parallel. Agents decide; calculators count;
a person approves.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date
from typing import Any

from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded

from ...core import guardrails, store
from ...core.company import CompanyData, company
from ...core.config import MAX_REVISION_ROUNDS, MODEL_NAME
from ...core.runner import RunRecorder
from . import calculators as calc
from . import render
from .agents import SPECS, build_agent
from .models import (
    CriticReview,
    Estimate,
    EstimateDraft,
    PricingDecision,
    ProjectSpec,
    ProposalDraft,
    Quote,
    Schedule,
    SolutionDesign,
    StaffingDraft,
)
from .tools import DealDeps

MODULE_KEY = "deal_desk"
ACTIVE: dict[str, dict[str, Any]] = {}  # runs in progress, served from memory while they run
_TASKS: set[asyncio.Task] = set()  # keep references so running tasks are not garbage-collected

STEP_ORDER = [
    ("screen", "Safety screen", "code", "Strips hidden text and flags instructions aimed at the AI."),
    *[(k, s.label, "agent", s.job) for k, s in SPECS.items() if k in ("analyst", "architect", "estimator", "staffing", "pricing")],
    ("orchestrator", "Orchestrator", "code",
     "Reconciles the agents' findings (capacity, deadline, budget) and routes conflicts back to the agent that owns them."),
    ("critic", SPECS["critic"].label, "agent", SPECS["critic"].job),
    ("writer", SPECS["writer"].label, "agent", SPECS["writer"].job),
    ("guard", "Leak guard", "code", "Blocks internal costs, salaries, margins or prompt text in the client document."),
]


def new_state(run_id: str, inp: dict[str, Any], client_ip: str) -> dict[str, Any]:
    return {
        "id": run_id,
        "module": MODULE_KEY,
        "status": "queued",
        "created_at": store.now_iso(),
        "title": inp.get("client_name") or "New deal",
        "model": MODEL_NAME,
        "input": inp,
        "client_ip": client_ip,
        "steps": {k: {"key": k, "label": label, "kind": kind, "job": job, "status": "pending"}
                  for k, label, kind, job in STEP_ORDER},
        "trace": [],
        "results": {},
        "screen": {"findings": []},
        "revisions": 0,
        "orchestrator_revisions": 0,
        "decision": None,
        "error": None,
    }


def dump(model: Any) -> Any:
    return model.model_dump(mode="json") if hasattr(model, "model_dump") else model


def compact(model: Any, drop: tuple[str, ...] = ()) -> str:
    """Short JSON for handing one agent's output to the next (fewer tokens than pretty-printing)."""
    d = dump(model)
    if isinstance(d, dict):
        d = {k: v for k, v in d.items() if k not in drop}
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def build_checks(c: CompanyData, spec: ProjectSpec, design: SolutionDesign, est: Any, sched: Any, quote: Any) -> dict:
    return {
        "estimate": {"expected_hours": est.expected_hours, "total_hours_with_contingency": est.total_hours,
                     "range": [est.low_hours, est.high_hours], "risk_level": est.risk_level,
                     "contingency_pct": est.contingency_pct, "qa_topup_hours": est.qa_topup_hours,
                     "historical_underestimate_pct_for_type": est.historical_underestimate_pct, "warnings": est.warnings,
                     "lines": [{"package": l.work_package, "hours": l.total_hours, "benchmark": l.benchmark_hours,
                                "deviation_pct": l.deviation_pct} for l in est.lines]},
        "schedule": {"start": sched.start_date, "end": sched.end_date, "weeks": sched.total_weeks,
                     "bottleneck_role": sched.bottleneck_role, "uncovered_roles": sched.uncovered_roles,
                     "client_deadline": spec.constraints.deadline_date, "meets_deadline": sched.meets_deadline,
                     "team": [{"emp_id": m.emp_id, "role": m.role, "allocation_pct": m.allocation_pct,
                               "free_pct": m.free_pct, "conflict": m.conflict} for m in sched.team],
                     "warnings": sched.warnings},
        "pricing": {"currency": quote.currency, "recommended_model": quote.recommended_model,
                    "fixed_price": quote.options[0].price, "tm_forecast": quote.options[1].price,
                    "margin_pct_fixed": quote.margin_pct_fixed, "margin_pct_tm": quote.margin_pct_tm,
                    "margin_floor_pct": quote.margin_floor_pct, "discount_pct": quote.discount_pct,
                    "needs_approval": quote.needs_approval, "approval_reasons": quote.approval_reasons,
                    "client_budget": spec.constraints.budget_text, "budget_fit": quote.budget_fit},
        "feasibility": design.feasibility,
        "capability_gaps": design.capability_gaps,
        "client": {"country": spec.client_country, "industry": spec.industry, "existing_client": spec.existing_client},
    }


class DealRun:
    def __init__(self, run_id: str, state: dict[str, Any], company_data: CompanyData | None = None,
                 effort: dict[str, Any] | None = None, save: bool = True) -> None:
        """`company_data`, `effort` and `save` exist for experiments (scripts/backtest.py); the app uses the defaults."""
        self.c = company_data or company()
        self.state = state
        self.run_id = run_id
        self.save = save
        self.rec = RunRecorder(run_id, MODULE_KEY, state, self.persist)
        inp = state["input"]
        self.deps = DealDeps(company=self.c, currency=inp["currency"])
        self.agents = {k: build_agent(self.c, k, (effort or {}).get(k)) for k in SPECS}

    def persist(self) -> None:
        if not self.save:
            return
        store.save_run(self.run_id, MODULE_KEY, self.state["status"], self.state["title"], self.state,
                       self.state.get("client_ip", ""))

    async def agent(self, key: str, prompt: str, detail: str = "") -> Any:
        self.rec.start_step(key, detail)
        out = await self.rec.run_agent(key, self.agents[key], prompt, self.deps)
        return out

    # ------------------------------------------------------------------ steps

    def screen(self) -> str:
        self.rec.start_step("screen")
        res = guardrails.screen_untrusted(self.state["input"]["brief"])
        clean, removed = guardrails.redact_ai_directed_lines(res.clean_text)
        findings = [f.to_dict() for f in res.findings]
        self.state["screen"] = {"findings": findings, "injection_suspected": res.injection_suspected, "removed_lines": removed}
        for f in res.findings:
            self.rec.event("screen", "guardrail", f"[{f.severity}] {f.message}", {"snippet": f.snippet})
            if f.severity == "high":
                store.add_safety_event("prompt_injection_flagged", "high", f.message, self.run_id, f.to_dict())
        summary = (f"Suspected injection: {len(findings)} finding(s), {removed} line(s) aimed at the AI removed; the rest is treated as data only."
                   if res.injection_suspected else f"{len(findings)} minor finding(s)." if findings else "Clean: nothing hidden or suspicious.")
        self.rec.finish_step("screen", summary)
        return clean

    async def run_analyst(self, clean_text: str) -> ProjectSpec:
        inp = self.state["input"]
        prompt = (
            "Analyse this client request.\n\n"
            f"{guardrails.spotlight(clean_text)}\n\n"
            "Details entered by Empower staff (trusted): "
            f"client name: {inp.get('client_name') or 'unknown'}; country: {inp.get('client_country') or 'unknown'}; "
            f"quote currency: {inp['currency']}; earliest start Empower wants: {inp.get('desired_start') or 'as soon as possible'}."
        )
        spec: ProjectSpec = await self.agent("analyst", prompt)
        self.deps.spec = spec
        self.state["title"] = f"{spec.project_title} · {spec.client_name}"
        self.state["results"]["spec"] = dump(spec)
        if spec.suspicious_content:
            self.rec.event("analyst", "guardrail", "Analyst flagged suspicious instructions in the document", spec.suspicious_content)
        self.rec.finish_step("analyst", f"{len(spec.features)} features, {len(spec.integrations)} integrations, "
                                        f"{len(spec.open_questions)} open questions" + (", existing client" if spec.existing_client else ""))
        return spec

    def spec_json(self) -> str:
        # The analyst's quotes of suspicious text are not passed on: later agents do not need them.
        return compact(self.deps.spec, drop=("suspicious_content",))

    async def run_architect(self, feedback: str = "") -> SolutionDesign:
        prompt = (
            f"Project specification from the Requirements Analyst:\n<analyst_spec>{self.spec_json()}</analyst_spec>"
            + (f"\n\nReviewer feedback to address:\n<review_feedback>{feedback}</review_feedback>\n"
               f"Your previous design:\n<previous>{compact(self.state['results'].get('design'))}</previous>" if feedback else "")
        )
        design: SolutionDesign = await self.agent("architect", prompt, "Revising after critic feedback" if feedback else "")
        self.deps.design = design
        self.state["results"]["design"] = dump(design)
        self.rec.finish_step("architect", f"{design.feasibility.replace('_', ' ')}; {len(design.work_packages)} work packages; "
                                          f"{len(design.risks)} risks; gaps: {', '.join(design.capability_gaps) or 'none'}")
        return design

    async def run_estimator(self, feedback: str = "") -> None:
        spec, design = self.deps.spec, self.deps.design
        prompt = (
            f"Spec:\n<analyst_spec>{self.spec_json()}</analyst_spec>\n"
            f"Architecture and work packages:\n<design>{compact(design)}</design>"
            + (f"\n\nReviewer feedback to address:\n<review_feedback>{feedback}</review_feedback>\n"
               f"Your previous estimate:\n<previous>{compact(self.state['results'].get('estimate_draft'))}</previous>" if feedback else "")
        )
        draft: EstimateDraft = await self.agent("estimator", prompt, "Revising after critic feedback" if feedback else "")
        est = calc.compute_estimate(self.c, draft, spec.project_type, spec.compliance_flags)
        self.deps.estimate = est
        self.state["results"]["estimate_draft"] = dump(draft)
        self.state["results"]["estimate"] = dump(est)
        self.rec.event("estimator", "calculator", f"Estimate computed: {est.expected_hours:,.0f} h expected (incl. PM, lead, QA policy); "
                                                  f"{est.total_hours:,.0f} h with {est.contingency_pct:.0f}% contingency", {"warnings": est.warnings})
        self.rec.finish_step("estimator", f"{est.expected_hours:,.0f} h expected; {est.total_hours:,.0f} h with contingency; risk {est.risk_level}")

    async def run_staffing(self, feedback: str = "") -> None:
        spec = self.deps.spec
        prompt = (
            f"Plan the team for: {spec.project_title} ({spec.client_name}, {spec.client_country}).\n"
            f"Recommended stack: {compact([s.technology for s in self.deps.design.recommended_stack])}\n"
            f"Earliest start Empower wants: {self.state['input'].get('desired_start') or 'as soon as possible'}. "
            f"Client's requested start: {spec.constraints.requested_start or 'not stated'}. "
            f"Client's go-live deadline: {spec.constraints.deadline_date or 'none stated'}."
            + (f"\n\nReviewer feedback to address:\n<review_feedback>{feedback}</review_feedback>\n"
               f"Your previous plan:\n<previous>{compact(self.state['results'].get('staffing_draft'))}</previous>" if feedback else "")
        )
        draft: StaffingDraft = await self.agent("staffing", prompt, "Revising after critic feedback" if feedback else "")
        sched = calc.plan_schedule(self.c, self.deps.estimate, draft, spec.constraints.deadline_date)
        # Safety net: the calculator's greedy baseline must not be clearly faster than the agent's team.
        try:
            start = max(date.fromisoformat(draft.start_date), self.c.as_of)
        except ValueError:
            start = self.c.as_of
        base_draft = calc.suggest_team(self.c, self.deps.estimate, start, spec.constraints.deadline_date)
        base = calc.plan_schedule(self.c, self.deps.estimate, base_draft, spec.constraints.deadline_date)
        if base.total_weeks < 0.8 * sched.total_weeks and not base.uncovered_roles:
            note = (f"Staffing Planner's team needed {sched.total_weeks} weeks; the calculator's baseline team of free people "
                    f"needs {base.total_weeks} weeks, so the baseline was used.")
            self.rec.event("staffing", "guardrail", note)
            base_draft.gaps, base_draft.notes = draft.gaps, [note, *draft.notes]
            draft, sched = base_draft, base
            sched.warnings.insert(0, note)
        self.deps.total_weeks = sched.total_weeks
        self.state["results"]["staffing_draft"] = dump(draft)
        self.state["results"]["schedule"] = dump(sched)
        self.rec.event("staffing", "calculator", f"Schedule computed: {sched.start_date} to {sched.end_date} ({sched.total_weeks} weeks)",
                       {"warnings": sched.warnings})
        self.rec.finish_step("staffing", f"{len(sched.team)} people; {sched.total_weeks:.1f} weeks; go-live {sched.end_date}"
                                         + (f"; uncovered: {', '.join(sched.uncovered_roles)}" if sched.uncovered_roles else ""))

    async def run_pricing(self, feedback: str = "") -> None:
        spec = self.deps.spec
        prompt = (
            f"Price this deal: {spec.project_title} for {spec.client_name} ({spec.client_country}, {spec.industry}).\n"
            f"Project type: {spec.project_type}. Currency: {self.deps.currency}.\n"
            f"Client budget as stated: {spec.constraints.budget_text or 'not given'}. Deadline: {spec.constraints.deadline or 'not given'}.\n"
            f"Estimate: {self.deps.estimate.total_hours:,.0f} h, risk {self.deps.estimate.risk_level}. "
            f"Feasibility: {self.deps.design.feasibility}. Open questions: {len(spec.open_questions)}.\n"
            f"Staffing result (from the Staffing Planner): {self.staffing_summary()}"
            + (f"\n\nReviewer feedback to address:\n<review_feedback>{feedback}</review_feedback>\n"
               f"Your previous decision:\n<previous>{compact(self.state['results'].get('pricing_decision'))}</previous>" if feedback else "")
        )
        decision: PricingDecision = await self.agent("pricing", prompt, "Revising after critic feedback" if feedback else "")
        self.state["results"]["pricing_decision"] = dump(decision)
        self.rec.finish_step("pricing", f"Recommends {'fixed price' if decision.recommended_model == 'fixed' else 'T&M'}"
                                        f", discount {decision.discount_pct:.1f}%")

    def staffing_summary(self) -> str:
        sch = self.state["results"].get("schedule")
        if not sch:
            return "not available"
        late = "meets the client's deadline" if sch["meets_deadline"] else (
            "MISSES the client's deadline" if sch["meets_deadline"] is False else "no client deadline stated")
        return (f"{len(sch['team'])} people from {sch['start_date']} to {sch['end_date']} ({sch['total_weeks']} weeks), {late}; "
                f"bottleneck {sch['bottleneck_role'] or 'none'}; uncovered roles: {', '.join(sch['uncovered_roles']) or 'none'}; "
                f"capacity gaps: {'; '.join(sch['gaps'][:3]) or 'none'}.")

    def post(self, source: str, target: str, kind: str, severity: str, finding: str, evidence: str, action: str,
             step: str = "orchestrator") -> dict:
        """Shared findings board: what one agent (or the orchestrator) tells another, with the evidence."""
        f = {"from": source, "to": target, "kind": kind, "severity": severity, "finding": finding, "evidence": evidence,
             "action": action, "t": self.rec.event_time(), "pass": self.state["steps"].get(step, {}).get("rounds") or 1}
        self.state["results"].setdefault("findings", []).append(f)
        self.rec.event("orchestrator", "finding", f"{source} → {target}: {finding}", {"evidence": evidence, "action": action})
        return f

    def orchestrate(self) -> list[str]:
        """Code, not a model: reconcile staffing, feasibility and pricing, and decide what must be redone.

        Returns the feedback for the Architect if the scope must be re-split (capacity, deadline or budget conflict
        with no smaller first phase available), else an empty list.
        """
        self.rec.start_step("orchestrator")
        r = self.state["results"]
        sch, q, spec = r["schedule"], r["quote"], self.deps.spec
        problems: list[str] = []
        if sch["uncovered_roles"]:
            problems.append(f"no free people for {', '.join(sch['uncovered_roles'])}")
            self.post("Staffing Planner", "Solution Architect", "capacity", "high",
                      f"No one is free for: {', '.join(sch['uncovered_roles'])}.",
                      "; ".join(sch["gaps"][:3]) or "role capacity check", "Re-scope, phase the work, or plan hiring/subcontracting.")
        if sch["meets_deadline"] is False:
            late = (date.fromisoformat(sch["end_date"]) - date.fromisoformat(spec.constraints.deadline_date)).days \
                if spec.constraints.deadline_date else None
            problems.append(f"go-live {sch['end_date']} is {late} days after the deadline" if late else "the deadline is missed")
            self.post("Staffing Planner", "Solution Architect", "timeline", "high",
                      f"With the people actually free, go-live is {sch['end_date']}" + (f", {late} days late." if late else "."),
                      f"bottleneck {sch['bottleneck_role']}; {sch['total_weeks']} weeks from {sch['start_date']}",
                      "Split must-haves into a first phase that can meet the date.")
        fit = q.get("budget_fit") or ""
        if "above" in fit:
            problems.append(fit.rstrip("."))
            self.post("Pricing calculator", "Solution Architect", "budget", "warning", fit,
                      f"{q['currency']} {q['options'][1]['price']:,.0f} T&M / {q['options'][0]['price']:,.0f} fixed",
                      "Offer a smaller first phase rather than a deep discount.")
        if r.get("phase1"):
            p1 = r["phase1"]
            ok = (not spec.constraints.deadline_date) or p1["go_live"] <= spec.constraints.deadline_date
            self.post("Pricing calculator", "Proposal Writer", "option", "info",
                      f"A Phase 1 option exists: {p1['hours']:,.0f} h, go-live {p1['go_live']}"
                      + (" (meets the deadline)." if ok else " (still after the deadline)."),
                      ", ".join(p1["packages"][:4]), "Lead the proposal with Phase 1 if the client's budget or date is tight.")
        p1 = r.get("phase1")
        budget = spec.constraints.budget_max
        if budget and spec.constraints.budget_currency and spec.constraints.budget_currency.upper() != q["currency"]:
            budget = calc.convert(self.c, budget, spec.constraints.budget_currency.upper(), q["currency"])
        p1_fits = bool(p1) and (not spec.constraints.deadline_date or p1["go_live"] <= spec.constraints.deadline_date)             and (not budget or p1["fixed_price"] <= 1.25 * budget)
        # Re-route once when nothing on the table fits: no Phase 1, or a Phase 1 that still misses the date or the budget.
        reroute = bool(problems) and not p1_fits and self.state["orchestrator_revisions"] == 0
        if reroute:
            self.state["orchestrator_revisions"] += 1
            self.rec.event("orchestrator", "handoff", "Sending back to architect: " + "; ".join(problems),
                           {"architect": problems})
            self.rec.finish_step("orchestrator", "Conflict found (" + "; ".join(problems) + "): re-split the scope, then "
                                 "re-estimate, re-staff and re-price.")
            return problems
        if not problems:
            summary = "No conflicts to route."
        elif p1_fits:
            summary = "Conflicts noted for the critic and the proposal (a Phase 1 option fits): " + "; ".join(problems) + "."
        else:
            summary = ("Still in conflict after one re-split (" + "; ".join(problems) + "); "
                       + ("the Phase 1 option does not fit either" if p1 else "the client's essentials alone do not fit")
                       + ". Left to the critic and the decision-maker.")
        self.rec.finish_step("orchestrator", summary)
        return []

    def compute_quote(self) -> Any:
        spec = self.deps.spec
        decision = PricingDecision.model_validate(self.state["results"]["pricing_decision"])
        quote = calc.price_options(self.c, self.deps.estimate, self.deps.currency, decision.discount_pct, self.deps.total_weeks,
                                   decision.recommended_model, spec.constraints.budget_max, spec.constraints.budget_currency)
        self.state["results"]["quote"] = dump(quote)
        sched = Schedule.model_validate(self.state["results"]["schedule"])
        phase1 = calc.phase1_option(self.c, EstimateDraft.model_validate(self.state["results"]["estimate_draft"]), self.deps.design,
                                    self.deps.estimate, spec.project_type, self.deps.currency, decision.discount_pct, sched,
                                    spec.constraints.budget_max, spec.constraints.budget_currency, spec.compliance_flags)
        self.state["results"]["phase1"] = phase1
        self.deps.notes["checks"] = build_checks(self.c, spec, self.deps.design, self.deps.estimate, sched, quote)
        self.deps.notes["checks"]["phase1_option"] = phase1
        self.state["results"]["checks"] = self.deps.notes["checks"]
        self.rec.event("pricing", "calculator", f"Quote computed: fixed {quote.currency} {quote.options[0].price:,.0f}, "
                                                f"T&M {quote.currency} {quote.options[1].price:,.0f}",
                       {"needs_approval": quote.needs_approval, "approval_reasons": quote.approval_reasons})
        return quote

    async def run_critic(self, round_no: int) -> CriticReview:
        prompt = (
            f"Review this deal (review round {round_no}).\n"
            f"Spec:\n<analyst_spec>{self.spec_json()}</analyst_spec>\n"
            f"Design:\n<design>{compact(self.deps.design)}</design>\n"
            f"Pricing decision:\n<pricing>{compact(self.state['results']['pricing_decision'])}</pricing>\n"
            f"Safety screen findings on the client document: {len(self.state['screen']['findings'])} "
            f"(injection suspected: {self.state['screen'].get('injection_suspected', False)})."
        )
        review: CriticReview = await self.agent("critic", prompt, f"Review round {round_no}")
        self.state["results"].setdefault("reviews", []).append(dump(review))
        self.state["results"]["review"] = dump(review)
        highs = sum(1 for i in review.issues if i.severity == "high")
        self.rec.finish_step("critic", f"Round {round_no}: {review.verdict.upper()}; {len(review.issues)} issues ({highs} high)")
        return review

    async def run_writer(self) -> ProposalDraft:
        spec, design = self.deps.spec, self.deps.design
        sched = self.state["results"]["schedule"]
        # Least privilege: the writer gets no costs, margins, employee ids or internal notes.
        client_view = {
            "spec": json.loads(self.spec_json()),
            "stack": [s.model_dump() for s in design.recommended_stack],
            "work_packages": [w.model_dump() for w in design.work_packages],
            "delivery_risks": [{"risk": r.risk, "mitigation": r.mitigation} for r in design.risks][:5],
            "timeline": {"start": sched["start_date"], "go_live": sched["end_date"], "weeks": sched["total_weeks"],
                         "client_requested_start": spec.constraints.requested_start,
                         "client_go_live_deadline": spec.constraints.deadline_date,
                         "meets_client_deadline": sched["meets_deadline"]},
            "team_roles": sorted({m["role"] for m in sched["team"]}),
            "commercial_model_recommended": self.state["results"]["pricing_decision"]["recommended_model"],
            "phased_launch_option": ({"phase_1": self.state["results"]["phase1"]["packages"],
                                      "phase_2": self.state["results"]["phase1"]["later_packages"],
                                      "phase_1_go_live": self.state["results"]["phase1"]["go_live"]}
                                     if self.state["results"].get("phase1") else None),
            "reference_work": [self.c.projects[p]["name"] + " (" + self.c.projects[p]["industry"] + ")"
                               for p in design.reference_projects if p in self.c.projects][:4],
        }
        prompt = f"Write the proposal for this deal:\n<deal>{json.dumps(client_view, ensure_ascii=False, separators=(',', ':'))}</deal>"
        draft: ProposalDraft = await self.agent("writer", prompt)
        self.state["results"]["proposal_draft"] = dump(draft)
        self.rec.finish_step("writer", f"'{draft.title}': {len(draft.scope_in)} scope items, {len(draft.questions_for_client)} questions")
        return draft

    def guard(self, draft: ProposalDraft) -> None:
        self.rec.start_step("guard")
        r = self.state["results"]
        est, sched, quote = Estimate.model_validate(r["estimate"]), Schedule.model_validate(r["schedule"]), Quote.model_validate(r["quote"])
        # 1) The model-written prose is checked for internal terms AND internal numbers (salaries, cost, margins).
        #    Tables are generated by code from client-facing figures, so numbers there are not re-checked
        #    (a price can legitimately equal some employee's monthly cost in another currency).
        sensitive = self.c.sensitive_numbers() | {f"{quote.internal_cost:,.0f}", f"{quote.margin_pct_fixed}%", f"{quote.margin_pct_tm}%"}
        findings: list[guardrails.Finding] = []
        clean: dict[str, Any] = {}
        for field, value in draft.model_dump().items():
            items = value if isinstance(value, list) else [value]
            out = []
            for text in items:
                res = guardrails.leak_check(str(text), sensitive, self.state["input"].get("brief", ""))
                findings += res.findings
                out.append(res.text)
            clean[field] = out if isinstance(value, list) else out[0]
        draft = ProposalDraft.model_validate(clean)
        md = render.proposal_markdown(self.c, self.deps.spec, self.deps.design, draft, est, sched, quote, r.get("phase1"))
        # 2) The whole assembled document is checked for internal terms and the prompt canary.
        leak = guardrails.leak_check(md)
        leak.findings = findings + leak.findings
        for f in leak.findings:
            self.rec.event("guard", "guardrail", f"[{f.severity}] {f.message}", {"line": f.snippet})
            store.add_safety_event("leak_blocked", "high", f.message, self.run_id, f.to_dict())
        r["proposal_markdown"] = leak.text
        r["leak_findings"] = [f.to_dict() for f in leak.findings]
        review = CriticReview.model_validate(r["review"])
        decision = PricingDecision.model_validate(r["pricing_decision"])
        r["memo_markdown"] = render.memo_markdown(self.c, self.deps.spec, self.deps.design, est, sched, quote, decision, review,
                                                  self.state["screen"]["findings"], r.get("phase1"))
        self.rec.finish_step("guard", f"Redacted {len(leak.findings)} line(s) with internal data." if leak.findings
                                      else "Clean: no internal data in the client document.")

    # ------------------------------------------------------------------ the whole run

    async def run(self) -> None:
        st = self.state
        st["status"] = "running"
        self.persist()
        try:
            clean = self.screen()
            await self.run_analyst(clean)
            await self.run_architect()
            await self.run_estimator()
            await self.run_staffing()
            await self.run_pricing()
            self.compute_quote()
            problems = self.orchestrate()
            if problems:  # capacity/timeline/budget conflict and no option that fits: feasibility, staffing and price redo
                p1 = st["results"].get("phase1")
                fb = ("The Staffing Planner and the pricing calculator found: " + "; ".join(problems) + ". "
                      + (f"The current first phase ({', '.join(p1['packages'])}) still does not fit: go-live {p1['go_live']}, "
                         f"{p1['hours']:,.0f} h. " if p1 else "")
                      + "Mark which work packages are must-have for a first launch (priority 'must') and which can follow "
                        "(should/nice), so a smaller first phase can be staffed and priced within the client's date and budget. "
                        "Do not drop anything the client called essential; say so if the essentials alone cannot fit.")
                await self.run_architect(fb)
                await self.run_estimator("The work packages changed after a staffing/timeline conflict; estimate the revised packages.")
                await self.run_staffing("Re-plan the team for the revised scope; aim to meet the client's deadline with a first phase.")
                await self.run_pricing("The scope and schedule were revised after a capacity/timeline conflict; re-decide model and discount.")
                self.compute_quote()
                self.orchestrate()
            review = await self.run_critic(1)

            # One review-driven revision in total: if the orchestrator already re-split the scope, the critic reviews only.
            for round_no in range(MAX_REVISION_ROUNDS if not self.state["orchestrator_revisions"] else 0):
                # Fixable HIGH issues go back even when the verdict is "escalate": agents fix what they can,
                # people decide the rest.
                fixes = [i for i in review.issues if i.severity == "high" and i.send_back_to != "none"]
                if review.verdict == "approve" or not fixes:
                    break
                st["revisions"] += 1
                targets = {i.send_back_to for i in fixes}
                fb = {k: "\n".join(f"- {i.finding} -> {i.recommendation}" for i in fixes if i.send_back_to == k) for k in targets}
                self.rec.event("critic", "handoff", f"Sending back to {', '.join(sorted(targets))} (revision {st['revisions']})", fb)
                for i in fixes:
                    self.post("Deal Critic", i.send_back_to, i.area, "high", i.finding, "critic review", i.recommendation, step="critic")
                if "architect" in targets:  # new scope/priorities -> new estimate -> new team and price
                    await self.run_architect(fb["architect"])
                    await self.run_estimator(fb.get("estimator", "The work packages changed; estimate the revised packages."))
                    await self.run_staffing(fb.get("staffing", ""))
                    await self.run_pricing(fb.get("pricing", ""))
                elif "estimator" in targets:  # a new estimate invalidates the team and the price
                    await self.run_estimator(fb["estimator"])
                    await self.run_staffing(fb.get("staffing", ""))
                    await self.run_pricing(fb.get("pricing", ""))
                else:
                    if "staffing" in targets:
                        await self.run_staffing(fb["staffing"])
                    if "pricing" in targets or "staffing" in targets:  # a new schedule must be re-priced
                        await self.run_pricing(fb.get("pricing", "The team and schedule changed; re-decide model and discount."))
                self.compute_quote()
                review = await self.run_critic(round_no + 2)

            draft = await self.run_writer()
            self.guard(draft)
            st["status"] = "ready"
        except UsageLimitExceeded as exc:
            st["status"] = "failed"
            st["error"] = f"Stopped by the per-run safety limit: {exc}"
            store.add_safety_event("run_limit_stop", "high", st["error"], self.run_id)
            self._fail_running_steps(st["error"])
        except ModelHTTPError as exc:
            if guardrails.is_content_filter(exc):
                st["status"] = "blocked"
                st["error"] = ("The model provider's safety filter refused this document (it looks like a jailbreak attempt), "
                               "so no quote was produced. Review the document yourself before going further.")
                store.add_safety_event("provider_content_filter", "high", st["error"], self.run_id)
            else:
                st["status"], st["error"] = "failed", f"ModelHTTPError {exc.status_code}: {exc.body}"
            self._fail_running_steps(st["error"])
        except Exception as exc:  # noqa: BLE001 -- a failed run must still be saved and shown
            st["status"] = "failed"
            st["error"] = f"{type(exc).__name__}: {exc}"
            self._fail_running_steps(st["error"])
        finally:
            self.persist()
            ACTIVE.pop(self.run_id, None)

    async def rerun_review(self, prev_usage: dict | None) -> None:
        """After a person applies a scenario: re-price from the stored decision, then re-run only the agents whose
        inputs changed (Deal Critic, Proposal Writer) and the leak guard. Earlier steps are not repeated."""
        st, r = self.state, self.state["results"]
        st["status"] = "running"
        self.persist()
        try:
            self.deps.spec = ProjectSpec.model_validate(r["spec"])
            self.deps.design = SolutionDesign.model_validate(r["design"])
            self.deps.estimate = Estimate.model_validate(r["estimate"])
            self.deps.total_weeks = r["schedule"]["total_weeks"]
            self.rec.event("orchestrator", "handoff", "Assumptions changed by a person: re-pricing, then re-running the Deal Critic and the Proposal Writer",
                           r.get("applied_scenario"))
            self.compute_quote()
            await self.run_critic(len(r.get("reviews", [])) + 1)
            draft = await self.run_writer()
            self.guard(draft)
            r["proposal_stale"] = False
            st["status"] = "ready"
        except Exception as exc:  # noqa: BLE001
            st["status"], st["error"] = "failed", f"{type(exc).__name__}: {exc}"
            self._fail_running_steps(st["error"])
        finally:
            if prev_usage:  # add the re-run's tokens to the deal's running total
                new = st.get("usage") or {}
                merged = {k: (prev_usage.get(k) or 0) + (new.get(k) or 0) for k in
                          ("input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens", "requests", "tool_calls", "cost_usd")}
                merged["cache_hit_pct"] = round(100 * merged["cached_tokens"] / merged["input_tokens"], 1) if merged["input_tokens"] else 0.0
                st["usage"] = merged
            self.persist()
            ACTIVE.pop(self.run_id, None)

    def _fail_running_steps(self, why: str) -> None:
        for s in self.state["steps"].values():
            if s["status"] == "running":
                s["status"] = "failed"
                s["summary"] = why
            elif s["status"] == "pending":
                s["status"] = "skipped"


def start_run(inp: dict[str, Any], client_ip: str) -> str:
    run_id = uuid.uuid4().hex[:10]
    state = new_state(run_id, inp, client_ip)
    run = DealRun(run_id, state)  # builds agents now so a missing key fails the request, not the task
    ACTIVE[run_id] = state
    run.persist()
    task = asyncio.get_running_loop().create_task(run.run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return run_id


def start_rerun(run_id: str) -> None:
    state = store.get_run(run_id)
    prev = dict(state.get("usage") or {})
    run = DealRun(run_id, state)
    ACTIVE[run_id] = state
    task = asyncio.get_running_loop().create_task(run.rerun_review(prev))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def get_state(run_id: str) -> dict | None:
    return ACTIVE.get(run_id) or store.get_run(run_id)


COLLAB_KINDS = ("agent_end", "handoff", "calculator", "finding")


def collaboration(state: dict) -> list[dict]:
    """The run as a story: who finished what, which numbers code computed, and who sent work to whom."""
    labels = {k: v.get("label", k) for k, v in state.get("steps", {}).items()}
    out = []
    for e in state.get("trace", []):
        if e.get("kind") not in COLLAB_KINDS:
            continue
        agent = e.get("agent") or ""
        out.append({"t": e.get("t"), "kind": e["kind"], "agent": agent, "label": labels.get(agent, agent.title()),
                    "text": e.get("text", "")})
    if state.get("status") == "ready":
        out.append({"t": None, "kind": "status", "agent": "human", "label": "People", "text": "Awaiting a person's decision."})
    elif state.get("decision"):
        d = state["decision"]
        out.append({"t": None, "kind": "status", "agent": "human", "label": d.get("approver", "People"),
                    "text": f"Decision: {d.get('action', '').replace('_', ' ')}."})
    return out
