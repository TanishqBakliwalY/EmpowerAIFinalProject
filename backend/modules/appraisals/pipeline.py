"""One appraisal cycle run: who hands work to whom.

    evidence (code) -> Calibration Analyst -> Hike Strategist -> optimizer (code)
        -> Fairness Auditor --(adjustments, once)--> rebalance (code) -> Fairness Auditor (round 2)
        -> Manager Brief Writer (one per manager, in parallel) -> privacy check (code) -> HR decision

Agents choose (flags, weights, adjustments, words); code counts (every hike and rupee, exactly to the pool);
a person approves.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from statistics import mean
from typing import Any

from pydantic_ai.exceptions import UsageLimitExceeded

from ...core import guardrails, store
from ...core.company import company
from ...core.config import MODEL_NAME, PROMPT_CANARY
from ...core.runner import RunRecorder
from . import optimizer as opt
from .agents import SPECS, build_agent
from .data import AppraisalData, appraisal_data
from .models import CalibrationReport, FairnessReview, ManagerBrief, StrategyDecision
from .tools import AppDeps

MODULE_KEY = "appraisals"
ACTIVE: dict[str, dict[str, Any]] = {}
_TASKS: set[asyncio.Task] = set()

STEP_ORDER = [
    ("evidence", "Evidence & market data", "code", "Evidence scores, compa-ratios and retention risk for everyone."),
    ("calibration", SPECS["calibration"].label, "agent", SPECS["calibration"].job),
    ("strategy", SPECS["strategy"].label, "agent", SPECS["strategy"].job),
    ("optimizer", "Budget optimizer", "code", "Spends the pool exactly, inside each person's caps."),
    ("fairness", SPECS["fairness"].label, "agent", SPECS["fairness"].job),
    ("rebalance", "Rebalance", "code", "Applies the auditor's adjustments and rebalances to the pool."),
    ("briefs", SPECS["briefs"].label, "agent", SPECS["briefs"].job),
    ("privacy", "Privacy check", "code", "Blocks other teams' names and pay, gender and prompt text in briefs."),
]
_GENDER = re.compile(r"\b(gender|female|male|women|woman|men|man|girls?|boys?|maternity|paternity)\b", re.I)


def inr(n: float) -> str:
    """Indian digit grouping: 1234567 -> 12,34,567."""
    s = str(abs(int(round(n))))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if n < 0 else "") + s


def new_state(run_id: str, inp: dict[str, Any], client_ip: str, user: dict | None = None) -> dict[str, Any]:
    d = appraisal_data()
    return {
        "id": run_id, "module": MODULE_KEY, "status": "queued", "created_at": store.now_iso(),
        "title": f"{d.policy.get('cycle', 'Hike cycle')} · pool {inp['pool_pct']:g}% of payroll",
        "model": MODEL_NAME, "input": inp, "client_ip": client_ip,
        "created_by": (user or {}).get("name"),
        "steps": {k: {"key": k, "label": label, "kind": kind, "job": job, "status": "pending"} for k, label, kind, job in STEP_ORDER},
        "trace": [], "results": {}, "decision": None, "error": None,
    }


def compact(x: Any) -> str:
    return json.dumps(x.model_dump(mode="json") if hasattr(x, "model_dump") else x, ensure_ascii=False, separators=(",", ":"))


class AppraisalRun:
    def __init__(self, run_id: str, state: dict[str, Any], data: AppraisalData | None = None, save: bool = True) -> None:
        self.c = company()
        self.d = data or appraisal_data()
        self.state = state
        self.run_id = run_id
        self.save = save
        self.rec = RunRecorder(run_id, MODULE_KEY, state, self.persist)
        self.deps = AppDeps(data=self.d, company=self.c, pool_pct=float(state["input"]["pool_pct"]))
        self.agents = {k: build_agent(self.d, self.c.as_of.isoformat(), k) for k in SPECS}

    def persist(self) -> None:
        if self.save:
            store.save_run(self.run_id, MODULE_KEY, self.state["status"], self.state["title"], self.state,
                           self.state.get("client_ip", ""))

    async def agent(self, key: str, prompt: str, detail: str = "") -> Any:
        self.rec.start_step(key, detail)
        return await self.rec.run_agent(key, self.agents[key], prompt, self.deps)

    # ------------------------------------------------------------------ steps

    def evidence(self) -> None:
        self.rec.start_step("evidence")
        ps = list(self.d.people.values())
        pool = round(self.d.payroll * self.deps.pool_pct / 100)
        offices = {off: round(mean(p.compa_ratio for p in ps if p.office == off), 3) for off in sorted({p.office for p in ps})}
        ev = {"headcount": len(ps), "payroll": self.d.payroll, "pool_pct": self.deps.pool_pct, "pool_amount": pool,
              "ratings": {str(r): sum(1 for p in ps if p.rating == r) for r in range(1, 6)},
              "promotions_recommended": sum(1 for p in ps if p.promotion_recommended),
              "retention_high": sum(1 for p in ps if p.retention_risk == "high"),
              "avg_compa_by_office": offices, "managers": self.d.managers}
        self.state["results"]["evidence"] = ev
        self.rec.finish_step("evidence", f"{len(ps)} people · payroll ₹{inr(self.d.payroll)} · pool ₹{inr(pool)} "
                                         f"({self.deps.pool_pct:g}%) · {ev['retention_high']} high retention risk")

    async def run_calibration(self) -> CalibrationReport:
        note = self.state["input"].get("note") or ""
        prompt = (f"Calibrate the {self.d.policy.get('cycle')} ratings for {len(self.d.people)} people across "
                  f"{len(self.d.managers)} managers ({', '.join(f'{k} {v}' for k, v in self.d.managers.items())})."
                  + (f"\nHR's note for this cycle (data):\n{guardrails.spotlight(note, 'hr_note')}" if note else ""))
        rep: CalibrationReport = await self.agent("calibration", prompt)
        known = set(self.d.people)
        dropped = [f.emp_id for f in rep.flags if f.emp_id not in known]
        rep.flags = [f for f in rep.flags if f.emp_id in known]
        if dropped:
            self.rec.event("calibration", "guardrail", f"Removed flags for unknown ids {dropped}")
        self.deps.calibration = rep.model_dump(mode="json")
        self.state["results"]["calibration"] = self.deps.calibration
        self.rec.finish_step("calibration", f"{len(rep.flags)} rating flags · {len(rep.manager_patterns)} manager patterns")
        return rep

    async def run_strategy(self) -> dict:
        prompt = (f"Choose the weighting for a pool of {self.deps.pool_pct:g}% of payroll. "
                  f"The Calibration Analyst raised {len(self.deps.calibration.get('flags', []))} flags; summary: "
                  f"{self.deps.calibration.get('summary', '')}")
        dec: StrategyDecision = await self.agent("strategy", prompt)
        chosen = opt.clamp_strategy(self.d.policy, dec.model_dump())
        self.deps.strategy = chosen
        self.state["results"]["strategy"] = {"chosen": chosen, "proposed": dec.model_dump(mode="json"), "rationale": dec.rationale}
        self.rec.event("strategy", "calculator", "Weights clamped to HR policy bounds", chosen)
        self.rec.finish_step("strategy", "performance {performance_weight} · market {market_weight} · retention "
                                         "{retention_weight} · promotions {promotion_share_pct}%".format(**chosen))
        return chosen

    def _store_allocation(self, a: opt.Allocation, key: str) -> None:
        r = self.state["results"]
        r["summary"] = opt.summary(self.d, a)
        r["proposal"] = opt.proposal_rows(self.d, a)
        r[key] = opt.fairness_metrics(self.d, a)

    def optimize(self) -> None:
        self.rec.start_step("optimizer")
        a = opt.allocate(self.d, self.deps.strategy, self.deps.pool_pct)
        self.deps.allocation = a
        self._store_allocation(a, "fairness_before")
        sm = self.state["results"]["summary"]
        self.rec.event("optimizer", "calculator", f"Allocated ₹{inr(a.used_amount)} of ₹{inr(a.pool_amount)}",
                       {"feasible": a.feasible, "note": a.note, "by_rating": sm["by_rating"]})
        self.rec.finish_step("optimizer", ("Pool used exactly" if a.used_amount == a.pool_amount else a.note)
                             + f" · avg hike {sm['avg_hike_pct']}% · {sm['promotions']} promotions")

    async def run_fairness(self, round_no: int) -> FairnessReview:
        prompt = (f"Fairness audit, round {round_no}. Pool {self.deps.pool_pct:g}% of payroll; strategy {compact(self.deps.strategy)}."
                  + (" The optimizer has applied your round-1 adjustments and rebalanced the pool; judge the result."
                     if round_no == 2 else ""))
        rev: FairnessReview = await self.agent("fairness", prompt, f"Review round {round_no}")
        lo, hi = self.d.policy["max_adjustment_pp"]
        rev.adjustments = [a for a in rev.adjustments if a.emp_id in self.d.people][:10]
        for a in rev.adjustments:
            a.add_pp = max(lo, min(hi, a.add_pp))
        self.state["results"].setdefault("reviews", []).append(rev.model_dump(mode="json"))
        highs = sum(1 for i in rev.issues if i.severity == "high")
        self.rec.finish_step("fairness", f"Round {round_no}: {rev.verdict.upper()} · {len(rev.issues)} issues ({highs} high) · "
                                         f"{len(rev.adjustments)} adjustments")
        return rev

    def rebalance(self, rev: FairnessReview) -> None:
        self.rec.start_step("rebalance")
        before = {e: self.deps.allocation.hikes_pct[e] for e in (a.emp_id for a in rev.adjustments)}
        a = opt.allocate(self.d, self.deps.strategy, self.deps.pool_pct, overrides_pp={x.emp_id: x.add_pp for x in rev.adjustments})
        self.deps.allocation = a
        self._store_allocation(a, "fairness_after")
        applied = [{"emp_id": x.emp_id, "name": self.d.people[x.emp_id].name, "requested_pp": x.add_pp,
                    "hike_before": before[x.emp_id], "hike_after": a.hikes_pct[x.emp_id], "reason": x.reason}
                   for x in rev.adjustments]
        self.state["results"]["adjustments_applied"] = applied
        self.rec.event("rebalance", "calculator", f"Applied {len(applied)} adjustments; pool still exact: {a.used_amount == a.pool_amount}",
                       applied)
        self.rec.finish_step("rebalance", f"{len(applied)} people adjusted · everyone else rebalanced · pool used "
                                          f"{'exactly' if a.used_amount == a.pool_amount else 'with a remainder'}")

    async def run_briefs(self) -> None:
        self.rec.start_step("briefs", f"{len(self.d.managers)} managers in parallel")
        a = self.deps.allocation
        cal = {f["emp_id"]: f for f in (self.deps.calibration or {}).get("flags", [])}

        async def one(mgr: str) -> tuple[str, ManagerBrief | None]:
            team = sorted(self.d.team(mgr), key=lambda p: p.name)
            if not team:
                return mgr, None
            rows = [{"emp_id": p.emp_id, "name": p.name, "title": p.title, "rating": p.rating, "hike_pct": a.hikes_pct[p.emp_id],
                     "promotion": p.emp_id in a.promotion_addon_pct, "hr_adjusted": p.emp_id in a.locked,
                     "client_feedback": p.client_feedback_score, "utilization_pct": p.utilization_12m_pct,
                     "skills_added": p.skills_added, "manager_notes": p.manager_notes,
                     "calibration_note": cal.get(p.emp_id, {}).get("evidence")} for p in team]
            prompt = (f"Brief for manager {mgr} ({self.d.managers.get(mgr)}) about their own team of {len(team)}. "
                      f"Effective date {self.d.policy.get('effective_date')}.\n<team>{compact(rows)}</team>")
            out = await self.rec.run_agent("briefs", self.agents["briefs"], prompt, self.deps)
            return mgr, out

        results = await asyncio.gather(*(one(m) for m in self.d.managers))
        self.state["results"]["brief_drafts"] = {m: b.model_dump(mode="json") for m, b in results if b}
        self.rec.finish_step("briefs", f"{sum(1 for _, b in results if b)} manager briefs drafted")

    def privacy(self) -> None:
        """Each manager's brief may mention only their own team: no other names, other pay, gender or prompt text."""
        self.rec.start_step("privacy")
        a = self.deps.allocation
        findings: list[dict] = []
        briefs: dict[str, str] = {}
        for mgr, raw in self.state["results"].get("brief_drafts", {}).items():
            team = {p.emp_id for p in self.d.team(mgr)}
            others = [p for p in self.d.people.values() if p.emp_id not in team and p.emp_id != mgr]
            other_names = [p.name for p in others]
            other_nums: set[str] = set()
            for p in others:
                for n in (p.ctc, p.ctc + a.amounts[p.emp_id], a.amounts[p.emp_id]):
                    other_nums |= {inr(n), f"{n:,}", str(n)}

            def check(text: str, where: str) -> str:
                reason = None
                if PROMPT_CANARY in text:
                    reason = "prompt text"
                elif any(n in text for n in other_names):
                    reason = "another team's employee"
                elif any(len(x) >= 5 and x in text for x in other_nums):
                    reason = "another team's pay"
                elif _GENDER.search(text):
                    reason = "gender"
                if reason:
                    findings.append({"manager": mgr, "where": where, "reason": reason, "text": text[:200]})
                    store.add_safety_event("privacy_redacted", "high", f"Manager brief for {mgr}: removed {reason}.",
                                           self.run_id, {"text": text[:200]})
                    return "[Removed by the privacy check]"
                return text

            b = ManagerBrief.model_validate(raw)
            b.headline = check(b.headline, "headline")
            b.team_summary = check(b.team_summary, "summary")
            for tp in b.talking_points:
                tp.points = [check(x, f"points for {tp.emp_id}") for x in tp.points]
            b.reminders = [check(x, "reminders") for x in b.reminders]
            b.talking_points = [tp for tp in b.talking_points if tp.emp_id in team]
            briefs[mgr] = self.render_brief(mgr, b)
        self.state["results"]["briefs"] = briefs
        self.state["results"]["privacy_findings"] = findings
        self.state["results"]["memo_markdown"] = self.memo()
        self.rec.finish_step("privacy", f"Removed {len(findings)} line(s)" if findings else "Clean: each brief covers its own team only")

    # ------------------------------------------------------------------ documents

    def render_brief(self, mgr: str, b: ManagerBrief) -> str:
        a = self.deps.allocation
        team = sorted(self.d.team(mgr), key=lambda p: p.name)
        pts = {tp.emp_id: tp.points for tp in b.talking_points}
        rows = "\n".join(
            f"| {p.name} | {p.title} | {p.rating} | {a.hikes_pct[p.emp_id]:.1f}% | ₹{inr(a.amounts[p.emp_id])} | ₹{inr(p.ctc + a.amounts[p.emp_id])} |"
            + (" promotion |" if p.emp_id in a.promotion_addon_pct else " |") for p in team)
        people = "\n\n".join(f"**{p.name}**\n\n" + "\n".join(f"- {x}" for x in pts.get(p.emp_id, ["(no talking points)"]))
                             for p in team)
        return (f"# {b.headline}\n\n**Manager:** {self.d.managers.get(mgr, mgr)} ({mgr}) · **Cycle:** {self.d.policy.get('cycle')} · "
                f"**Effective:** {self.d.policy.get('effective_date')} · Confidential\n\n{b.team_summary}\n\n"
                f"| Person | Title | Rating | Hike | Increase | New annual CTC | |\n|---|---|---|---|---|---|---|\n{rows}\n\n"
                f"## Talking points\n\n{people}\n\n## Reminders\n\n" + "\n".join(f"- {x}" for x in b.reminders))

    def memo(self) -> str:
        r = self.state["results"]
        sm, st = r["summary"], r["strategy"]["chosen"]
        reviews = r.get("reviews", [])
        final = reviews[-1] if reviews else {}
        by_rating = "\n".join(f"| {b['rating']} | {b['people']} | {b['avg_hike_pct']}% | {b['min_hike_pct']}–{b['max_hike_pct']}% |"
                              for b in sm["by_rating"])
        issues = "\n".join(f"| {i['severity'].upper()} | {i['kind']} | {i['group']} | {i['finding']} |" for i in final.get("issues", [])) \
            or "| - | - | - | No issues |"
        adj = "\n".join(f"| {x['name']} ({x['emp_id']}) | {x['hike_before']}% | {x['hike_after']}% | {x['reason']} |"
                        for x in r.get("adjustments_applied", [])) or "| - | - | - | none |"
        flags = "\n".join(f"- **{f['emp_id']}** {f['issue'].replace('_', ' ')} (rating {f['current_rating']}"
                          + (f" → suggest {f['suggested_rating']}" if f.get("suggested_rating") else "") + f"): {f['evidence']}"
                          for f in r.get("calibration", {}).get("flags", [])) or "- None"
        offices = "\n".join(f"| {o['office']} | {o['avg_compa_before']} | {o['avg_compa_after']} | {o['avg_hike_pct']}% |"
                            for o in r.get("fairness_after", r.get("fairness_before", {})).get("offices", []))
        return f"""# HR director memo: {self.d.policy.get('cycle')} hike cycle

**Fairness verdict:** {final.get('verdict', '-').upper()} · **Pool:** ₹{inr(sm['pool_amount'])} ({self.deps.pool_pct:g}% of payroll) · **Allocated:** ₹{inr(sm['used_amount'])} · **Average hike:** {sm['avg_hike_pct']}%

{final.get('summary', '')}

## Strategy

Performance {st['performance_weight']} · market {st['market_weight']} · retention {st['retention_weight']} · promotion share {st['promotion_share_pct']}% of the pool ({sm['promotions']} promotions).

{chr(10).join('- ' + x for x in r['strategy']['rationale'])}

## Hikes by rating

| Rating | People | Average | Range |
|---|---|---|---|
{by_rating}

## Market position by office (compa-ratio)

| Office | Before | After | Avg hike |
|---|---|---|---|
{offices}

## Fairness issues (final review)

| Severity | Kind | Group | Finding |
|---|---|---|---|
{issues}

## Adjustments applied by the Fairness Auditor

| Person | Before | After | Reason |
|---|---|---|---|
{adj}

## Calibration flags (ratings are the managers' call; HR decides)

{flags}
"""

    # ------------------------------------------------------------------ the whole run

    async def run(self) -> None:
        st = self.state
        st["status"] = "running"
        self.persist()
        try:
            self.evidence()
            await self.run_calibration()
            await self.run_strategy()
            self.optimize()
            rev = await self.run_fairness(1)
            if rev.adjustments and rev.verdict in ("adjust", "escalate"):
                self.rebalance(rev)
                await self.run_fairness(2)
            else:
                self.rec.skip_step("rebalance", "No adjustments proposed.")
                self.state["results"]["fairness_after"] = self.state["results"]["fairness_before"]
            await self.run_briefs()
            self.privacy()
            st["status"] = "ready"
        except UsageLimitExceeded as exc:
            st["status"], st["error"] = "failed", f"Stopped by the per-run safety limit: {exc}"
            store.add_safety_event("run_limit_stop", "high", st["error"], self.run_id)
            self._fail_running_steps(st["error"])
        except Exception as exc:  # noqa: BLE001 - a failed run must still be saved and shown
            st["status"], st["error"] = "failed", f"{type(exc).__name__}: {exc}"
            self._fail_running_steps(st["error"])
        finally:
            self.persist()
            ACTIVE.pop(self.run_id, None)

    def _fail_running_steps(self, why: str) -> None:
        for s in self.state["steps"].values():
            if s["status"] == "running":
                s.update(status="failed", summary=why)
            elif s["status"] == "pending":
                s["status"] = "skipped"


def start_run(inp: dict[str, Any], client_ip: str, user: dict | None = None) -> str:
    run_id = uuid.uuid4().hex[:10]
    state = new_state(run_id, inp, client_ip, user)
    run = AppraisalRun(run_id, state)
    ACTIVE[run_id] = state
    run.persist()
    task = asyncio.get_running_loop().create_task(run.run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return run_id


def get_state(run_id: str) -> dict | None:
    return ACTIVE.get(run_id) or store.get_run(run_id)
