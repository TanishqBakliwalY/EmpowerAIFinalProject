"""Sign-in, roles and data separation, through the real FastAPI app (no model calls)."""

import pytest
from fastapi.testclient import TestClient

from backend.core import auth, store
from backend.main import app

PASSWORDS = {d["role"]: (d["email"], d["password"]) for d in auth.DEMO_USERS}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # runs the lifespan: demo users + demo deals
        yield c


def signed_in(client: TestClient, role: str) -> TestClient:
    client.cookies.clear()
    email, pw = PASSWORDS[role]
    r = client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return client


def test_api_requires_sign_in(client):
    client.cookies.clear()
    for path in ("/api/deals", "/api/staffing/board", "/api/copilot/chats", "/api/usage", "/api/files/samples/list"):
        assert client.get(path).status_code == 401, path
    assert client.get("/api/meta").status_code == 200  # the sign-in page needs this


def test_wrong_password_is_refused_with_a_generic_message(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "sales@empower.demo", "password": "nope"})
    assert r.status_code == 401 and r.json()["detail"] == "Email or password is incorrect."
    r = client.post("/api/auth/login", json={"email": "nobody@empower.demo", "password": "nope"})
    assert r.status_code == 401 and r.json()["detail"] == "Email or password is incorrect."


def test_roles_limit_what_each_person_can_open(client):
    signed_in(client, "sales")
    assert client.get("/api/deals").status_code == 200
    assert client.get("/api/auth/me").json()["role"] == "sales"
    signed_in(client, "hr")
    assert client.get("/api/deals").status_code == 403          # HR doesn't price deals
    assert client.get("/api/copilot/chats").status_code == 403
    assert client.get("/api/staffing/board").status_code == 200  # everyone can see availability


def test_only_a_director_can_approve_outside_pricing_policy(client):
    state = {"id": "policytest", "module": "deal_desk", "status": "ready", "created_at": store.now_iso(),
             "title": "Policy test", "input": {"brief": "x", "currency": "USD"}, "steps": {}, "trace": [],
             "results": {"quote": {"needs_approval": True, "approval_reasons": ["Margin below the 35% floor"]}},
             "decision": None}
    store.save_run("policytest", "deal_desk", "ready", "Policy test", state)
    signed_in(client, "sales")
    r = client.post("/api/deals/policytest/decision", json={"action": "approve", "note": "client is strategic for us"})
    assert r.status_code == 403 and "Director" in r.json()["detail"]
    signed_in(client, "director")
    r = client.post("/api/deals/policytest/decision", json={"action": "approve", "note": "client is strategic for us"})
    assert r.status_code == 200
    assert store.get_run("policytest")["decision"]["approver"] == "Anita Rao"  # recorded from the session, not typed


def test_copilot_chats_are_private(client):
    signed_in(client, "sales")
    chat_id = client.post("/api/copilot/chats").json()["id"]
    assert any(c["id"] == chat_id for c in client.get("/api/copilot/chats").json())
    signed_in(client, "director")
    assert all(c["id"] != chat_id for c in client.get("/api/copilot/chats").json())
    assert client.get(f"/api/copilot/chats/{chat_id}").status_code == 404


def test_sign_out_ends_the_session(client):
    signed_in(client, "sales")
    assert client.get("/api/deals").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/deals").status_code == 401


def test_passwords_are_hashed_not_stored():
    u = store.get_user_by_email("sales@empower.demo")
    assert u and "demo-sales" not in u["password_hash"] and u["password_hash"].startswith("pbkdf2_sha256$")


def test_only_failed_sign_ins_count_toward_the_lockout():
    from backend.core.guardrails import RateLimiter

    old = auth._login_limiter
    auth._login_limiter = RateLimiter(3, 60)
    try:
        with TestClient(app) as c:
            email, pw = PASSWORDS["sales"]
            for _ in range(5):  # successful sign-ins never lock anyone out
                assert c.post("/api/auth/login", json={"email": email, "password": pw}).status_code == 200
            codes = [c.post("/api/auth/login", json={"email": email, "password": "guess"}).status_code for _ in range(4)]
            assert codes == [401, 401, 401, 429]
            assert c.post("/api/auth/login", json={"email": email, "password": pw}).status_code == 429
    finally:
        auth._login_limiter = old
