"""HTTP routes for the Scope-Creep Guard (directors and sales/delivery only)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core import store
from ...core.auth import require_role
from ...core.company import company
from ...core.guardrails import RateLimiter
from ...core.llm import MissingAPIKey, api_key_present
from ...core.usage import BudgetExceeded, check_daily_budget, reprice, reprice_run
from ..deal_desk import pipeline as deal_pipeline
from . import calculators as calc
from . import data
from . import pipeline

ROLES = ("director", "sales")
router = APIRouter(prefix="/api/scope", tags=["scope_guard"], dependencies=[Depends(require_role(*ROLES))])
_limiter = RateLimiter(20, 3600)  # analyses per hour per IP
MAX_MESSAGE_CHARS = 20_000


class Analyse(BaseModel):
    sow_id: str = Field(min_length=3, max_length=40)
    message: str | None = Field(default=None, max_length=MAX_MESSAGE_CHARS * 2)
    subject: str | None = Field(default=None, max_length=200)
    attachment_id: str | None = Field(default=None, max_length=20)
    sample_id: str | None = Field(default=None, max_length=10)


class Decision(BaseModel):
    action: Literal["approve", "reject", "clarify"]
    absorb_ask_ids: list[str] = Field(default_factory=list, max_length=50)
    note: str = Field(default="", max_length=2000)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------- SOWs and samples


@router.get("/sows")
def list_sows() -> list[dict]:
    return [data.sow_summary(s) for s in data.all_sows().values()]


@router.get("/sows/{sow_id}")
def get_sow(sow_id: str) -> dict:
    s = data.get_sow(sow_id)
    if not s:
        raise HTTPException(404, "No such SOW.")
    return s


@router.post("/sows/from-deal/{deal_id}")
def sow_from_deal(deal_id: str) -> dict:
    d = deal_pipeline.get_state(deal_id)
    if not d:
        raise HTTPException(404, "No such deal.")
    if d.get("status") not in ("ready", "approved", "changes_requested"):
        raise HTTPException(409, "The deal must be finished (ready or approved) before it can become an SOW.")
    try:
        sow = data.sow_from_deal(d, company())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    store.save_run(sow["sow_id"], data.SOW_MODULE, "active", f"{sow['client']}: {sow['project_name']}", sow)
    return data.sow_summary(sow)


@router.get("/samples")
def samples(sow_id: str | None = None) -> list[dict]:
    return [m for m in data.sample_messages() if not sow_id or m["sow_id"] == sow_id]


# ---------------------------------------------------------------------------- analyses


@router.post("/analyses")
async def analyse(body: Analyse, request: Request, user: dict = Depends(require_role(*ROLES))) -> dict:
    sow = data.get_sow(body.sow_id)
    if not sow:
        raise HTTPException(404, "No such SOW.")
    subject, message, source = body.subject, body.message, "text"
    if body.sample_id:
        m = next((x for x in data.sample_messages() if x["id"] == body.sample_id), None)
        if not m:
            raise HTTPException(404, "No such sample message.")
        subject, message, source = m["subject"], m["text"], f"sample {m['id']} ({m['channel']} from {m['from']})"
    elif body.attachment_id:
        att = store.get_attachment(body.attachment_id)
        if not att:
            raise HTTPException(404, "Attachment not found; upload the file again.")
        message, source = att["text"], f"file {att['name']}"
        subject = subject or att["name"]
    message = (message or "").strip()
    if len(message) < 10:
        raise HTTPException(422, "Paste the client's message (at least 10 characters), pick a sample or upload a file.")
    if len(message) > MAX_MESSAGE_CHARS:
        store.add_safety_event("input_too_long", "warning", f"Scope Guard message of {len(message):,} chars refused.")
        raise HTTPException(413, f"The message is {len(message):,} characters; the limit is {MAX_MESSAGE_CHARS:,}.")
    if not api_key_present():
        raise HTTPException(503, "PORTKEY_API_KEY is not set. Put it in a .env file in this folder or the folder above it.")
    try:
        check_daily_budget()
    except BudgetExceeded as exc:
        store.add_safety_event("daily_budget_stop", "high", str(exc))
        raise HTTPException(429, str(exc)) from exc
    wait = _limiter.check(_ip(request))
    if wait:
        store.add_safety_event("rate_limited", "warning", f"Scope Guard rate-limited for {_ip(request)}.")
        raise HTTPException(429, f"Too many analyses from this computer. Try again in {wait // 60 + 1} minutes.")
    inp = {"sow_id": sow["sow_id"], "subject": subject, "message": message, "source": source}
    try:
        run_id = pipeline.start_run(inp, sow, _ip(request), user)
        store.audit(user, "run.started", "scope_check", run_id, f"Checked a client message against {sow['sow_id']}")
    except MissingAPIKey as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"id": run_id}


@router.get("/analyses")
def list_analyses(sow_id: str | None = None) -> list[dict]:
    out = []
    for r in store.list_runs(pipeline.MODULE_KEY, 200):
        r = pipeline.ACTIVE.get(r["id"]) or r
        if sow_id and r["input"].get("sow_id") != sow_id:
            continue
        res = r.get("results") or {}
        p = res.get("pricing") or {}
        out.append({
            "id": r["id"], "title": r["title"], "status": r["status"], "created_at": r["created_at"],
            "sow_id": r["input"].get("sow_id"), "subject": r["input"].get("subject"),
            "asks": len(res.get("items") or []), "counts": p.get("counts"),
            "cr_total": p.get("total_price"), "currency": p.get("currency"),
            "decision": (r.get("decision") or {}).get("action"),
            "cost_usd": (reprice(r.get("usage")) or {}).get("cost_usd"),
            "flags": len((r.get("screen") or {}).get("findings", [])) + len(res.get("leak_findings") or []),
        })
    return out


@router.get("/analyses/{run_id}")
def get_analysis(run_id: str) -> dict:
    r = pipeline.get_state(run_id)
    if not r or r.get("module") != pipeline.MODULE_KEY:
        raise HTTPException(404, "No such analysis.")
    r = reprice_run(r)
    r.pop("client_ip", None)
    return r


@router.post("/analyses/{run_id}/decision")
def decide(run_id: str, body: Decision, user: dict = Depends(require_role(*ROLES))) -> dict:
    r = store.get_run(run_id)
    if not r or r.get("module") != pipeline.MODULE_KEY:
        raise HTTPException(404, "No such analysis.")
    if r["status"] not in ("ready", "approved", "rejected", "needs_clarification"):
        raise HTTPException(409, "This analysis is not ready for a decision yet.")
    oos = {p["ask_id"] for p in ((r.get("results") or {}).get("pricing") or {}).get("items", [])}
    unknown = [a for a in body.absorb_ask_ids if a not in oos]
    if unknown:
        raise HTTPException(422, f"Only out-of-scope asks can be absorbed; not: {', '.join(unknown)}.")
    if body.action == "clarify" and len(body.note.strip()) < 10:
        raise HTTPException(422, "Write the question for the client (10+ characters) when you ask for clarification.")
    if body.action == "approve" and (r.get("results") or {}).get("leak_findings"):
        raise HTTPException(422, "The leak guard redacted internal data from the reply. Re-run before approving.")
    r["decision"] = {"action": body.action, "absorb_ask_ids": body.absorb_ask_ids, "note": body.note.strip(),
                     "approver": user["name"], "approver_role": user["role"], "at": store.now_iso()}
    r["status"] = {"approve": "approved", "reject": "rejected", "clarify": "needs_clarification"}[body.action]
    store.save_run(run_id, pipeline.MODULE_KEY, r["status"], r["title"], r)
    store.audit(user, f"decision.{body.action}", "scope_check", run_id, f"{r['title']}: {r['status'].replace('_', ' ')}",
                {"absorbed": body.absorb_ask_ids, "note": body.note.strip()})
    return {"ok": True, "status": r["status"]}


@router.get("/ledger")
def get_ledger() -> dict:
    return calc.ledger(store.list_runs(pipeline.MODULE_KEY, 1000), data.all_sows())
