"""Deal Room: the referee prices offers with the Deal Desk calculator and enforces policy (no model calls)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.core import auth
from backend.core.company import company
from backend.main import app
from backend.modules.deal_room import pipeline, referee

DEAL = json.loads(next(Path("data/demo_runs").glob("01-*.json")).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def facts():
    return referee.deal_facts(DEAL)


def test_referee_reproduces_the_deal_desk_quote(facts):
    q = facts["quote"]
    for opt in q.options:
        out = referee.price_offer(company(), facts, opt.model, "full", q.discount_pct)
        assert out["price"] == opt.price
    p1 = facts["phase1"]
    assert referee.price_offer(company(), facts, "fixed", "phase1", q.discount_pct)["price"] == p1["fixed_price"]


def test_referee_caps_discounts_and_flags_director_approval(facts):
    c = company()
    out = referee.price_offer(c, facts, "tm", "full", 25)
    assert out["discount_pct"] == c.policy["max_discount_pct"] and out["needs_director"]
    assert any("capped" in n for n in out["notes"])
    small = referee.price_offer(c, facts, "tm", "full", 3)
    assert not small["needs_director"] and small["price"] < referee.price_offer(c, facts, "tm", "full", 0)["price"]


def test_negotiator_cannot_type_its_own_numbers():
    text, n = referee.scrub_numbers("We can do USD 40,000 with a 15% discount, or $55k. Final: USD 86,000.", {"86,000"})
    assert n == 3 and "40,000" not in text and "15%" not in text and "86,000" in text


def test_client_ceiling_comes_from_their_budget(facts):
    _, tough = pipeline.private_position(company(), facts, "tough")
    _, friendly = pipeline.private_position(company(), facts, "friendly")
    budget = facts["spec"].constraints.budget_max
    assert budget and budget <= tough < friendly


def test_rehearsal_routes_need_sales_or_director():
    with TestClient(app) as c:
        hr = {d["role"]: d for d in auth.DEMO_USERS}["hr"]
        c.post("/api/auth/login", json={"email": hr["email"], "password": hr["password"]})
        assert c.post(f"/api/deals/{DEAL['id']}/rehearsals", json={"style": "tough"}).status_code == 403
        c.cookies.clear()
        sales = {d["role"]: d for d in auth.DEMO_USERS}["sales"]
        c.post("/api/auth/login", json={"email": sales["email"], "password": sales["password"]})
        assert c.post("/api/deals/nope123456/rehearsals", json={"style": "tough"}).status_code == 404
        assert c.get("/api/rehearsals/nope123456").status_code == 404


def test_paid_discovery_is_priced_from_the_rate_card(facts):
    c = company()
    out = referee.price_offer(c, facts, "fixed", "discovery", 0)
    assert out["scope"] == "discovery" and out["hours"] == 180 and out["margin_pct"] > c.policy["margin_floor_pct"]
    assert out["price"] < referee.price_offer(c, facts, "fixed", "full", 0)["price"] / 10
    assert "paid discovery" in referee.offer_card(out, facts)


def test_example_rehearsals_ship_with_the_app():
    with TestClient(app) as c:  # the lifespan imports data/demo_runs/deal_room into a fresh database
        sales = {d["role"]: d for d in auth.DEMO_USERS}["sales"]
        c.post("/api/auth/login", json={"email": sales["email"], "password": sales["password"]})
        rows = c.get("/api/deals/1e8168cc4b/rehearsals").json()
        assert any(r["result"] == "deal" for r in rows)
        full = c.get(f"/api/rehearsals/{rows[0]['id']}").json()
        assert full["results"]["coach"] and full["results"]["transcript"]
