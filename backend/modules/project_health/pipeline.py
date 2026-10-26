"""Delivery review run: code ranks projects by risk, the Delivery Risk Agent reviews each flagged one."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded

from ...core import guardrails, store
from ...core.company import company
from ...core.config import MODEL_NAME
from ...core.runner import RunRecorder
from . import health
from .agent import RiskDeps, build_agent

MODULE_KEY = "project_health"
MAX_PROJECTS = 6
ACTIVE: dict[str, dict[str, Any]] = {}
_TASKS: set[asyncio.Task] = set()


def new_state(run_id: str, rows: list[dict], user: dict, client_ip: str) -> dict:
    steps = {"assess": {"key": "assess", "label": "Risk indicators", "kind": "code",
                        "job": "Earned value, milestone slip, dependencies, staffing and scope signals from the tracker.",
                        "status": "pending"}}
    for r in rows:
        steps[r["code"]] = {"key": r["code"], "label": f"Delivery Risk Agent: {r['code']}", "kind": "agent",
                            "job": f"Explain the risk on {r['name']} and propose mitigations.", "status": "pending"}
    return {"id": run_id, "module": MODULE_KEY, "status": "running", "created_at": store.now_iso(),
            "title": f"Delivery review: {len(rows)} project(s) at risk", "model": MODEL_NAME,
            "input": {"projects": [r["code"] for r in rows], "created_by": user.get("name", "")}, "client_ip": client_ip,
            "steps": steps, "trace": [], "results": {"projects": rows, "reviews": {}}, "error": None, "decision": None}


class ReviewRun:
    def __init__(self, run_id: str, state: dict) -> None:
        self.run_id, self.state, self.c = run_id, state, company()
        self.rec = RunRecorder(run_id, MODULE_KEY, state, self.persist)
        self.agent = build_agent()

    def persist(self) -> None:
        store.save_run(self.run_id, MODULE_KEY, self.state["status"], self.state["title"], self.state, self.state.get("client_ip", ""))

    async def run(self) -> None:
        st = self.state
        try:
            self.rec.start_step("assess")
            rows = st["results"]["projects"]
            self.rec.finish_step("assess", "; ".join(f"{r['code']} {r['level']} ({len(r['signals'])} signals)" for r in rows))
            numbers = self.c.sensitive_numbers()
            for r in rows:
                self.rec.start_step(r["code"])
                facts = {k: r[k] for k in ("code", "name", "client", "status", "contract_type", "currency", "contract_value",
                                           "start", "end", "sow_id", "level", "signals", "metrics", "milestones", "dependencies")}
                prompt = ("Review this project. Facts computed by code:\n<project>" + json.dumps(facts, ensure_ascii=False) +
                          "</project>\nToday is " + self.c.as_of.isoformat() + ".")
                review = await self.rec.run_agent(r["code"], self.agent, prompt, RiskDeps(company=self.c))
                out = review.model_dump()
                # Mitigations and client notes are shown to staff and may be forwarded: no salaries in them.
                for key in ("headline", "client_message"):
                    if out.get(key):
                        out[key] = guardrails.leak_check(out[key], numbers).text
                st["results"]["reviews"][r["code"]] = out
                self.rec.finish_step(r["code"], review.headline + (" Escalate." if review.escalate else ""))
            st["status"] = "ready"
        except UsageLimitExceeded as exc:
            st["status"], st["error"] = "failed", f"Stopped by the per-run safety limit: {exc}"
        except ModelHTTPError as exc:
            st["status"], st["error"] = ("blocked", "The provider's safety filter refused the review.") if guardrails.is_content_filter(exc) \
                else ("failed", f"ModelHTTPError {exc.status_code}: {exc.body}")
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


def start(codes: list[str] | None, user: dict, client_ip: str) -> str:
    rows = [r for r in health.all_health() if r["level"] != "ok" and (not codes or r["code"] in codes)][:MAX_PROJECTS]
    if not rows:
        raise ValueError("No project is flagged at risk right now.")
    run_id = uuid.uuid4().hex[:10]
    state = new_state(run_id, rows, user, client_ip)
    run = ReviewRun(run_id, state)
    ACTIVE[run_id] = state
    run.persist()
    task = asyncio.get_running_loop().create_task(run.run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return run_id


def get_state(run_id: str) -> dict | None:
    return ACTIVE.get(run_id) or store.get_run(run_id)


def latest_reviews() -> dict[str, dict]:
    """The most recent agent review per project code, with the run it came from."""
    out: dict[str, dict] = {}
    for r in store.list_runs(MODULE_KEY, 50):
        for code, rev in (r.get("results", {}).get("reviews") or {}).items():
            if code not in out:
                out[code] = {**rev, "run_id": r["id"], "at": r["created_at"], "run_status": r["status"]}
    return out
