"""The Scope-Creep Guard run: one client message checked against one signed SOW.

    screen (code) -> Request Splitter -> Scope Matcher -> citation check (code)
        -> Change-Request Estimator (only if something is out of scope) -> CR pricing (code)
        -> Reply Drafter -> leak guard (code) -> waiting for a person to approve

Agents classify and estimate; code verifies the clause citations, prices change requests from the SOW's
own rates, and checks the reply for internal data. A delivery manager approves (and can absorb items as goodwill).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded

from ...core import guardrails, store
from ...core.company import CompanyData, company
from ...core.config import MODEL_NAME
from ...core.runner import RunRecorder
from . import calculators as calc
from .agents import SPECS, build_agent
from .models import CheckedItem, ClientReply, CREstimate, MatchResult, Pricing, SplitResult
from .tools import ScopeDeps

MODULE_KEY = "scope_guard"
REDACTED_LINE = guardrails.REDACTED_LINE
redact_ai_directed_lines = guardrails.redact_ai_directed_lines
ACTIVE: dict[str, dict[str, Any]] = {}
_TASKS: set[asyncio.Task] = set()

STEP_ORDER = [
    ("screen", "Safety screen", "code", "Strips hidden text and flags instructions aimed at the AI."),
    ("splitter", SPECS["splitter"].label, "agent", SPECS["splitter"].job),
    ("matcher", SPECS["matcher"].label, "agent", SPECS["matcher"].job),
    ("check", "Citation check", "code", "Every verdict must cite SOW clauses that exist and support it; else 'ambiguous'."),
    ("estimator", SPECS["estimator"].label, "agent", SPECS["estimator"].job),
    ("pricing", "CR pricing", "code", "Change-request price = hours x the SOW's rates + PM overhead."),
    ("reply", SPECS["reply"].label, "agent", SPECS["reply"].job),
    ("guard", "Leak guard", "code", "Blocks internal costs, margins or prompt text in the client reply."),
]


def dump(m: Any) -> Any:
    if isinstance(m, (list, tuple)):
        return [dump(x) for x in m]
    return m.model_dump(mode="json") if hasattr(m, "model_dump") else m


def compact(obj: Any) -> str:
    return json.dumps(dump(obj), ensure_ascii=False, separators=(",", ":"))


def new_state(run_id: str, inp: dict[str, Any], sow: dict, client_ip: str, user: dict | None) -> dict[str, Any]:
    return {
        "id": run_id,
        "module": MODULE_KEY,
        "status": "queued",
        "created_at": store.now_iso(),
        "title": f"{sow['client']}: {inp.get('subject') or 'client message'}",
        "model": MODEL_NAME,
        "input": inp,
        "sow": calc_summary(sow),
        "client_ip": client_ip,
        "created_by": (user or {}).get("name"),
        "steps": {k: {"key": k, "label": label, "kind": kind, "job": job, "status": "pending"} for k, label, kind, job in STEP_ORDER},
        "trace": [],
        "results": {},
        "screen": {"findings": []},
        "decision": None,
        "error": None,
    }


def calc_summary(sow: dict) -> dict:
    return {k: sow.get(k) for k in ("sow_id", "project_name", "client", "currency", "contract_value", "contract_type")}


class ScopeRun:
    def __init__(self, run_id: str, state: dict[str, Any], sow: dict, company_data: CompanyData | None = None,
                 save: bool = True) -> None:
        self.c = company_data or company()
        self.sow = sow
        self.state = state
        self.run_id = run_id
        self.save = save
        self.rec = RunRecorder(run_id, MODULE_KEY, state, self.persist)
        self.deps = ScopeDeps(company=self.c, sow=sow)
        self.agents = {k: build_agent(self.c, k) for k in SPECS}

    def persist(self) -> None:
        if self.save:
            store.save_run(self.run_id, MODULE_KEY, self.state["status"], self.state["title"], self.state,
                           self.state.get("client_ip", ""))

    async def agent(self, key: str, prompt: str) -> Any:
        self.rec.start_step(key)
        return await self.rec.run_agent(key, self.agents[key], prompt, self.deps)

    # ------------------------------------------------------------------ steps

    def screen(self) -> str:
        self.rec.start_step("screen")
        res = guardrails.screen_untrusted(self.state["input"]["message"])
        clean, removed = redact_ai_directed_lines(res.clean_text)
        self.state["screen"] = {"findings": [f.to_dict() for f in res.findings], "injection_suspected": res.injection_suspected,
                                "removed_lines": removed}
        for f in res.findings:
            self.rec.event("screen", "guardrail", f"[{f.severity}] {f.message}", {"snippet": f.snippet})
            if f.severity == "high":
                store.add_safety_event("prompt_injection_flagged", "high", f"Scope Guard: {f.message}", self.run_id, f.to_dict())
        n = len(res.findings)
        self.rec.finish_step("screen", (f"Suspected injection: {removed} line(s) aimed at the AI removed." if res.injection_suspected
                                        else f"{n} minor finding(s)." if n else "Clean."))
        return clean

    async def split(self, clean: str) -> SplitResult:
        s = self.sow
        prompt = (f"Project: {s['project_name']} for {s['client']} (SOW {s['sow_id']}).\n"
                  f"Subject: {self.state['input'].get('subject') or '(none)'}\n"
                  f"Client message (untrusted):\n{guardrails.spotlight(clean, 'client_message')}")
        out: SplitResult = await self.agent("splitter", prompt)
        self.state["results"]["asks"] = dump(out.asks)
        if out.suspicious_content:
            self.rec.event("splitter", "guardrail", "Splitter flagged text aimed at the AI", out.suspicious_content)
        self.rec.finish_step("splitter", f"{len(out.asks)} ask(s)")
        return out

    async def match(self, split: SplitResult) -> MatchResult:
        prompt = ("Classify each ask against the SOW (read it with get_sow).\n"
                  f"<asks>{compact([a.model_dump() for a in split.asks])}</asks>")
        out: MatchResult = await self.agent("matcher", prompt)
        self.state["results"]["matches"] = dump(out)
        verdicts = [m.verdict for m in out.matches]
        self.rec.finish_step("matcher", ", ".join(f"{verdicts.count(v)} {v.replace('_', ' ')}" for v in sorted(set(verdicts))) or "no verdicts")
        return out

    def check(self, split: SplitResult, matches: MatchResult) -> list[CheckedItem]:
        self.rec.start_step("check")
        items = calc.validate(self.sow, split.asks, matches)
        self.state["results"]["items"] = dump(items)
        down = [i for i in items if i.downgraded]
        for i in down:
            self.rec.event("check", "guardrail", f"{i.ask_id} downgraded to ambiguous: {i.downgrade_reason}")
        self.rec.finish_step("check", f"{len(down)} verdict(s) downgraded to ambiguous." if down else "All citations valid.")
        return items

    async def estimate(self, items: list[CheckedItem]) -> CREstimate | None:
        oos = [i for i in items if i.verdict == "out_of_scope"]
        if not oos:
            self.rec.skip_step("estimator", "Nothing out of scope: no change request to estimate.")
            return None
        s = self.sow
        prompt = (f"Project: {s['project_name']} for {s['client']} (existing system Empower is building).\n"
                  "Estimate a change request for each of these out-of-scope asks:\n"
                  f"<asks>{compact([{'ask_id': i.ask_id, 'summary': i.summary, 'client_words': i.quote} for i in oos])}</asks>")
        out: CREstimate = await self.agent("estimator", prompt)
        self.state["results"]["estimate"] = dump(out)
        self.rec.finish_step("estimator", f"{len(out.items)} change request(s) estimated")
        return out

    def price(self, items: list[CheckedItem], est: CREstimate | None) -> Pricing:
        self.rec.start_step("pricing")
        p = calc.price(self.sow, items, est, self.c.policy["pm_overhead_pct"])
        self.state["results"]["pricing"] = dump(p)
        for w in p.warnings:
            self.rec.event("pricing", "calculator", w)
        self.rec.finish_step("pricing", f"{len(p.items)} CR(s): {p.total_hours:,.1f} h, {p.currency} {p.total_price:,.0f}"
                             if p.items else "No change requests.")
        return p

    async def reply(self, items: list[CheckedItem], pricing: Pricing) -> ClientReply:
        titles = {c["id"]: c["title"] for c in self.sow["clauses"]}
        crs = {p.ask_id: p for p in pricing.items}
        view = {
            "client": self.sow["client"], "project": self.sow["project_name"],
            "asks": [{"ask_id": i.ask_id, "client_words": i.quote, "summary": i.summary, "verdict": i.verdict,
                      "sow_clauses": [f"{c}: {titles[c]}" for c in i.clause_ids],
                      "question": i.question_for_client if i.verdict == "ambiguous" else None,
                      "change_request": ({"hours": crs[i.ask_id].total_hours, "price": f"{pricing.currency} {crs[i.ask_id].price:,.0f}"}
                                         if i.ask_id in crs and crs[i.ask_id].estimated else None)} for i in items],
        }
        out: ClientReply = await self.agent("reply", f"Draft the reply for:\n<scope_review>{compact(view)}</scope_review>")
        self.state["results"]["reply_draft"] = dump(out)
        self.rec.finish_step("reply", f"'{out.subject}'")
        return out

    def guard(self, reply: ClientReply, pricing: Pricing) -> None:
        self.rec.start_step("guard")
        # Prices in the reply come from code; don't let one collide with an employee's internal cost figure.
        prices = {f"{p.price:,.0f}" for p in pricing.items} | {f"{p.price:.0f}" for p in pricing.items}
        sensitive = self.c.sensitive_numbers() - prices
        res = guardrails.leak_check(f"Subject: {reply.subject}\n\n{reply.body}", sensitive,
                                    allowed_text=self.state["input"]["message"])
        for f in res.findings:
            self.rec.event("guard", "guardrail", f"[{f.severity}] {f.message}", {"line": f.snippet})
            store.add_safety_event("leak_blocked", "high", f"Scope Guard reply: {f.message}", self.run_id, f.to_dict())
        self.state["results"]["reply_text"] = res.text
        self.state["results"]["leak_findings"] = [f.to_dict() for f in res.findings]
        self.rec.finish_step("guard", f"Redacted {len(res.findings)} line(s)." if res.findings else "Clean.")

    # ------------------------------------------------------------------ the whole run

    async def run(self) -> None:
        st = self.state
        st["status"] = "running"
        self.persist()
        try:
            clean = self.screen()
            split = await self.split(clean)
            if not split.asks:
                for k in ("matcher", "check", "estimator", "pricing", "reply", "guard"):
                    self.rec.skip_step(k, "No actionable asks in the message.")
                st["results"]["items"] = []
                st["status"] = "ready"
                return
            matches = await self.match(split)
            items = self.check(split, matches)
            est = await self.estimate(items)
            pricing = self.price(items, est)
            reply = await self.reply(items, pricing)
            self.guard(reply, pricing)
            st["status"] = "ready"
        except UsageLimitExceeded as exc:
            st["status"], st["error"] = "failed", f"Stopped by the per-run safety limit: {exc}"
            store.add_safety_event("run_limit_stop", "high", st["error"], self.run_id)
            self._fail_running()
        except ModelHTTPError as exc:
            if "content_filter" in str(exc.body):
                st["status"] = "blocked"
                st["error"] = ("The model provider's safety filter refused this message (it looks like a jailbreak attempt), "
                               "so nothing was processed. Review the message yourself.")
                store.add_safety_event("provider_content_filter", "high", st["error"], self.run_id)
            else:
                st["status"], st["error"] = "failed", f"ModelHTTPError {exc.status_code}: {exc.body}"
            self._fail_running()
        except Exception as exc:  # noqa: BLE001 - a failed run must still be saved and shown
            st["status"], st["error"] = "failed", f"{type(exc).__name__}: {exc}"
            self._fail_running()
        finally:
            self.persist()
            ACTIVE.pop(self.run_id, None)

    def _fail_running(self) -> None:
        for s in self.state["steps"].values():
            if s["status"] == "running":
                s["status"], s["summary"] = "failed", self.state["error"]
            elif s["status"] == "pending":
                s["status"] = "skipped"


def start_run(inp: dict[str, Any], sow: dict, client_ip: str, user: dict | None) -> str:
    run_id = uuid.uuid4().hex[:10]
    state = new_state(run_id, inp, sow, client_ip, user)
    run = ScopeRun(run_id, state, sow)
    ACTIVE[run_id] = state
    run.persist()
    task = asyncio.get_running_loop().create_task(run.run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return run_id


def get_state(run_id: str) -> dict | None:
    return ACTIVE.get(run_id) or store.get_run(run_id)
