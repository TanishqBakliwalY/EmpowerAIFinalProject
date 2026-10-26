"""Scope-Creep Guard: citation checks, change-request pricing, ledger, injection handling and roles (no model calls)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core import guardrails
from backend.core.auth import current_user
from backend.core.company import company
from backend.modules.deal_desk.models import RoleHours
from backend.modules.scope_guard import calculators as calc
from backend.modules.scope_guard import data
from backend.modules.scope_guard.api import router
from backend.modules.scope_guard.models import Ask, CheckedItem, CREstimate, CRItem, Match, MatchResult
from backend.modules.scope_guard.pipeline import REDACTED_LINE, redact_ai_directed_lines

SOW = data.seed_sows()["SOW-A201"]


def ask(i: str) -> Ask:
    return Ask(id=i, quote=f"quote {i}", summary=f"summary {i}", kind="feature")


def test_seed_data_shape():
    sows = data.seed_sows()
    assert {"SOW-A201", "SOW-A206", "SOW-A209", "SOW-A210"} <= set(sows)
    for s in sows.values():
        types = {c["type"] for c in s["clauses"]}
        assert {"in_scope", "out_of_scope", "warranty", "change_control"} <= types
        assert s["cr_rates"]["be"] > 0
    msgs = data.sample_messages()
    assert len(msgs) >= 10 and all(m["sow_id"] in sows for m in msgs)


def test_citations_are_validated_and_unsupported_verdicts_downgraded():
    asks = [ask("R1"), ask("R2"), ask("R3"), ask("R4"), ask("R5"), ask("R6")]
    result = MatchResult(matches=[
        Match(ask_id="R1", verdict="in_scope", clause_ids=["S1"], reasoning="P2P is S1", confidence="high"),
        Match(ask_id="R2", verdict="out_of_scope", clause_ids=["X9"], reasoning="invented clause", confidence="high"),
        Match(ask_id="R3", verdict="warranty_fix", clause_ids=["S2"], reasoning="no W clause cited", confidence="medium"),
        Match(ask_id="R4", verdict="in_scope", clause_ids=["S3", "X1"], reasoning="contradiction", confidence="low"),
        Match(ask_id="R5", verdict="out_of_scope", clause_ids=["x1", "C1"], reasoning="Apple Pay excluded", confidence="high"),
    ])  # R6 has no verdict at all
    items = {i.ask_id: i for i in calc.validate(SOW, asks, result)}
    assert items["R1"].verdict == "in_scope" and not items["R1"].downgraded
    assert items["R2"].verdict == "ambiguous" and items["R2"].invalid_clause_ids == ["X9"]
    assert items["R3"].verdict == "ambiguous" and items["R3"].model_verdict == "warranty_fix"
    assert items["R4"].verdict == "ambiguous"
    assert items["R5"].verdict == "out_of_scope" and items["R5"].clause_ids == ["X1", "C1"]  # case-insensitive ids
    assert items["R6"].verdict == "ambiguous" and items["R6"].downgraded
    assert all(items[k].question_for_client for k in ("R2", "R3", "R4"))


def test_change_request_pricing_uses_sow_rates_and_policy_overhead():
    items = [CheckedItem(ask_id="R1", quote="q", summary="Apple Pay", kind="feature", verdict="out_of_scope"),
             CheckedItem(ask_id="R2", quote="q", summary="tiny", kind="feature", verdict="out_of_scope"),
             CheckedItem(ask_id="R3", quote="q", summary="bug", kind="defect", verdict="in_scope"),
             CheckedItem(ask_id="R4", quote="q", summary="no estimate", kind="feature", verdict="out_of_scope")]
    est = CREstimate(items=[
        CRItem(ask_id="R1", module_key="payments", complexity="medium", basis="b",
               hours=[RoleHours(role="mobile", hours=20), RoleHours(role="be", hours=10), RoleHours(role="qa", hours=10),
                      RoleHours(role="pm", hours=99)]),
        CRItem(ask_id="R2", module_key="custom", complexity="low", basis="b", hours=[RoleHours(role="fe", hours=0.5)]),
        CRItem(ask_id="R3", module_key="custom", complexity="low", basis="b", hours=[RoleHours(role="fe", hours=5)]),
    ])
    p = calc.price(SOW, items, est, pm_overhead_pct=10)
    r = SOW["cr_rates"]
    cr = {c.ask_id: c for c in p.items}
    assert set(cr) == {"R1", "R2", "R4"}  # in-scope R3 is never priced
    assert cr["R1"].build_hours == 40 and cr["R1"].pm_hours == 4 and "pm" not in cr["R1"].hours_by_role
    assert cr["R1"].price == round(20 * r["mobile"] + 10 * r["be"] + 10 * r["qa"] + 4 * r["pm"], -1)
    assert cr["R2"].build_hours == calc.MIN_BUILD_HOURS  # raised to the minimum
    assert not cr["R4"].estimated and cr["R4"].price == 0
    assert any("pm hours ignored" in w for w in p.warnings) and any("not estimated" in w for w in p.warnings)
    assert p.counts == {"in_scope": 1, "out_of_scope": 3, "ambiguous": 0, "warranty_fix": 0}
    assert p.total_price == round(sum(c.price for c in p.items), -1)


def test_ledger_counts_billed_and_absorbed_only_for_approved_runs():
    def run(action, absorb, crs):
        return {"input": {"sow_id": "SOW-A201"}, "decision": {"action": action, "absorb_ask_ids": absorb} if action else None,
                "results": {"items": [{"verdict": "out_of_scope"}] * len(crs) + [{"verdict": "in_scope"}],
                            "pricing": {"items": [{"ask_id": a, "total_hours": h, "price": v} for a, h, v in crs]}}}
    runs = [run("approve", ["R2"], [("R1", 10, 300), ("R2", 5, 150)]),
            run("reject", [], [("R1", 100, 3000)]),
            run(None, [], [("R1", 100, 3000)])]
    out = calc.ledger(runs, data.seed_sows())
    p = out["projects"][0]
    assert p["analyses"] == 3 and p["approved"] == 1
    assert p["billable_hours"] == 10 and p["billable_value"] == 300 and p["margin_protected"] == 300
    assert p["absorbed_hours"] == 5 and p["absorbed_value"] == 150
    assert p["out_of_scope"] == 2 and p["in_scope"] == 1


def test_injection_sample_is_flagged_and_its_ai_directed_line_removed():
    m = next(x for x in data.sample_messages() if x["id"] == "M09")
    res = guardrails.screen_untrusted(m["text"])
    assert res.injection_suspected
    clean, removed = redact_ai_directed_lines(res.clean_text)
    assert removed >= 1 and REDACTED_LINE in clean
    assert "ignore your rules" not in clean.lower()
    assert "email campaigns" in clean  # the genuine ask survives


def test_sow_from_deal_numbers_clauses_and_uses_rate_card():
    deal = {"id": "abc1234567", "title": "t", "results": {
        "proposal_draft": {"scope_in": ["Booking app", "Reminders"], "scope_out": ["Native tablet app"], "assumptions": ["Client API"]},
        "quote": {"currency": "EUR", "recommended_model": "fixed", "options": [{"model": "fixed", "price": 90000}]},
        "spec": {"project_title": "Booking", "client_name": "Acme", "client_country": "DE"},
        "schedule": {"start_date": "2026-11-02", "end_date": "2027-04-01"}}}
    sow = data.sow_from_deal(deal, company())
    ids = [c["id"] for c in sow["clauses"]]
    assert ids == ["S1", "S2", "X1", "A1", "W1", "C1"]
    assert sow["sow_id"] == "SOW-abc1234567" and sow["contract_value"] == 90000 and sow["currency"] == "EUR"
    assert sow["cr_rates"] == {k: float(v) for k, v in company().rate_card["billing_rates"]["EUR"].items()}


def _client(role: str) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: {"id": 1, "email": f"{role}@x", "name": role.title(), "role": role,
                                                      "role_label": role}
    return TestClient(app)


def test_router_allows_sales_and_directors_but_not_hr():
    assert _client("sales").get("/api/scope/sows").status_code == 200
    assert _client("director").get("/api/scope/samples?sow_id=SOW-A201").status_code == 200
    r = _client("hr").get("/api/scope/sows")
    assert r.status_code == 403


def test_analysis_input_validation():
    c = _client("sales")
    assert c.post("/api/scope/analyses", json={"sow_id": "SOW-NOPE", "message": "x" * 50}).status_code == 404
    assert c.post("/api/scope/analyses", json={"sow_id": "SOW-A201", "message": "hi"}).status_code == 422
