"""Deal Room: rehearse the pricing call before a quote goes out.

A simulated client (built from the client's own email, with a private budget ceiling) and Empower's negotiator take
turns. Every offer goes through the referee (code), which prices it with the Deal Desk calculator and enforces the
discount cap and margin floor; the client only ever sees the referee's numbers. A coach then reads the transcript,
including the client's private thoughts, and writes the plan for the real call.

    client opens -> [negotiator -> referee (code) -> client] x up to 4 rounds -> coach
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded

from ...core import guardrails, store
from ...core.company import company
from ...core.config import MODEL_NAME, PROMPT_CANARY
from ...core.runner import RunRecorder
from . import referee
from .agents import LABELS, RoomDeps, client_agent, coach_agent, negotiator_agent
from .models import ClientTurn, CoachReport, Offer

MODULE_KEY = "deal_room"
MAX_ROUNDS = 4
ACTIVE: dict[str, dict[str, Any]] = {}
_TASKS: set[asyncio.Task] = set()

STYLES = {
    "friendly": ("Friendly", 1.30, "Collaborative and keen to work with Empower. You push back once or twice, mostly on price "
                                    "and timing, and you respond well to a sensible phased plan."),
    "balanced": ("Balanced", 1.15, "Professional and firm. You are comparing vendors and expect at least one meaningful "
                                   "concession before you sign."),
    "tough": ("Tough", 1.02, "A hard bargainer with a procurement mindset. You challenge every number, mention cheaper "
                             "competitors, ask for guarantees, and are willing to walk away."),
}


# With no stated budget the client's hidden ceiling is set against Empower's recommended price instead.
NO_BUDGET_CEILING = {"friendly": 0.99, "balanced": 0.94, "tough": 0.88}


def _money(cur: str, x: float) -> str:
    return f"{cur} {x:,.0f}"


def private_position(c, facts: dict, style: str) -> tuple[str, float]:
    """The client's hidden ceiling and priorities, derived from their own email (and the deal's price if no budget)."""
    spec, q = facts["spec"], facts["quote"]
    cur = q.currency
    stretch = STYLES[style][1]
    budget = spec.constraints.budget_max
    if budget and spec.constraints.budget_currency and spec.constraints.budget_currency.upper() != cur:
        budget = referee.calc.convert(c, budget, spec.constraints.budget_currency.upper(), cur)
    rec = next(o.price for o in q.options if o.model == q.recommended_model)
    if budget:
        ceiling = round(budget * stretch, -3)
        money = (f"Your stated budget tops out at {_money(cur, budget)}. In private you could stretch to about "
                 f"{_money(cur, ceiling)} if the offer clearly protects what matters most to you; above that you would "
                 f"have to go back to your board, which you want to avoid.")
    else:
        ceiling = round(rec * NO_BUDGET_CEILING[style], -3)
        money = (f"You did not state a budget, but you expected something around {_money(cur, ceiling)} and would need "
                 f"a strong reason to pay more.")
    musts = [f.name for f in spec.features if f.priority == "must"][:6]
    lines = [money,
             f"Your deadline: {spec.constraints.deadline or 'not fixed, but sooner is better'}.",
             "Must-haves for you: " + (", ".join(musts) or "the core of what you asked for") + ".",
             "You would accept a smaller first phase if it covers your must-haves and your deadline."]
    return "\n".join(f"- {x}" for x in lines), ceiling


def facts_text(c, facts: dict, deal: dict) -> str:
    spec, q, sch, est, p1 = facts["spec"], facts["quote"], facts["schedule"], facts["estimate"], facts["phase1"]
    r = deal["results"]
    review = r.get("review") or {}
    pol = c.policy
    lines = [
        f"Project: {spec.project_title} for {spec.client_name} ({spec.client_country}). Currency {q.currency}.",
        f"Client constraints: deadline {spec.constraints.deadline or 'none stated'}; budget {spec.constraints.budget_text or 'none stated'}.",
        f"Full scope: {est.total_hours:,.0f} h, go-live {sch.end_date} ({'meets' if sch.meets_deadline else 'misses' if sch.meets_deadline is False else 'no'} deadline), bottleneck {sch.bottleneck_role}.",
        f"Full scope list prices at the deal's {q.discount_pct:g}% discount: fixed {_money(q.currency, q.options[0].price)}, "
        f"T&M {_money(q.currency, q.options[1].price)}; recommended {q.recommended_model}. Margins: fixed {q.margin_pct_fixed}%, T&M {q.margin_pct_tm}%.",
        (f"Phase 1 option: {', '.join(p1['packages'])}; {p1['hours']:,.0f} h; go-live {p1['go_live']}; fixed "
         f"{_money(q.currency, p1['fixed_price'])}, T&M {_money(q.currency, p1['tm_price'])}; later: {', '.join(p1['later_packages'])}.")
        if p1 else "No Phase 1 option (every package is a must-have).",
        f"Policy: margin floor {pol['margin_floor_pct']}%, target {pol['target_margin_pct']}%; discounts over 5% need a Director; "
        f"maximum discount {pol['max_discount_pct']}%.",
        "Critic's verdict: " + str(review.get("verdict", "n/a")) + ". Top issues: " +
        "; ".join(i["finding"][:160] for i in (review.get("issues") or [])[:3]),
        "Pricing strategist's notes: " + "; ".join((r.get("pricing_decision") or {}).get("negotiation_notes", [])[:4]),
    ]
    return "\n".join(f"- {x}" for x in lines)


def new_state(run_id: str, deal: dict, style: str, user: dict, client_ip: str) -> dict[str, Any]:
    steps = {k: {"key": k, "label": LABELS[k][0], "kind": "code" if k == "referee" else "agent", "job": LABELS[k][1],
                 "status": "pending"} for k in ("client", "negotiator", "referee", "coach")}
    return {
        "id": run_id, "module": MODULE_KEY, "status": "running", "created_at": store.now_iso(),
        "title": f"Rehearsal ({STYLES[style][0].lower()} client): {deal['title']}", "model": MODEL_NAME,
        "input": {"deal_id": deal["id"], "style": style, "created_by": user.get("name", "")},
        "client_ip": client_ip, "steps": steps, "trace": [],
        "results": {"transcript": [], "outcome": None, "coach": None, "client_name": deal["results"]["spec"]["client_name"]},
        "error": None,
    }


class RoomRun:
    def __init__(self, run_id: str, state: dict, deal: dict) -> None:
        self.run_id, self.state, self.deal = run_id, state, deal
        self.c = company()
        self.facts = referee.deal_facts(deal)
        self.style = state["input"]["style"]
        self.private, self.ceiling = private_position(self.c, self.facts, self.style)
        self.state["results"]["client_ceiling"] = self.ceiling  # staff-only, shown after the rehearsal
        self.ftext = facts_text(self.c, self.facts, deal)
        self.deps = RoomDeps(company=self.c, facts=self.facts)
        self.rec = RunRecorder(run_id, MODULE_KEY, state, self.persist)
        screened = guardrails.screen_untrusted(deal["input"]["brief"])
        self.brief, _ = guardrails.redact_ai_directed_lines(screened.clean_text)
        q = self.facts["quote"]
        self.sensitive = self.c.sensitive_numbers() | {f"{q.internal_cost:,.0f}", f"{q.margin_pct_fixed}%", f"{q.margin_pct_tm}%"}
        self.agents = {"client": client_agent(self.private, STYLES[self.style][2]),
                       "negotiator": negotiator_agent(self.ftext), "coach": coach_agent(self.ftext)}

    def persist(self) -> None:
        store.save_run(self.run_id, MODULE_KEY, self.state["status"], self.state["title"], self.state,
                       self.state.get("client_ip", ""))

    def redact(self, report: dict) -> dict:
        """The coach's advice is shown to sales staff: no salaries or internal cost figures in it."""
        numbers = {n for n in self.sensitive if len(n.replace(",", "").rstrip("%")) >= 5}

        def clean(v):
            if isinstance(v, str):
                if PROMPT_CANARY in v or guardrails._leaks_number(v, numbers, set()):
                    store.add_safety_event("leak_blocked", "high", "Deal Room coach quoted an internal figure; redacted.", self.run_id)
                    return "[Redacted: internal figure]"
                return v
            return [clean(x) for x in v] if isinstance(v, list) else v
        return {k: clean(v) for k, v in report.items()}

    def say(self, entry: dict) -> None:
        self.state["results"]["transcript"].append(entry)
        self.persist()

    def client_view(self) -> str:
        """The conversation as the client sees it: their messages and Empower's messages with offer cards."""
        out = []
        for e in self.state["results"]["transcript"]:
            if e["speaker"] == "client":
                out.append(f"YOU: {e['text']}")
            elif e["speaker"] == "empower":
                out.append(f"EMPOWER: {e['text']}\n{e['card']}")
        return "\n\n".join(out)

    async def client_turn(self, rnd: int, opening: str | None = None) -> ClientTurn:
        self.rec.start_step("client", f"Client, round {rnd}")
        prompt = (guardrails.spotlight(self.brief, "client_request") + "\n\n" +
                  (opening or "Conversation so far:\n" + self.client_view() + "\n\nReply to Empower's latest offer."))
        turn: ClientTurn = await self.rec.run_agent("client", self.agents["client"], prompt, self.deps)
        self.say({"speaker": "client", "round": rnd, "text": turn.message, "stance": turn.stance,
                  "objections": turn.objections, "private": turn.private_thoughts})
        self.rec.finish_step("client", f"Round {rnd}: {turn.stance}" + (f" ({'; '.join(turn.objections[:2])})" if turn.objections else ""))
        return turn

    async def negotiator_turn(self, rnd: int) -> dict:
        self.rec.start_step("negotiator", f"Negotiator, round {rnd}")
        prompt = ("Conversation so far (the client's messages, and your offers with the referee's offer cards):\n\n"
                  + self.client_view() + f"\n\nMake your offer for round {rnd} of at most {MAX_ROUNDS}.")
        offer: Offer = await self.rec.run_agent("negotiator", self.agents["negotiator"], prompt, self.deps)
        self.rec.finish_step("negotiator", f"Round {rnd}: {offer.model}, {offer.scope}, {offer.discount_pct:g}% asked")

        self.rec.start_step("referee", f"Pricing round {rnd}")
        priced = referee.price_offer(self.c, self.facts, offer.model, offer.scope, offer.discount_pct)
        card = referee.offer_card(priced, self.facts)
        allowed = {f"{priced['price']:,.0f}", f"{priced['price']:.0f}"}
        text, scrubbed = referee.scrub_numbers(offer.message, allowed)
        leak = guardrails.leak_check(text, self.sensitive)
        if leak.findings:
            for f in leak.findings:
                store.add_safety_event("leak_blocked", "high", f"Deal Room negotiator: {f.message}", self.run_id, f.to_dict())
        if scrubbed:
            self.rec.event("referee", "guardrail", f"Removed {scrubbed} number(s) the negotiator typed itself; only the offer card states numbers.")
        entry = {"speaker": "empower", "round": rnd, "text": leak.text, "card": card, "offer": priced,
                 "concessions": offer.concessions, "reasoning": offer.internal_reasoning,
                 "scrubbed": scrubbed, "leak_redacted": bool(leak.findings)}
        self.say(entry)
        flag = "needs a Director" if priced["needs_director"] else "within policy"
        self.rec.finish_step("referee", f"{priced['currency']} {priced['price']:,.0f} ({priced['scope']}, {priced['model']}), "
                                        f"margin {priced['margin_pct']}%, {flag}")
        return entry

    async def run(self) -> None:
        st = self.state
        try:
            q = self.facts["quote"]
            rec_opt = next(o for o in q.options if o.model == q.recommended_model)
            first = referee.price_offer(self.c, self.facts, rec_opt.model, "full", q.discount_pct)
            opening_card = referee.offer_card(first, self.facts)
            self.say({"speaker": "empower", "round": 0, "text": "Thank you for your request. Our proposal is attached.",
                      "card": opening_card, "offer": first, "concessions": [], "reasoning": "The Deal Desk's recommended option.",
                      "scrubbed": 0, "leak_redacted": False})
            p1 = self.facts["phase1"]
            opening = ("Empower has sent you its proposal:\n" + opening_card +
                       (f"\nThey also mention a smaller first phase is possible ({', '.join(p1['packages'][:4])}), go-live {p1['go_live']}."
                        if p1 else "") + "\n\nGive your first reaction.")
            turn = await self.client_turn(0, opening)
            outcome = None
            for rnd in range(1, MAX_ROUNDS + 1):
                if turn.stance != "negotiating":
                    break
                await self.negotiator_turn(rnd)
                turn = await self.client_turn(rnd)
            outcome = {"accept": "deal", "walk_away": "no_deal"}.get(turn.stance, "no_agreement")
            offers = [e for e in st["results"]["transcript"] if e["speaker"] == "empower"]
            last = offers[-1]["offer"]
            st["results"]["outcome"] = {"result": outcome, "rounds": len(offers) - 1, "final_offer": last,
                                        "opening_price": offers[0]["offer"]["price"],
                                        "price_movement_pct": round(100 * (last["price"] / offers[0]["offer"]["price"] - 1), 1)}
            self.persist()

            self.rec.start_step("coach")
            full = "\n\n".join(
                (f"CLIENT (round {e['round']}, stance {e['stance']}): {e['text']}\n  [private thoughts: {e['private']}]"
                 if e["speaker"] == "client" else
                 f"EMPOWER (round {e['round']}): {e['text']}\n  {e['card']}\n  [negotiator's reasoning: {e['reasoning']}; "
                 f"concessions: {', '.join(e['concessions']) or 'none'}; margin {e['offer']['margin_pct']}%; "
                 f"{'needs Director' if e['offer']['needs_director'] else 'within policy'}]")
                for e in st["results"]["transcript"])
            prompt = (f"Rehearsal with a {STYLES[self.style][0].lower()} client. Result: {outcome}. "
                      f"The client's hidden ceiling was {_money(q.currency, self.ceiling)}.\n\nTranscript:\n\n{full}")
            report: CoachReport = await self.rec.run_agent("coach", self.agents["coach"], prompt, self.deps)
            st["results"]["coach"] = self.redact(report.model_dump())
            self.rec.finish_step("coach", report.headline)
            st["status"] = "ready"
        except UsageLimitExceeded as exc:
            st["status"], st["error"] = "failed", f"Stopped by the per-run safety limit: {exc}"
            store.add_safety_event("run_limit_stop", "high", st["error"], self.run_id)
        except ModelHTTPError as exc:
            st["status"] = "blocked" if guardrails.is_content_filter(exc) else "failed"
            st["error"] = ("The model provider's safety filter refused this rehearsal." if st["status"] == "blocked"
                           else f"ModelHTTPError {exc.status_code}: {exc.body}")
        except Exception as exc:  # noqa: BLE001 -- a failed run must still be saved and shown
            st["status"], st["error"] = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            for s in st["steps"].values():
                if s["status"] == "running":
                    s["status"] = "failed"
                elif s["status"] == "pending":
                    s["status"] = "skipped"
            self.persist()
            ACTIVE.pop(self.run_id, None)


def start(deal: dict, style: str, user: dict, client_ip: str) -> str:
    run_id = uuid.uuid4().hex[:10]
    state = new_state(run_id, deal, style, user, client_ip)
    run = RoomRun(run_id, state, deal)
    ACTIVE[run_id] = state
    run.persist()
    task = asyncio.get_running_loop().create_task(run.run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return run_id


def get_state(run_id: str) -> dict | None:
    return ACTIVE.get(run_id) or store.get_run(run_id)


def list_for_deal(deal_id: str) -> list[dict]:
    out = []
    for d in store.list_runs(MODULE_KEY, 200):
        if d["input"].get("deal_id") == deal_id:
            d = ACTIVE.get(d["id"]) or d
            o = d["results"].get("outcome") or {}
            out.append({"id": d["id"], "status": d["status"], "style": d["input"]["style"], "created_at": d["created_at"],
                        "created_by": d["input"].get("created_by"), "result": o.get("result"),
                        "final_price": (o.get("final_offer") or {}).get("price"), "currency": (o.get("final_offer") or {}).get("currency"),
                        "cost_usd": (d.get("usage") or {}).get("cost_usd")})
    return out
