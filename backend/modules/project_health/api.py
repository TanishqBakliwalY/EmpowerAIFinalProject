"""HTTP routes for Project Health (directors and sales/delivery)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core import store
from ...core.auth import current_user, require_role
from ...core.company import company
from ...core.llm import MissingAPIKey
from ...core.usage import BudgetExceeded, check_daily_budget, reprice_run
from ..deal_desk.api import deal_limiter
from . import health, pipeline

router = APIRouter(prefix="/api/projects", tags=["project_health"], dependencies=[Depends(require_role("director", "sales"))])


class NewReview(BaseModel):
    codes: list[str] = Field(default_factory=list, max_length=12)


class Decision(BaseModel):
    action: Literal["approve", "reject"]
    note: str = Field(default="", max_length=2000)


@router.get("/health")
def list_health() -> dict:
    t = health.tracker()
    reviews = pipeline.latest_reviews()
    rows = health.all_health()
    for r in rows:
        r["review"] = reviews.get(r["code"])
    return {"as_of": company().as_of.isoformat(), "synthetic": t.get("synthetic", True), "note": t.get("note"), "projects": rows}


@router.get("/health/{code}")
def project(code: str) -> dict:
    p = next((x for x in health.projects() if x["code"] == code), None)
    if not p:
        raise HTTPException(404, "No such project.")
    r = health.assess(company(), p)
    r["team"] = health.team_for(company(), code)
    r["review"] = pipeline.latest_reviews().get(code)
    r["audit"] = sorted(store.list_audit(50, entity_id=code) + store.list_audit(50, entity_id=f"risk:{code}"), key=lambda e: e["id"], reverse=True)
    return r


@router.post("/reviews")
async def start_review(body: NewReview, request: Request, user: dict = Depends(current_user)) -> dict:
    try:
        check_daily_budget()
    except BudgetExceeded as exc:
        raise HTTPException(429, str(exc)) from exc
    ip = request.client.host if request.client else "unknown"
    if deal_limiter.check(ip):
        raise HTTPException(429, "Too many AI runs from this computer. Try again later.")
    try:
        run_id = pipeline.start(body.codes, user, ip)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except MissingAPIKey as exc:
        raise HTTPException(503, str(exc)) from exc
    store.audit(user, "run.started", "delivery_review", run_id, "Started a delivery risk review")
    return {"id": run_id}


@router.get("/reviews")
def list_reviews() -> list[dict]:
    return [{"id": r["id"], "status": r["status"], "title": r["title"], "created_at": r["created_at"],
             "projects": r["input"]["projects"], "cost_usd": (r.get("usage") or {}).get("cost_usd")}
            for r in store.list_runs(pipeline.MODULE_KEY, 50)]


@router.get("/reviews/{run_id}")
def get_review(run_id: str) -> dict:
    d = pipeline.get_state(run_id)
    if not d or d.get("module") != pipeline.MODULE_KEY:
        raise HTTPException(404, "No such review.")
    d = reprice_run(d)
    d.pop("client_ip", None)
    return d


@router.post("/reviews/{run_id}/decision")
def decide(run_id: str, body: Decision, user: dict = Depends(current_user)) -> dict:
    d = store.get_run(run_id)
    if not d or d.get("module") != pipeline.MODULE_KEY:
        raise HTTPException(404, "No such review.")
    if d["status"] not in ("ready", "approved", "rejected"):
        raise HTTPException(409, "This review is not finished yet.")
    d["decision"] = {"action": body.action, "note": body.note.strip(), "approver": user["name"], "role": user["role"],
                     "at": store.now_iso()}
    d["status"] = "approved" if body.action == "approve" else "rejected"
    store.save_run(run_id, pipeline.MODULE_KEY, d["status"], d["title"], d)
    store.audit(user, f"decision.{body.action}", "delivery_review", run_id,
                f"Mitigation plan {d['status']} for {', '.join(d['input']['projects'])}", {"note": body.note.strip()})
    return {"ok": True, "status": d["status"]}
