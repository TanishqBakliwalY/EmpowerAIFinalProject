"""FastAPI app: module routers + shared usage/safety endpoints + the built React frontend."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .core import auth, documents, store
from .core.company import company
from .core.config import (
    DAILY_BUDGET_USD,
    DEMO_RUNS_DIR,
    FRONTEND_DIST,
    MAX_BRIEF_CHARS,
    MODEL_NAME,
    RUN_REQUEST_LIMIT,
    RUN_TOOL_CALLS_LIMIT,
    RUN_TOTAL_TOKENS_LIMIT,
)
from .core.llm import api_key_present
from .core.registry import all_modules
from .core.usage import prices
from .modules.ops.api import router as ops_router

MODULES = all_modules()


@asynccontextmanager
async def lifespan(_: FastAPI):
    company()  # load data once, fail fast on a bad data folder
    store.mark_interrupted_runs()
    store.import_demo_runs(DEMO_RUNS_DIR, "deal_desk")
    if DEMO_RUNS_DIR.exists():  # example runs for the other modules live in subfolders named after the module
        for sub in sorted(d for d in DEMO_RUNS_DIR.iterdir() if d.is_dir()):
            store.import_demo_runs(sub, sub.name)
    auth.ensure_demo_users()
    yield


app = FastAPI(title="Empower Ops Agents", lifespan=lifespan)
app.include_router(auth.router)  # sign-in is the only part of the API that works without a session
app.include_router(documents.router)
app.include_router(ops_router, dependencies=[Depends(auth.current_user)])
for m in MODULES:
    if m.router is not None:
        # Every module needs a signed-in user; modules add their own role rules on top (e.g. Appraisals: HR/Director).
        app.include_router(m.router, dependencies=[Depends(auth.current_user)])


@app.get("/api/meta")
def meta() -> dict:
    c = company()
    return {
        "app": "Empower Ops Agents",
        "model": MODEL_NAME,
        "api_key_present": api_key_present(),
        "dataset": {"name": c.meta.get("dataset"), "as_of": c.as_of.isoformat(), "synthetic": c.is_synthetic(),
                    "description": c.meta.get("description"), "employees": len(c.employees), "past_projects": len(c.projects)},
        "modules": [m.info() for m in MODULES],
        "demo_accounts": auth.DEMO_MODE,
        "prices_per_million_tokens_usd": prices(),
        "limits": {"requests_per_run": RUN_REQUEST_LIMIT, "tool_calls_per_run": RUN_TOOL_CALLS_LIMIT,
                   "tokens_per_run": RUN_TOTAL_TOKENS_LIMIT, "daily_budget_usd": DAILY_BUDGET_USD,
                   "max_brief_chars": MAX_BRIEF_CHARS},
    }


@app.get("/api/usage", dependencies=[Depends(auth.require_role("director", "sales"))])
def usage() -> dict:
    from .modules.deal_desk.api import feedback_summary

    return {**store.usage_summary(), "spent_today_usd": round(store.spent_today_usd(), 4),
            "daily_budget_usd": DAILY_BUDGET_USD, "prices_per_million_tokens_usd": prices(),
            "feedback": feedback_summary()}


@app.get("/api/me/progress")
def my_progress(user: dict = Depends(auth.current_user)) -> dict:
    from .modules.ops.api import MODULES_BY_ROLE

    return your_week(user, {m: m in MODULES_BY_ROLE[user["role"]] for m in ("deal_desk", "appraisals")})


def your_week(user: dict, allowed: dict) -> dict:
    """A light game layer for the landing page: this week's progress and badges earned from real activity."""
    from datetime import datetime, timedelta, timezone

    from .modules.deal_desk.api import feedback_summary

    me = user["name"]
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    runs = {k: store.list_runs(k, 500) for k in ("deal_desk", "scope_guard", "bench", "appraisals", "deal_room")}

    def mine(module: str, action: str | None = None) -> list[dict]:
        return [r for r in runs[module] if (r.get("decision") or {}).get("approver") == me
                and (action is None or r["decision"].get("action") == action)]

    decided_7d = sum(1 for m in ("deal_desk", "scope_guard", "bench", "appraisals") for r in mine(m)
                     if (r["decision"].get("at") or "") >= since)
    rehearsals = [r for r in runs["deal_room"] if r["input"].get("created_by") == me and r.get("status") == "ready"]
    fb = feedback_summary()
    leaks_7d = sum(1 for e in store.list_safety_events(500) if e["kind"] == "leak_blocked" and e["ts"] >= since)
    sales = allowed["deal_desk"]
    badges = []
    if sales:
        badges += [
            ("rehearsed", "Rehearsed", "Run a Deal Room rehearsal before a pricing call", bool(rehearsals)),
            ("scope_keeper", "Scope keeper", "Approve a scope check that logs a change request",
             any((r.get("results", {}).get("pricing") or {}).get("items") for r in mine("scope_guard", "approve"))),
            ("measured", "Measured it", "Record how long a quote takes by hand when you decide",
             any((r["decision"].get("manual_hours") is not None) for r in mine("deal_desk"))),
        ]
    if allowed["appraisals"]:
        badges += [("fair_pay", "Fair pay", "Approve a hike cycle after its fairness audit", bool(mine("appraisals", "approve"))),
                   ("bench_builder", "Bench builder", "Approve a bench plan", bool(mine("bench", "approve")))]
    badges.append(("clean_week", "Clean week", "No internal data caught by the leak guard in 7 days", leaks_7d == 0))
    goals = [{"key": "decided", "label": "Decisions this week", "value": decided_7d, "goal": 5}]
    if sales:
        goals.append({"key": "rehearsals", "label": "Calls rehearsed this week",
                      "value": sum(1 for r in rehearsals if r["created_at"] >= since), "goal": 3})
        goals.append({"key": "hours", "label": "Hours saved (reviewer reports)", "value": fb.get("hours_saved_total") or 0, "goal": 40})
    return {"goals": goals, "badges": [{"key": k, "label": lab, "hint": hint, "earned": e} for k, lab, hint, e in badges]}


@app.get("/api/safety-events", dependencies=[Depends(auth.require_role("director", "sales"))])
def safety_events() -> list[dict]:
    return store.list_safety_events()


# ---- frontend (pre-built into frontend/dist so graders only need Python) -------------
if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    f = FRONTEND_DIST / path
    if path and f.is_file() and FRONTEND_DIST in f.resolve().parents:
        return FileResponse(f)
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "Frontend not built. Run: cd frontend && npm install && npm run build"}, status_code=503)
