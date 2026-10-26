"""HTTP routes for the Appraisal & Hike Planner. HR and directors only: this module shows pay."""

from __future__ import annotations

from statistics import mean
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core import store
from ...core.auth import current_user, require_role
from ...core.guardrails import RateLimiter
from ...core.llm import MissingAPIKey
from ...core.usage import BudgetExceeded, check_daily_budget, reprice, reprice_run
from . import pipeline
from .data import appraisal_data

router = APIRouter(prefix="/api/appraisals", tags=["appraisals"], dependencies=[Depends(require_role("hr", "director"))])
_limiter = RateLimiter(6, 3600)


class NewCycle(BaseModel):
    pool_pct: float = Field(default=9.0, ge=2.0, le=20.0)
    note: str = Field(default="", max_length=1500)


class Decision(BaseModel):
    action: Literal["approve", "reject", "request_changes"]
    note: str = Field(default="", max_length=2000)


@router.get("/overview")
def overview() -> dict:
    d = appraisal_data()
    ps = list(d.people.values())
    return {
        "cycle": d.policy.get("cycle"), "effective_date": d.policy.get("effective_date"),
        "headcount": len(ps), "payroll": d.payroll, "default_pool_pct": d.policy["pool_pct_of_payroll"],
        "ratings": {str(r): sum(1 for p in ps if p.rating == r) for r in range(1, 6)},
        "promotions_recommended": sum(1 for p in ps if p.promotion_recommended),
        "retention_risk": {k: sum(1 for p in ps if p.retention_risk == k) for k in ("high", "medium", "low")},
        "offices": [{"office": o, "people": sum(1 for p in ps if p.office == o),
                     "avg_compa_ratio": round(mean(p.compa_ratio for p in ps if p.office == o), 3)} for o in sorted({p.office for p in ps})],
        "managers": [{"emp_id": m, "name": n, "team_size": len(d.team(m))} for m, n in d.managers.items()],
        "policy": {k: d.policy[k] for k in ("guideline_hike_pct", "promotion_addon_pct", "min_hike_pct", "max_hike_pct",
                                             "strategy_bounds", "default_strategy")},
        "agents": [{"key": k, "label": label, "kind": kind, "job": job} for k, label, kind, job in pipeline.STEP_ORDER],
    }


@router.post("/runs")
async def start(body: NewCycle, request: Request, user: dict = Depends(current_user)) -> dict:
    try:
        check_daily_budget()
    except BudgetExceeded as exc:
        store.add_safety_event("daily_budget_stop", "high", str(exc))
        raise HTTPException(429, str(exc)) from exc
    ip = request.client.host if request.client else "unknown"
    wait = _limiter.check(ip)
    if wait:
        store.add_safety_event("rate_limited", "warning", f"Appraisal runs rate-limited for {ip}.")
        raise HTTPException(429, f"Too many appraisal runs from this computer. Try again in {wait // 60 + 1} minutes.")
    try:
        run_id = pipeline.start_run({"pool_pct": body.pool_pct, "note": body.note.strip()}, ip, user)
        store.audit(user, "run.started", "hike_cycle", run_id, "Started a hike cycle")
    except MissingAPIKey as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"id": run_id}


@router.get("/runs")
def runs() -> list[dict]:
    out = []
    for d in store.list_runs(pipeline.MODULE_KEY, 50):
        d = pipeline.ACTIVE.get(d["id"]) or d
        r = d.get("results", {})
        sm = r.get("summary") or {}
        rev = (r.get("reviews") or [{}])[-1]
        out.append({"id": d["id"], "title": d["title"], "status": d["status"], "created_at": d["created_at"],
                    "created_by": d.get("created_by"), "pool_pct": d["input"]["pool_pct"], "avg_hike_pct": sm.get("avg_hike_pct"),
                    "verdict": rev.get("verdict"), "adjustments": len(r.get("adjustments_applied", [])),
                    "cost_usd": (reprice(d.get("usage")) or {}).get("cost_usd"), "decision": (d.get("decision") or {}).get("action")})
    return out


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    d = pipeline.get_state(run_id)
    if not d or d.get("module") != pipeline.MODULE_KEY:
        raise HTTPException(404, "No such appraisal run.")
    d = reprice_run(d)
    d.pop("client_ip", None)
    return d


@router.post("/runs/{run_id}/decision")
def decide(run_id: str, body: Decision, user: dict = Depends(current_user)) -> dict:
    d = store.get_run(run_id)
    if not d or d.get("module") != pipeline.MODULE_KEY:
        raise HTTPException(404, "No such appraisal run.")
    if d["status"] not in ("ready", "approved", "rejected", "changes_requested"):
        raise HTTPException(409, "This run is not ready for a decision yet.")
    if body.action == "approve" and d.get("results", {}).get("privacy_findings"):
        if len(body.note.strip()) < 10:
            raise HTTPException(422, "The privacy check removed lines from manager briefs. Add a note (10+ characters) "
                                     "confirming you reviewed them before approving.")
    d["decision"] = {"action": body.action, "note": body.note.strip(), "approver": user["name"], "role": user["role"],
                     "at": store.now_iso()}
    d["status"] = {"approve": "approved", "reject": "rejected", "request_changes": "changes_requested"}[body.action]
    store.save_run(run_id, pipeline.MODULE_KEY, d["status"], d["title"], d)
    store.audit(user, f"decision.{body.action}", "hike_cycle", run_id, f"{d['title']}: {d['status'].replace('_', ' ')}", {"note": body.note.strip()})
    return {"ok": True, "status": d["status"]}
