"""Appraisal & Hike Planner: deterministic parts and access control (no model calls)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth import current_user
from backend.modules.appraisals import optimizer as opt
from backend.modules.appraisals.api import router
from backend.modules.appraisals.data import appraisal_data
from backend.modules.appraisals.pipeline import inr


@pytest.fixture(scope="module")
def d():
    return appraisal_data()


def test_optimizer_spends_the_pool_exactly_within_caps(d):
    for pool_pct in (6.0, 9.0, 12.0):
        a = opt.allocate(d, d.policy["default_strategy"], pool_pct)
        assert a.feasible
        assert a.used_amount == a.pool_amount == round(d.payroll * pool_pct / 100)
        for e, p in d.people.items():
            lo, hi = opt.bounds_for(d.policy, p)
            assert lo - 0.05 <= a.hikes_pct[e] <= hi + 0.05, (e, a.hikes_pct[e], lo, hi)
            if p.rating == 1:
                assert a.amounts[e] == 0


def test_higher_ratings_get_more_on_average(d):
    s = opt.summary(d, opt.allocate(d, d.policy["default_strategy"]))
    avg = {b["rating"]: b["avg_hike_pct"] for b in s["by_rating"]}
    assert avg[5] > avg[4] > avg[3] > avg[2]


def test_strategy_weights_are_clamped_to_policy(d):
    s = opt.clamp_strategy(d.policy, {"performance_weight": 5, "market_weight": -1, "retention_weight": 0.9, "promotion_share_pct": 90})
    b = d.policy["strategy_bounds"]
    assert s["performance_weight"] == b["performance_weight"][1] and s["market_weight"] == b["market_weight"][0]
    assert s["retention_weight"] == b["retention_weight"][1] and s["promotion_share_pct"] == b["promotion_share_pct"][1]


def test_fairness_metrics_find_the_planted_problems(d):
    m = opt.fairness_metrics(d, opt.allocate(d, d.policy["default_strategy"]))
    kinds = {(f["kind"], f["group"]) for f in m["flags"]}
    assert any(k == "manager_pattern" for k, _ in kinds), kinds          # one manager rates women below evidence
    assert ("office_gap", "Bhopal office") in kinds                         # Bhopal below its moved-up market band
    bhopal = next(o for o in m["offices"] if o["office"] == "Bhopal")
    assert bhopal["avg_compa_before"] < min(o["avg_compa_before"] for o in m["offices"] if o["office"] != "Bhopal")


def test_adjustments_rebalance_to_the_pool(d):
    base = opt.allocate(d, d.policy["default_strategy"])
    m = opt.fairness_metrics(d, base)
    members = next(f["members"] for f in m["flags"] if f["kind"] == "manager_pattern")
    adj = {e: 2.0 for e in members}
    after = opt.allocate(d, d.policy["default_strategy"], overrides_pp=adj)
    assert after.used_amount == after.pool_amount == base.pool_amount
    assert all(after.hikes_pct[e] > base.hikes_pct[e] for e in members)
    assert after.locked == set(members)
    # everyone else paid for it, a little
    others = [e for e in d.people if e not in adj and base.hikes_pct[e] > 0]
    assert sum(after.amounts[e] for e in others) < sum(base.amounts[e] for e in others)


def test_adjustments_are_bounded(d):
    lo, hi = d.policy["max_adjustment_pp"]
    base = opt.allocate(d, d.policy["default_strategy"])
    e = next(e for e, p in d.people.items() if p.rating == 3)
    after = opt.allocate(d, d.policy["default_strategy"], overrides_pp={e: 50.0})
    assert after.hikes_pct[e] <= base.hikes_pct[e] + hi + 0.05


def test_indian_number_format():
    assert inr(85068000) == "8,50,68,000" and inr(1234) == "1,234" and inr(999) == "999"


def _client(role: str) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: {"id": 1, "email": f"{role}@x", "name": role, "role": role, "role_label": role}
    return TestClient(app)


def test_only_hr_and_directors_can_open_appraisals():
    assert _client("sales").get("/api/appraisals/overview").status_code == 403
    for role in ("hr", "director"):
        r = _client(role).get("/api/appraisals/overview")
        assert r.status_code == 200 and r.json()["headcount"] == 54


def test_privacy_check_strips_other_teams_and_gender(d):
    from backend.core.company import company
    from backend.core.runner import RunRecorder
    from backend.modules.appraisals.models import ManagerBrief, TalkingPoint
    from backend.modules.appraisals.pipeline import AppraisalRun, new_state
    from backend.modules.appraisals.tools import AppDeps

    run = AppraisalRun.__new__(AppraisalRun)  # no model needed for the code-only privacy step
    run.d, run.c, run.run_id, run.save = d, company(), "test-privacy", False
    run.state = new_state("test-privacy", {"pool_pct": 9.0, "note": ""}, "test")
    run.rec = RunRecorder("test-privacy", "appraisals", run.state, lambda: None)
    strat = opt.clamp_strategy(d.policy, d.policy["default_strategy"])
    run.deps = AppDeps(data=d, company=run.c, pool_pct=9.0, strategy=strat, allocation=opt.allocate(d, strat))
    mgr = "E054"
    team = [p.emp_id for p in d.team(mgr)]
    outsider = next(p for p in d.people.values() if p.emp_id not in team and p.emp_id != mgr)
    r = run.state["results"]
    r.update(summary=opt.summary(d, run.deps.allocation), strategy={"chosen": strat, "rationale": []},
             fairness_before=opt.fairness_metrics(d, run.deps.allocation))
    r["brief_drafts"] = {mgr: ManagerBrief(
        headline="Strong year for the team",
        team_summary=f"Your team did better than {outsider.name}'s group.",
        talking_points=[TalkingPoint(emp_id=team[0], points=["Clear ownership of releases.", "She did better than the men on the team."])],
        reminders=["Keep numbers confidential."]).model_dump()}
    run.privacy()
    reasons = {f["reason"] for f in r["privacy_findings"]}
    assert {"another team's employee", "gender"} <= reasons
    brief = r["briefs"][mgr]
    assert outsider.name not in brief and "men on the team" not in brief
    assert "Clear ownership of releases." in brief and "Keep numbers confidential." in brief
    assert r["memo_markdown"].startswith("# HR director memo")
