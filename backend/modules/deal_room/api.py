"""HTTP routes for the Deal Room (directors and sales/delivery only)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...core import store
from ...core.auth import current_user, require_role
from ...core.llm import MissingAPIKey
from ...core.usage import BudgetExceeded, check_daily_budget, reprice_run
from ..deal_desk import pipeline as deal_pipeline
from ..deal_desk.api import deal_limiter
from . import pipeline

router = APIRouter(prefix="/api", tags=["deal_room"], dependencies=[Depends(require_role("director", "sales"))])
READY = ("ready", "approved", "rejected", "changes_requested")


class NewRehearsal(BaseModel):
    style: Literal["friendly", "balanced", "tough"] = "balanced"


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/deals/{deal_id}/rehearsals")
async def start(deal_id: str, body: NewRehearsal, request: Request, user: dict = Depends(current_user)) -> dict:
    deal = deal_pipeline.get_state(deal_id)
    if not deal:
        raise HTTPException(404, "No such deal.")
    if deal["status"] not in READY or not deal.get("results", {}).get("quote"):
        raise HTTPException(409, "The deal needs a finished quote before you can rehearse the call.")
    try:
        check_daily_budget()
    except BudgetExceeded as exc:
        store.add_safety_event("daily_budget_stop", "high", str(exc))
        raise HTTPException(429, str(exc)) from exc
    wait = deal_limiter.check(_ip(request))
    if wait:
        raise HTTPException(429, f"Too many AI runs from this computer. Try again in {wait // 60 + 1} minutes.")
    try:
        run_id = pipeline.start(deal, body.style, user, _ip(request))
        store.audit(user, "run.started", "rehearsal", run_id, f"Rehearsed {deal['title']} against a {body.style} client")
        return {"id": run_id}
    except MissingAPIKey as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/deals/{deal_id}/rehearsals")
def list_rehearsals(deal_id: str) -> list[dict]:
    return pipeline.list_for_deal(deal_id)


@router.get("/rehearsals/{run_id}")
def get_rehearsal(run_id: str) -> dict:
    d = pipeline.get_state(run_id)
    if not d or d.get("module") != pipeline.MODULE_KEY:
        raise HTTPException(404, "No such rehearsal.")
    d = reprice_run(d)
    d.pop("client_ip", None)
    return d
