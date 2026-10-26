"""HTTP routes for the Deal Desk."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core import store
from ...core.auth import current_user, require_role
from ...core.config import MAX_BRIEF_CHARS, MIN_BRIEF_CHARS, RUNS_PER_HOUR_PER_CLIENT, SAMPLE_BRIEFS
from ...core.guardrails import RateLimiter
from ...core.llm import MissingAPIKey
from ...core.usage import BudgetExceeded, check_daily_budget, reprice, reprice_run
from . import pipeline
from .scenarios import Scenario
from .scenarios import compute as compute_scenario
from ...core.company import company

router = APIRouter(prefix="/api/deals", tags=["deal_desk"], dependencies=[Depends(require_role("director", "sales"))])
deal_limiter = RateLimiter(RUNS_PER_HOUR_PER_CLIENT, 3600)  # shared with the Copilot's start_deal


class NewDeal(BaseModel):
    brief: str = Field(min_length=1, max_length=MAX_BRIEF_CHARS * 2)
    client_name: str = Field(default="", max_length=120)
    client_country: str = Field(default="", max_length=40)
    currency: Literal["USD", "EUR", "GBP"] = "USD"
    desired_start: str = Field(default="", max_length=20)


class Decision(BaseModel):
    action: Literal["approve", "reject", "request_changes"]
    note: str = Field(default="", max_length=2000)
    # Optional evidence from the reviewer, for measuring impact: how long a quote like this takes by hand today,
    # and how good the draft was.
    manual_hours: float | None = Field(default=None, ge=0, le=500)
    quality: int | None = Field(default=None, ge=1, le=5)


def run_minutes(d: dict) -> float:
    ends = [s.get("ended_at") or 0 for s in d.get("steps", {}).values()]
    return round(max(ends or [0]) / 60, 1)


def feedback_summary() -> dict:
    rows = []
    for d in store.list_runs(pipeline.MODULE_KEY, 500):
        dec = d.get("decision") or {}
        if dec.get("manual_hours") is not None or dec.get("quality") is not None:
            rows.append({"deal_id": d["id"], "title": d["title"], "approver": dec.get("approver"), "action": dec.get("action"),
                         "manual_hours": dec.get("manual_hours"), "quality": dec.get("quality"),
                         "app_minutes": dec.get("app_minutes", run_minutes(d)), "note": dec.get("note")})
    hours = [r["manual_hours"] for r in rows if r["manual_hours"] is not None]
    quality = [r["quality"] for r in rows if r["quality"] is not None]
    app_h = sum((r["app_minutes"] or 0) / 60 for r in rows if r["manual_hours"] is not None)
    return {"reviews": len(rows), "avg_quality": round(sum(quality) / len(quality), 2) if quality else None,
            "manual_hours_total": round(sum(hours), 1), "app_hours_total": round(app_h, 2),
            "hours_saved_total": round(sum(hours) - app_h, 1) if hours else None, "rows": rows[:50]}


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/samples")
def samples() -> list[dict]:
    return json.loads(SAMPLE_BRIEFS.read_text(encoding="utf-8"))


@router.post("")
async def create_deal(body: NewDeal, request: Request, user: dict = Depends(current_user)) -> dict:
    brief = body.brief.strip()
    if len(brief) < MIN_BRIEF_CHARS:
        raise HTTPException(422, f"Please paste the client's request (at least {MIN_BRIEF_CHARS} characters).")
    if len(brief) > MAX_BRIEF_CHARS:
        store.add_safety_event("input_too_long", "warning", f"Brief of {len(brief):,} chars refused (limit {MAX_BRIEF_CHARS:,}).")
        raise HTTPException(413, f"That document is {len(brief):,} characters; the limit is {MAX_BRIEF_CHARS:,}. "
                                 "Paste the relevant part (scope, constraints, budget, deadline).")
    try:
        check_daily_budget()
    except BudgetExceeded as exc:
        store.add_safety_event("daily_budget_stop", "high", str(exc))
        raise HTTPException(429, str(exc)) from exc
    wait = deal_limiter.check(_ip(request))
    if wait:
        store.add_safety_event("rate_limited", "warning", f"Deal runs rate-limited for {_ip(request)}.")
        raise HTTPException(429, f"Too many deal runs from this computer. Try again in {wait // 60 + 1} minutes.")
    inp = body.model_dump()
    inp["brief"] = brief
    inp["created_by"] = user["name"]
    try:
        run_id = pipeline.start_run(inp, _ip(request))
    except MissingAPIKey as exc:
        raise HTTPException(503, str(exc)) from exc
    store.audit(user, "run.started", "deal", run_id, f"Started the Deal Desk on a {len(brief):,}-character client request")
    return {"id": run_id}


@router.get("")
def list_deals() -> list[dict]:
    out = []
    for d in store.list_runs(pipeline.MODULE_KEY):
        live = pipeline.ACTIVE.get(d["id"])
        d = live or d
        q = d.get("results", {}).get("quote") or {}
        opt = next((o for o in q.get("options", []) if o["model"] == q.get("recommended_model")), None)
        out.append({
            "id": d["id"], "title": d["title"], "status": d["status"], "created_at": d["created_at"],
            "client_name": d["input"].get("client_name"), "currency": d["input"].get("currency"),
            "price": opt["price"] if opt else None, "model": q.get("recommended_model"),
            "margin_pct": q.get("margin_pct_fixed") if q.get("recommended_model") == "fixed" else q.get("margin_pct_tm"),
            "hours": (d.get("results", {}).get("estimate") or {}).get("total_hours"),
            "verdict": (d.get("results", {}).get("review") or {}).get("verdict"),
            "cost_usd": (reprice(d.get("usage")) or {}).get("cost_usd"),
            "decision": (d.get("decision") or {}).get("action"),
            "flags": len(d.get("screen", {}).get("findings", [])) + len(d.get("results", {}).get("leak_findings", [])),
            "demo": bool(d.get("demo")),
            "created_by": d["input"].get("created_by") or ("example" if d.get("demo") else ""),
            "via": d["input"].get("via", "form"),
        })
    return out


@router.get("/{run_id}")
def get_deal(run_id: str) -> dict:
    d = pipeline.get_state(run_id)
    if not d:
        raise HTTPException(404, "No such deal.")
    d = reprice_run(d)
    d.pop("client_ip", None)
    return d


@router.post("/{run_id}/decision")
def decide(run_id: str, body: Decision, user: dict = Depends(current_user)) -> dict:
    d = store.get_run(run_id)
    if not d:
        raise HTTPException(404, "No such deal.")
    if d["status"] not in ("ready", "approved", "rejected", "changes_requested"):
        raise HTTPException(409, "This deal is not ready for a decision yet.")
    quote = d.get("results", {}).get("quote") or {}
    if body.action == "approve" and quote.get("needs_approval") and user["role"] != "director":
        raise HTTPException(403, "This deal is outside pricing policy (" + "; ".join(quote.get("approval_reasons", []))
                                 + "). Only a Director can approve it. You can request changes instead.")
    if body.action == "approve" and quote.get("needs_approval") and len(body.note.strip()) < 10:
        raise HTTPException(422, "This deal is outside pricing policy: " + "; ".join(quote.get("approval_reasons", []))
                                 + " Add a note (10+ characters) explaining why you approve it anyway.")
    if body.action == "approve" and d.get("results", {}).get("leak_findings"):
        raise HTTPException(422, "The leak guard redacted internal data from this proposal. Review the redactions and "
                                 "re-run the deal before approving.")
    d["decision"] = {"action": body.action, "note": body.note.strip(), "approver": user["name"], "approver_role": user["role_label"],
                     "at": store.now_iso(), "manual_hours": body.manual_hours, "quality": body.quality,
                     "app_minutes": run_minutes(d)}
    d["status"] = {"approve": "approved", "reject": "rejected", "request_changes": "changes_requested"}[body.action]
    store.save_run(run_id, pipeline.MODULE_KEY, d["status"], d["title"], d)
    store.audit(user, f"decision.{body.action}", "deal", run_id, f"{d['title']}: {body.action.replace('_', ' ')}"
                + (" (outside pricing policy)" if quote.get("needs_approval") else ""), {"note": body.note.strip()})
    return {"ok": True, "status": d["status"]}


# ---------------------------------------------------------------------------- scenarios (what-if, then apply)


def _ready_deal(run_id: str) -> dict:
    d = store.get_run(run_id)
    if not d or d.get("module") != pipeline.MODULE_KEY:
        raise HTTPException(404, "No such deal.")
    if not (d.get("results") or {}).get("quote") or d["status"] not in ("ready", "changes_requested", "approved", "rejected"):
        raise HTTPException(409, "The deal needs a finished quote first.")
    return d


@router.post("/{run_id}/scenario")
def scenario(run_id: str, body: Scenario) -> dict:
    out = compute_scenario(company(), _ready_deal(run_id), body)
    out.pop("_apply", None)
    return out


@router.post("/{run_id}/scenarios")
def save_scenario(run_id: str, body: Scenario, user: dict = Depends(current_user)) -> dict:
    d = _ready_deal(run_id)
    out = compute_scenario(company(), d, body)
    out.pop("_apply", None)
    out.update({"by": user["name"], "at": store.now_iso(), "name": body.name or f"Scenario {len(d['results'].get('scenarios', [])) + 1}"})
    d["results"].setdefault("scenarios", []).append(out)
    store.save_run(run_id, pipeline.MODULE_KEY, d["status"], d["title"], d)
    store.audit(user, "scenario.saved", "deal", run_id, f"Saved scenario '{out['name']}'", body.model_dump())
    return {"ok": True, "scenarios": d["results"]["scenarios"]}


@router.post("/{run_id}/scenarios/apply")
async def apply_scenario(run_id: str, body: Scenario, request: Request, user: dict = Depends(current_user)) -> dict:
    d = _ready_deal(run_id)
    if d["status"] == "approved":
        raise HTTPException(409, "This deal is approved; start a new deal to change it.")
    if run_id in pipeline.ACTIVE:
        raise HTTPException(409, "This deal is already being updated.")
    try:
        check_daily_budget()
    except BudgetExceeded as exc:
        raise HTTPException(429, str(exc)) from exc
    out = compute_scenario(company(), d, body)
    r = d["results"]
    if "baseline" not in r:  # keep what the agents first produced, for comparison and audit
        r["baseline"] = {k: r.get(k) for k in ("estimate", "schedule", "quote", "phase1", "pricing_decision")}
    ap = out["_apply"]
    r["estimate_draft"], r["estimate"], r["staffing_draft"], r["schedule"] = ap["estimate_draft"], ap["estimate"], ap["staffing_draft"], ap["schedule"]
    r["pricing_decision"] = {**r["pricing_decision"], "recommended_model": ap["model"], "discount_pct": ap["discount_pct"]}
    r["applied_scenario"] = {**body.model_dump(), "by": user["name"], "at": store.now_iso()}
    r["proposal_stale"] = True
    d["decision"] = None
    d["status"] = "ready"
    store.save_run(run_id, pipeline.MODULE_KEY, d["status"], d["title"], d)
    store.audit(user, "scenario.applied", "deal", run_id, "Applied a scenario; re-running the Deal Critic and the Proposal Writer",
                body.model_dump())
    try:
        pipeline.start_rerun(run_id)
    except MissingAPIKey as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"ok": True}
