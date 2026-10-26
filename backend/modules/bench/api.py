"""HTTP routes for the Bench Optimizer. Directors and HR only: bench cost is built from salary data."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ...core import store
from ...core.auth import current_user, require_role
from ...core.company import company
from ...core.guardrails import RateLimiter
from ...core.llm import MissingAPIKey
from ...core.usage import BudgetExceeded, check_daily_budget, reprice, reprice_run
from . import pipeline

router = APIRouter(prefix="/api/bench", tags=["bench"], dependencies=[Depends(require_role("director", "hr"))])
_limiter = RateLimiter(6, 3600)  # bench plans per hour per IP


class NewRun(BaseModel):
    horizon_weeks: int = Field(default=12, ge=4, le=26)
    min_free_pct: int = Field(default=50, ge=25, le=100)


class Decision(BaseModel):
    action: Literal["approve", "reject"]
    note: str = Field(default="", max_length=2000)


@router.get("/forecast")
def forecast(weeks: int = Query(12, ge=4, le=26), min_free_pct: int = Query(50, ge=25, le=100)) -> dict:
    return pipeline.forecast_bundle(company(), weeks, min_free_pct)


@router.post("/runs")
async def start(body: NewRun, request: Request, user: dict = Depends(current_user)) -> dict:
    try:
        check_daily_budget()
    except BudgetExceeded as exc:
        store.add_safety_event("daily_budget_stop", "high", str(exc))
        raise HTTPException(429, str(exc)) from exc
    ip = request.client.host if request.client else "unknown"
    wait = _limiter.check(ip)
    if wait:
        store.add_safety_event("rate_limited", "warning", f"Bench plans rate-limited for {ip}.")
        raise HTTPException(429, f"Too many bench plans from this computer. Try again in {wait // 60 + 1} minutes.")
    try:
        run_id = pipeline.start_run(body.model_dump(), ip, user)
        store.audit(user, "run.started", "bench_plan", run_id, "Started a bench plan")
    except MissingAPIKey as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"id": run_id}


@router.get("/runs")
def runs() -> list[dict]:
    out = []
    for d in store.list_runs(pipeline.MODULE_KEY, 30):
        d = pipeline.ACTIVE.get(d["id"]) or d
        v = (d.get("results") or {}).get("value") or {}
        out.append({"id": d["id"], "title": d["title"], "status": d["status"], "created_at": d["created_at"],
                    "created_by": d.get("created_by"), "people_matched": v.get("people_matched"),
                    "covered_inr": v.get("bench_cost_covered_by_billable_inr"),
                    "cost_usd": (reprice(d.get("usage")) or {}).get("cost_usd"),
                    "decision": (d.get("decision") or {}).get("action")})
    return out


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    d = pipeline.get_state(run_id)
    if not d or d.get("module") != pipeline.MODULE_KEY:
        raise HTTPException(404, "No such bench plan.")
    d = reprice_run(d)
    d.pop("client_ip", None)
    return d


@router.post("/runs/{run_id}/decision")
def decide(run_id: str, body: Decision, user: dict = Depends(current_user)) -> dict:
    d = store.get_run(run_id)
    if not d or d.get("module") != pipeline.MODULE_KEY:
        raise HTTPException(404, "No such bench plan.")
    if d["status"] not in ("ready", "approved", "rejected"):
        raise HTTPException(409, "This plan is not ready for a decision yet.")
    d["decision"] = {"action": body.action, "note": body.note.strip(), "approver": user["name"], "role": user["role"],
                     "at": store.now_iso()}
    d["status"] = "approved" if body.action == "approve" else "rejected"
    store.save_run(run_id, pipeline.MODULE_KEY, d["status"], d["title"], d)
    store.audit(user, f"decision.{body.action}", "bench_plan", run_id, f"{d['title']}: {d['status'].replace('_', ' ')}", {"note": body.note.strip()})
    return {"ok": True, "status": d["status"]}
