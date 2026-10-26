"""HTTP routes for the Empower Copilot chat."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core import store
from ...core.auth import current_user, require_role
from ...core.config import COPILOT_MESSAGES_PER_HOUR
from ...core.guardrails import RateLimiter
from ...core.llm import api_key_present
from ...core.usage import BudgetExceeded, check_daily_budget, reprice
from .agent import run_turn

router = APIRouter(prefix="/api/copilot", tags=["copilot"], dependencies=[Depends(require_role("director", "sales"))])
_limiter = RateLimiter(COPILOT_MESSAGES_PER_HOUR, 3600)


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=3)
    page_deal_id: str | None = Field(default=None, max_length=20)


def _with_cost(m: dict) -> dict:
    meta = m.get("meta")
    if meta and meta.get("usage"):
        m = {**m, "meta": {**meta, "usage": reprice(meta["usage"])}}
    return m


def _own_chat(chat_id: str, user: dict) -> dict:
    chat = store.get_chat(chat_id)
    if not chat or (chat.get("user_id") not in (None, user["id"])):  # chats are private to their owner
        raise HTTPException(404, "No such chat.")
    return chat


@router.get("/chats")
def chats(user: dict = Depends(current_user)) -> list[dict]:
    return store.list_chats(user_id=user["id"])


@router.post("/chats")
def new_chat(user: dict = Depends(current_user)) -> dict:
    chat_id = uuid.uuid4().hex[:10]
    store.create_chat(chat_id, "New chat", user["id"])
    return {"id": chat_id}


@router.get("/chats/{chat_id}")
def get_chat(chat_id: str, user: dict = Depends(current_user)) -> dict:
    chat = _own_chat(chat_id, user)
    return {"chat": chat, "messages": [_with_cost(m) for m in store.chat_messages(chat_id)]}


@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: str, user: dict = Depends(current_user)) -> dict:
    _own_chat(chat_id, user)
    store.delete_chat(chat_id)
    return {"ok": True}


@router.post("/chats/{chat_id}/messages")
async def send(chat_id: str, body: NewMessage, request: Request, user: dict = Depends(current_user)) -> dict:
    chat = _own_chat(chat_id, user)
    if not api_key_present():
        raise HTTPException(503, "PORTKEY_API_KEY is not set. Put it in a .env file in this folder or the folder above it.")
    try:
        check_daily_budget()
    except BudgetExceeded as exc:
        store.add_safety_event("daily_budget_stop", "high", str(exc))
        raise HTTPException(429, str(exc)) from exc
    ip = request.client.host if request.client else "unknown"
    wait = _limiter.check(ip)
    if wait:
        store.add_safety_event("rate_limited", "warning", f"Copilot rate-limited for {ip}.")
        raise HTTPException(429, f"Too many messages from this computer. Try again in {wait // 60 + 1} minutes.")
    if chat["title"] == "New chat":
        title = " ".join(body.content.split())[:60] or "Chat"
        store.rename_chat(chat_id, title)
    reply = await run_turn(chat_id, body.content.strip(), body.attachment_ids, body.page_deal_id, ip, user)
    return _with_cost(reply)
