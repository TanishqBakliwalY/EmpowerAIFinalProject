"""Bench Optimizer: deterministic logic and access control (no model calls)."""

import copy
from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core import auth
from backend.core.company import Assignment, company
from backend.modules.bench import api as bench_api
from backend.modules.bench import calculators as calc
from backend.modules.bench.agents import figures_not_in
from backend.modules.bench.data import courses, internal_work


def small_company(assignments: dict[str, list[tuple]]):
    """A copy of the demo company with only the given people and their assignments.
    assignments: emp_id -> [(kind, alloc_pct, start_offset_days, end_offset_days, name)]"""
    base = company()
    c = copy.copy(base)
    c.employees = {k: base.employees[k] for k in assignments}
    c.assignments = [
        Assignment(emp_id=k, project_code="T" + k, project_name=name, client="Test", allocation_pct=pct,
                   start=base.as_of + timedelta(days=s), end=base.as_of + timedelta(days=e), kind=kind)
        for k, rows in assignments.items() for kind, pct, s, e, name in rows
    ]
    return c


def emp_of_role(role: str, skip: set[str] = frozenset()) -> str:
    return next(e.emp_id for e in company().employees.values() if e.role == role and e.emp_id not in skip)


A, B, C2, D = emp_of_role("be"), emp_of_role("be", {emp_of_role("be")}), emp_of_role("pm"), emp_of_role("qa")


def scenario():
    return small_company({
        A: [("project", 100, -60, 20, "Claims stabilisation")],          # busy weeks 0-2, free from week 3
        B: [("project", 100, -60, 200, "Long retainer")],               # never free
        C2: [("project", 50, -60, 200, "Half-time PM role")],            # half free all along
        D: [("leave", 100, 7, 12, "Planned leave")],                     # free, one week of leave
    })


# ---------------------------------------------------------------- roll-offs and cost


def test_rolloff_detection():
    c = scenario()
    rolls = {r["emp_id"]: r for r in calc.rolloffs(c, horizon=12, min_free_pct=50)}
    assert B not in rolls
    assert rolls[A]["status"] == "rolling_off"
    assert rolls[A]["free_from"] == (c.as_of + timedelta(days=21)).isoformat()
    assert rolls[A]["ending_project"]["project"] == "Claims stabilisation"
    assert rolls[C2]["status"] == "on_bench_now" and rolls[C2]["free_pct"] == 50
    assert rolls[D]["leave_weeks"] == 1 and rolls[D]["bench_hours"] == 11 * 40


def test_bench_cost_math():
    c = small_company({D: []})
    rolls = calc.rolloffs(c, horizon=2, min_free_pct=50)
    rate = c.role_cost_inr_per_hour[c.employees[D].role]
    assert rolls[0]["bench_hours"] == 80
    assert rolls[0]["bench_cost_inr"] == round(80 * rate)
    weekly = calc.weekly_forecast(c, horizon=2)
    assert [w["bench_fte"] for w in weekly] == [1.0, 1.0]
    assert sum(w["bench_cost_inr"] for w in weekly) == round(40 * rate) * 2


# ---------------------------------------------------------------- demand from the Deal Desk


def fake_deal(deal_id: str, status: str) -> dict:
    return {
        "id": deal_id, "status": status, "title": f"Deal {deal_id}",
        "results": {
            "spec": {"client_name": "Acme", "constraints": {"preferred_stack": ["Stripe"]}},
            "design": {"recommended_stack": [{"layer": "Mobile", "technology": "React Native"}], "capability_gaps": ["MQTT"]},
            "estimate": {"hours_by_role": {"mobile": 680.0, "be": 340.0, "pm": 100.0}},
            "schedule": {"start_date": "2026-11-02", "end_date": "2027-03-01", "total_weeks": 17.0, "build_weeks": 10.0,
                         "team": [{"emp_id": "E029", "name": "Ritika Tiwari", "role": "mobile", "allocation_pct": 100}],
                         "uncovered_roles": ["be"]},
        },
    }


def test_demand_extraction_from_deals():
    c = company()
    deals = calc.deal_demand(c, [fake_deal("aaaaaaaaaa", "ready"), fake_deal("bbbbbbbbbb", "rejected"),
                                 fake_deal("cccccccccc", "running"), fake_deal("dddddddddd", "approved")])
    assert [d["deal_id"] for d in deals] == ["dddddddddd", "aaaaaaaaaa"]  # approved first; rejected/running ignored
    d = deals[1]
    assert d["win_probability"] == 0.5 and "React Native" in d["stack"] and "Stripe" in d["stack"]
    roles = {r["role"]: r for r in d["roles"]}
    assert roles["mobile"]["fte_needed"] == 2.0  # 680 h / (10 weeks x 34 h)
    assert roles["be"]["uncovered"] and roles["mobile"]["planned"][0]["emp_id"] == "E029"
    gaps = {g["skill"]: g for g in calc.skills_gap(c, deals, [], courses())}
    assert gaps["MQTT"]["gap"] and "C10" in gaps["MQTT"]["courses"]


# ---------------------------------------------------------------- validation of agent proposals


def test_match_validation_rejects_unavailable_and_wrong_people():
    c = scenario()
    deals = calc.deal_demand(c, [fake_deal("aaaaaaaaaa", "approved")])
    rolls = calc.rolloffs(c, 12, 50)
    end = c.as_of + timedelta(weeks=12)
    proposed = [
        {"emp_id": B, "target_type": "deal", "target_id": "aaaaaaaaaa", "allocation_pct": 100, "start_date": c.as_of.isoformat(), "weeks": 8},
        {"emp_id": "E999", "target_type": "deal", "target_id": "aaaaaaaaaa", "allocation_pct": 100, "start_date": c.as_of.isoformat(), "weeks": 8},
        {"emp_id": D, "target_type": "deal", "target_id": "aaaaaaaaaa", "allocation_pct": 100, "start_date": c.as_of.isoformat(), "weeks": 8},
        {"emp_id": A, "target_type": "deal", "target_id": "aaaaaaaaaa", "allocation_pct": 100, "start_date": c.as_of.isoformat(), "weeks": 8},
        {"emp_id": A, "target_type": "internal", "target_id": "IW5", "allocation_pct": 50, "start_date": c.as_of.isoformat(), "weeks": 4},
    ]
    kept, rejected = calc.validate_matches(c, proposed, deals, calc.internal_demand(internal_work()), rolls, end)
    reasons = {r["emp_id"]: " ".join(r["issues"]) for r in rejected}
    assert "not free" in reasons[B]
    assert "not an Empower employee" in reasons["E999"]
    assert "does not need that role" in reasons[D]  # QA engineer, deal needs mobile/be/pm
    a = kept[0]
    assert a["emp_id"] == A and a["start_date"] == (c.as_of + timedelta(days=21)).isoformat()  # moved to free-from
    assert a["status"] == "flagged" and a["hours_in_horizon"] > 0
    assert len(kept) == 1  # A's second match finds no free time left


def test_upskilling_validation_and_plan_value():
    c = scenario()
    rolls = calc.rolloffs(c, 12, 50)
    end = c.as_of + timedelta(weeks=12)
    items = [{"emp_id": D, "course_id": "C13", "start_date": c.as_of.isoformat(), "hours_per_week": 60, "reason": "x"},
             {"emp_id": D, "course_id": "C99", "start_date": c.as_of.isoformat(), "hours_per_week": 10, "reason": "x"}]
    kept, rejected = calc.validate_upskilling(c, items, courses(), rolls, [], end)
    assert len(kept) == 1 and len(rejected) == 1
    assert kept[0]["hours_per_week"] == 40 and kept[0]["weeks"] == 1  # 10-hour course, capped at a full week
    v = calc.plan_value(c, calc.weekly_forecast(c, 12), rolls, [], kept)
    assert v["people_upskilled"] == 1 and v["training_hours"] == 10
    assert v["idle_cost_remaining_inr"] < v["bench_cost_if_nothing_inr"]


def test_brief_figures_must_come_from_the_plan():
    assert figures_not_in("Bench cost is INR 1,47,09,888 in 2026.", [14709888.0]) == []
    assert figures_not_in("We save INR 9,99,999.", [14709888.0]) == ["9,99,999"]


def test_indian_grouping():
    assert calc.inr(14709888) == "1,47,09,888" and calc.inr(999) == "999" and calc.inr(100000) == "1,00,000"


# ---------------------------------------------------------------- access control


def client_as(role: str) -> TestClient:
    app = FastAPI()
    app.include_router(bench_api.router)
    app.dependency_overrides[auth.current_user] = lambda: {"id": 1, "email": f"{role}@x", "name": role.title(), "role": role,
                                                           "role_label": role}
    return TestClient(app)


def test_router_refuses_sales_and_allows_hr_and_directors():
    assert client_as("sales").get("/api/bench/forecast").status_code == 403
    for role in ("director", "hr"):
        r = client_as(role).get("/api/bench/forecast?weeks=8")
        assert r.status_code == 200 and r.json()["horizon_weeks"] == 8


def test_calculator_fill_uses_spare_internal_capacity_only_with_skill_fit():
    c = scenario()
    rolls = calc.rolloffs(c, 12, 50)
    end = c.as_of + timedelta(weeks=12)
    work = [
        {"id": "X1", "name": "Backend kit", "roles": ["be"], "skills": list(c.employees[A].skills[:1]), "capacity_fte": 1.0,
         "min_weeks": 2, "max_weeks": 3, "priority": "high", "value": "v"},
        {"id": "X2", "name": "QA packs", "roles": ["qa"], "skills": ["Nonexistent skill"], "capacity_fte": 2.0,
         "min_weeks": 2, "max_weeks": None, "priority": "high", "value": "v"},
    ]
    extra = calc.fill_internal_capacity(c, [], rolls, calc.internal_demand(work), end)
    by_target = {m["target_id"]: m for m in extra}
    assert "X2" not in by_target  # D is QA but has no matching skill: not placed
    assert by_target["X1"]["emp_id"] == A and by_target["X1"]["weeks"] == 3  # capped at max_weeks
    assert by_target["X1"]["allocation_pct"] == 100 and by_target["X1"]["source"] == "calculator"
