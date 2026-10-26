"""HTTP routes for the Staffing module: the availability board and the Staffing Assistant."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core import store
from ...core.auth import current_user
from ...core.company import company
from ...core.config import CHATS_PER_HOUR_PER_CLIENT
from ...core.guardrails import RateLimiter
from ...core.llm import MissingAPIKey, api_key_present
from ...core.usage import BudgetExceeded, check_daily_budget, reprice
from . import availability as av
from .assistant import MODULE_KEY, ask

router = APIRouter(prefix="/api/staffing", tags=["staffing"], dependencies=[Depends(current_user)])
_limiter = RateLimiter(CHATS_PER_HOUR_PER_CLIENT, 3600)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@router.get("/board")
def board(weeks: int = 12) -> dict:
    c = company()
    weeks = max(4, min(weeks, 26))
    starts = av.week_starts(c, None, weeks)
    people = []
    for e in sorted(c.employees.values(), key=lambda e: (e.role, e.name)):
        alloc = av.weekly_allocation(c, e.emp_id, None, weeks)
        nxt = av.earliest_start(c, e.emp_id, 50, None, run_weeks=4)
        people.append({
            "emp_id": e.emp_id, "name": e.name, "title": e.title, "role": e.role, "level": e.level, "office": e.office,
            "skills": list(e.skills), "weekly": alloc, "free_now_pct": max(0, 100 - alloc[0]),
            "free_50_from": nxt.isoformat() if nxt else None,
            "assignments": av.current_work(c, e.emp_id, None, weeks),
        })
    roles = [{"role": r, "label": c.roles[r], **av.team_capacity(c, r, None, weeks)} for r in c.roles]
    bench = sum(1 for p in people if p["free_now_pct"] >= 100)
    return {
        "as_of": c.as_of.isoformat(),
        "weeks": [s.isoformat() for s in starts],
        "week_ends": [(s + timedelta(days=6)).isoformat() for s in starts],
        "people": people,
        "roles": roles,
        "summary": {"headcount": len(people), "on_bench_now": bench,
                    "avg_utilisation_now_pct": round(sum(min(100, p["weekly"][0]) for p in people) / max(1, len(people)))},
    }


@router.post("/ask")
async def ask_staffing(body: Question, request: Request) -> dict:
    ip = request.client.host if request.client else "unknown"
    if not api_key_present():
        raise HTTPException(503, "PORTKEY_API_KEY is not set. Put it in a .env file in this folder or the folder above it.")
    try:
        check_daily_budget()
    except BudgetExceeded as exc:
        store.add_safety_event("daily_budget_stop", "high", str(exc))
        raise HTTPException(429, str(exc)) from exc
    wait = _limiter.check(ip)
    if wait:
        store.add_safety_event("rate_limited", "warning", f"Staffing questions rate-limited for {ip}.")
        raise HTTPException(429, f"Too many questions from this computer. Try again in {wait // 60 + 1} minutes.")
    try:
        state = await ask(body.question.strip(), ip)
    except MissingAPIKey as exc:
        raise HTTPException(503, str(exc)) from exc
    state.pop("client_ip", None)
    return state


@router.get("/history")
def history() -> list[dict]:
    return [{"id": r["id"], "question": r["input"]["question"], "status": r["status"], "created_at": r["created_at"],
             "answer": (r.get("results") or {}).get("answer"), "usage": reprice(r.get("usage"))}
            for r in store.list_runs(MODULE_KEY, 20)]
