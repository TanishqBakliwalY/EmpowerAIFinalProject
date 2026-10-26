"""Sign-in, sessions and roles (Python standard library only, like Homework 4's security.py).

Roles
  director  everything, including approving deals outside pricing policy and salary data
  sales     Deal Desk, Copilot, Scope Guard, Staffing
  hr        Appraisals, Staffing, Bench

Passwords are stored as PBKDF2-SHA256 hashes; sessions are random tokens kept in an httpOnly cookie,
and only a SHA-256 of each token is stored, so a copied database cannot be replayed as cookies.
Demo accounts are created on first start (synthetic company, so the graders can sign in with one click).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import store
from .guardrails import RateLimiter

ROLES = ("director", "sales", "hr")
ROLE_LABELS = {"director": "Director", "sales": "Sales & delivery", "hr": "HR"}
SESSION_COOKIE = "empower_session"
SESSION_HOURS = 12
ITERATIONS = 600_000  # OWASP 2023 recommendation for PBKDF2-HMAC-SHA256
DEMO_MODE = os.getenv("EMPOWER_DEMO_ACCOUNTS", "1") != "0"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"

DEMO_USERS = [
    {"email": "director@empower.demo", "name": "Anita Rao", "role": "director", "password": "demo-director"},
    {"email": "sales@empower.demo", "name": "Rohit Mehta", "role": "sales", "password": "demo-sales"},
    {"email": "hr@empower.demo", "name": "Kavya Iyer", "role": "hr", "password": "demo-hr"},
]

_login_limiter = RateLimiter(10, 15 * 60)  # 10 failed attempts per 15 minutes per IP


# ---------------------------------------------------------------------------- hashing


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    return hmac.compare_digest(candidate, digest)  # constant time


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_DUMMY = hash_password(secrets.token_urlsafe(12), 1000)  # equalises timing for unknown emails


# ---------------------------------------------------------------------------- users and sessions


def public_user(u: dict) -> dict:
    return {"id": u["id"], "email": u["email"], "name": u["name"], "role": u["role"], "role_label": ROLE_LABELS.get(u["role"], u["role"])}


def ensure_demo_users() -> int:
    if not DEMO_MODE:
        return 0
    created = 0
    for d in DEMO_USERS:
        if not store.get_user_by_email(d["email"]):
            store.create_user(d["email"], d["name"], d["role"], hash_password(d["password"]))
            created += 1
    return created


def authenticate(email: str, password: str) -> dict | None:
    user = store.get_user_by_email(email.strip().lower())
    if not user or not user["active"]:
        verify_password(password, _DUMMY)
        return None
    return user if verify_password(password, user["password_hash"]) else None


def create_session(user_id: int, ip: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    store.create_session(_token_hash(token), user_id, expires.isoformat(timespec="seconds"), ip)
    return token


def user_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    s = store.get_session(_token_hash(token))
    if not s or s["expires_at"] < datetime.now(timezone.utc).isoformat(timespec="seconds"):
        return None
    u = store.get_user_by_id(s["user_id"])
    return u if u and u["active"] else None


# ---------------------------------------------------------------------------- FastAPI dependencies


def current_user(request: Request) -> dict:
    """Any signed-in user. Every /api route except sign-in and /api/meta depends on this."""
    user = user_for_token(request.cookies.get(SESSION_COOKIE))
    if not user:
        raise HTTPException(401, "Please sign in.")
    request.state.user = user
    return public_user(user)


def require_role(*roles: str):
    """Restrict a route (or a whole router) to some roles, e.g. Depends(require_role("hr", "director"))."""

    def dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "Your role can't open this. It needs: " + ", ".join(ROLE_LABELS[r] for r in roles) + ".")
        return user

    return dep


# ---------------------------------------------------------------------------- API

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
def login(body: Login, request: Request, response: Response) -> dict:
    ip = request.client.host if request.client else "unknown"
    wait = _login_limiter.wait_seconds(ip)  # only failed attempts count, so normal sign-ins never lock anyone out
    if wait:
        store.add_safety_event("login_rate_limited", "warning", f"Too many sign-in attempts from {ip}.")
        raise HTTPException(429, f"Too many sign-in attempts. Try again in {wait // 60 + 1} minutes.")
    user = authenticate(body.email, body.password)
    if not user:
        _login_limiter.check(ip)
        store.add_safety_event("login_failed", "info", f"Failed sign-in for {body.email.strip().lower()[:80]}.")
        raise HTTPException(401, "Email or password is incorrect.")
    token = create_session(user["id"], ip)
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_HOURS * 3600, httponly=True, samesite="lax",
                        secure=COOKIE_SECURE, path="/")
    return public_user(user)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        store.delete_session(_token_hash(token))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(current_user)) -> dict:
    return user


@router.get("/demo-accounts")
def demo_accounts() -> list[dict]:
    """Shown on the sign-in page so graders can sign in with one click. Synthetic data only; disable with
    EMPOWER_DEMO_ACCOUNTS=0 when real company data is loaded."""
    if not DEMO_MODE:
        return []
    return [{"email": d["email"], "password": d["password"], "name": d["name"], "role": d["role"],
             "role_label": ROLE_LABELS[d["role"]]} for d in DEMO_USERS]
