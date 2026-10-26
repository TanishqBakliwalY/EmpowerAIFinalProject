"""Deterministic Deal Desk and staffing logic (no model calls)."""

from backend.core.company import company
from backend.modules.deal_desk import calculators as calc
from backend.modules.deal_desk.models import (
    EstimateDraft,
    LineItem,
    RoleHours,
    Risk,
    SolutionDesign,
    StackChoice,
    StaffingDraft,
    TeamMember,
    WorkPackage,
)
from backend.modules.staffing import availability as av


def draft() -> EstimateDraft:
    return EstimateDraft(
        line_items=[
            LineItem(work_package="Booking", module_key="booking", complexity="medium",
                     hours=[RoleHours(role="be", hours=120), RoleHours(role="fe", hours=64), RoleHours(role="qa", hours=56)], basis="b"),
            LineItem(work_package="Payments", module_key="payments", complexity="medium",
                     hours=[RoleHours(role="be", hours=96), RoleHours(role="qa", hours=48)], basis="b"),
            LineItem(work_package="Reports", module_key="reporting", complexity="low",
                     hours=[RoleHours(role="fe", hours=34), RoleHours(role="data", hours=24)], basis="b"),
        ],
        risk_level="medium", risk_reasons=["r"],
    )


def design() -> SolutionDesign:
    return SolutionDesign(
        feasibility="feasible", feasibility_reasons=["ok"],
        recommended_stack=[StackChoice(layer="API", technology=".NET Core", reason="depth")],
        work_packages=[
            WorkPackage(name="Booking", module_key="booking", complexity="medium", priority="must", scope_notes="x"),
            WorkPackage(name="Payments", module_key="payments", complexity="medium", priority="must", scope_notes="x"),
            WorkPackage(name="Reports", module_key="reporting", complexity="low", priority="nice", scope_notes="x"),
        ],
        risks=[Risk(risk="r", impact="low", mitigation="m")],
    )


def test_expected_vs_priced_hours():
    c = company()
    e = calc.compute_estimate(c, draft(), "web")
    pol = c.policy
    assert e.expected_hours < e.total_hours
    assert abs(e.total_hours - e.expected_hours * (1 + pol["contingency_pct"]["medium"] / 100)) < 1
    assert e.low_hours < e.expected_hours < e.high_hours
    # PM 10% + lead 6% of build (+QA top-up) are inside the expected hours
    assert e.pm_hours > 0 and e.lead_hours > 0


def test_schedule_uses_real_availability_and_flags_unknown_people():
    c = company()
    e = calc.compute_estimate(c, draft(), "web")
    free_fe = av.search_people(c, role="fe", min_free_pct=100, weeks=8)
    assert free_fe, "demo data should have at least one fully free frontend developer"
    team = [TeamMember(emp_id=free_fe[0]["emp_id"], role="fe", allocation_pct=100, reason="free"),
            TeamMember(emp_id="E999", role="qa", allocation_pct=100, reason="does not exist")]
    s = calc.plan_schedule(c, e, StaffingDraft(team=team, start_date=c.as_of.isoformat()), deadline="2030-01-01")
    assert any("E999" in w for w in s.warnings)
    assert [m.emp_id for m in s.team] == [free_fe[0]["emp_id"]]
    assert "be" in s.uncovered_roles  # nobody assigned -> hire assumption, flagged
    assert s.meets_deadline is True and s.total_weeks > 0


def test_double_booking_is_caught():
    c = company()
    e = calc.compute_estimate(c, draft(), "web")
    busy = next(p for p in av.search_people(c, role="be", weeks=8, limit=20) if p["free_pct_in_window"] == 0)
    s = calc.plan_schedule(c, e, StaffingDraft(team=[TeamMember(emp_id=busy["emp_id"], role="be", allocation_pct=100, reason="x")],
                                               start_date=c.as_of.isoformat()))
    assert s.team[0].conflict and "be" in s.uncovered_roles


def test_phase1_option_prices_only_must_haves():
    c = company()
    d = draft()
    e = calc.compute_estimate(c, d, "web")
    s = calc.plan_schedule(c, e, StaffingDraft(team=[], start_date=c.as_of.isoformat()))
    p1 = calc.phase1_option(c, d, design(), e, "web", "USD", 0, s, 30000, "USD")
    assert p1 is not None
    assert p1["packages"] == ["Booking", "Payments"] and p1["later_packages"] == ["Reports"]
    assert p1["hours"] < e.total_hours
    full = calc.price_options(c, e, "USD", 0, s.total_weeks)
    assert p1["fixed_price"] < full.options[0].price


def test_capability_maps_client_concepts_to_in_house_skills():
    c = company()
    rows = {r["skill"]: r for r in av.capability(c, ["card payments", "SMS reminders", "Rust"])}
    assert "Stripe" in rows["card payments"]["matched_in_house_skills"] and rows["card payments"]["people"] > 0
    assert "Twilio" in rows["SMS reminders"]["matched_in_house_skills"]
    assert rows["Rust"]["people"] == 0 and rows["Rust"]["assessment"] == "none in-house"


def test_react_does_not_match_react_native():
    assert not av.skill_matches("React", "React Native")
    assert av.skill_matches(".NET", ".NET Core")


def test_people_search_falls_back_to_role_when_no_skill_matches():
    c = company()
    rows = av.search_people(c, role="qa", skills=["e-commerce"], weeks=8)
    assert rows and all(r["role"] == "qa" for r in rows)
    assert all(r["matched_skills"] == [] for r in rows)


def test_baseline_team_uses_only_free_people_and_respects_deadline():
    c = company()
    e = calc.compute_estimate(c, draft(), "web")
    deadline = (c.as_of.replace(year=c.as_of.year + 1)).isoformat()
    team = calc.suggest_team(c, e, c.as_of, deadline)
    assert team.team, "baseline should find someone"
    for m in team.team:
        assert m.emp_id in c.employees
        assert m.allocation_pct <= av.free_pct(c, m.emp_id, c.as_of, 26) or m.allocation_pct <= 100
    s = calc.plan_schedule(c, e, team, deadline)
    assert s.meets_deadline and not any(m.conflict for m in s.team)


def test_regulated_data_adds_qa_by_policy():
    c = company()
    plain = calc.compute_estimate(c, draft(), "web")
    hipaa = calc.compute_estimate(c, draft(), "web", ["HIPAA"])
    assert hipaa.hours_by_role["qa"] > plain.hours_by_role["qa"]
    assert any("regulated data" in w for w in hipaa.warnings)
