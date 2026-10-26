"""Orchestrator routing, scenarios, Project Health, Home/Activity permissions, reviews and audit (no model calls)."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.core import auth, store
from backend.core.company import company
from backend.core.runner import RunRecorder
from backend.main import app
from backend.modules.copilot import specialists
from backend.modules.deal_desk.models import ProjectSpec
from backend.modules.deal_desk.pipeline import DealRun
from backend.modules.deal_desk.scenarios import Scenario, compute
from backend.modules.project_health import health

DEAL = json.loads(next(Path("data/demo_runs").glob("01-*.json")).read_text(encoding="utf-8"))  # BrightSmile: misses deadline
USERS = {d["role"]: d for d in auth.DEMO_USERS}


def sign_in(c, role):
    c.cookies.clear()
    assert c.post("/api/auth/login", json={"email": USERS[role]["email"], "password": USERS[role]["password"]}).status_code == 200


def orchestrator_for(state):
    run = DealRun.__new__(DealRun)
    run.state = state
    run.state["orchestrator_revisions"] = 0
    run.rec = RunRecorder("t", "deal_desk", state, lambda: None)
    run.state["steps"].setdefault("orchestrator", {"key": "orchestrator", "label": "Orchestrator", "kind": "code", "status": "pending"})
    run.deps = SimpleNamespace(spec=ProjectSpec.model_validate(state["results"]["spec"]))
    return run


def test_orchestrator_routes_a_deadline_and_budget_conflict_back_to_feasibility():
    state = copy.deepcopy(DEAL)
    state["results"]["phase1"] = None  # no smaller option yet -> the scope must be re-split
    run = orchestrator_for(state)
    problems = run.orchestrate()
    assert problems and any("deadline" in p for p in problems)
    board = state["results"]["findings"]
    assert any(f["kind"] == "timeline" and f["to"] == "Solution Architect" for f in board)
    assert state["orchestrator_revisions"] == 1
    # A second pass never re-routes again, and says plainly that the conflict is left to people.
    assert run.orchestrate() == []
    assert state["steps"]["orchestrator"]["summary"].startswith("Still in conflict after one re-split")


def test_orchestrator_does_not_reroute_when_a_phase1_option_exists():
    run = orchestrator_for(copy.deepcopy(DEAL))
    assert run.orchestrate() == []
    assert any(f["kind"] == "option" for f in run.state["results"]["findings"])


def test_scenario_recomputes_hours_schedule_and_price_from_code():
    c = company()
    base = compute(c, DEAL, Scenario())
    more = compute(c, DEAL, Scenario(effort_pct=20))
    assert base["delta"] == {"hours": 0.0, "weeks": 0.0, "go_live_days": 0, "price": 0, "margin_pts": 0.0}
    assert more["estimate"]["total_hours"] > base["estimate"]["total_hours"] and more["price"]["price"] > base["price"]["price"]
    disc = compute(c, DEAL, Scenario(discount_pct=8))
    assert disc["price"]["needs_approval"] and disc["price"]["price"] < base["price"]["price"]


def test_project_health_flags_every_seeded_problem_with_evidence():
    c = company()
    for p in health.projects(c):
        a = health.assess(c, p)
        assert (a["level"] != "ok") == (p["seeded_risk"] != "none"), p["code"]
        for s in a["signals"]:
            assert s["evidence"] and s["recommendation"]


def test_home_and_activity_respect_roles():
    with TestClient(app) as c:
        sign_in(c, "hr")
        h = c.get("/api/home").json()
        assert not any(k["key"] in ("deals", "projects", "scope") for k in h["kpis"])
        assert not any(a["module"] == "deal_desk" for a in c.get("/api/activity").json())
        assert c.get("/api/projects/health").status_code == 403
        sign_in(c, "director")
        h = c.get("/api/home").json()
        assert {"deals", "projects", "scope", "available", "bench", "impact"} <= {k["key"] for k in h["kpis"]}
        assert all(k["link"].startswith("#/") for k in h["kpis"])
        assert c.get("/api/settings").json()["editable"] is False


def test_recommendation_reviews_are_recorded_and_audited():
    with TestClient(app) as c:
        sign_in(c, "director")
        key = "risk:A207"
        assert c.post(f"/api/recommendations/{key}/review", json={"status": "accepted", "note": "mitigation agreed"}).status_code == 200
        item = next(a for a in c.get("/api/home").json()["actions"] if a["key"] == key)
        assert item["review"]["status"] == "accepted" and item["review"]["by"] == USERS["director"]["name"]
        assert any(e["entity_id"] == key and e["action"] == "recommendation.accepted" for e in c.get("/api/audit").json())
        c.post(f"/api/recommendations/{key}/review", json={"status": "open"})


def test_scope_clarification_needs_a_question_and_is_audited():
    with TestClient(app) as c:
        sign_in(c, "sales")
        run = next(r for r in store.list_runs("scope_guard", 50) if r["status"] in ("ready", "needs_clarification"))
        assert c.post(f"/api/scope/analyses/{run['id']}/decision", json={"action": "clarify", "note": "?"}).status_code == 422
        r = c.post(f"/api/scope/analyses/{run['id']}/decision", json={"action": "clarify", "note": "Is the report monthly or weekly?"})
        assert r.status_code == 200 and r.json()["status"] == "needs_clarification"
        assert any(e["entity_id"] == run["id"] for e in store.list_audit(50))


def test_emi_specialist_tools_answer_from_shared_data():
    ctx = SimpleNamespace(deps=SimpleNamespace(company=company()))
    big = specialists.capacity_check(ctx, {"mobile": 50_000}, weeks=8)
    assert big["roles"][0]["shortfall_hours"] > 0 and "short on mobile" in big["verdict"]
    small = specialists.capacity_check(ctx, {"qa": 10}, weeks=8)
    assert small["verdict"] == "fits current capacity"
    rows = specialists.pipeline_profit(ctx, "all")
    assert rows == sorted(rows, key=lambda r: -r["gross_profit_if_won_usd"])


def test_orchestrator_reroutes_when_the_phase1_option_still_misses_the_date():
    state = copy.deepcopy(DEAL)
    state["results"]["phase1"] = {**state["results"]["phase1"], "go_live": "2027-06-30"}  # after the client's deadline
    run = orchestrator_for(state)
    assert run.orchestrate()
