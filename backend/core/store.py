"""SQLite storage for runs, the token/cost ledger and safety events (data/runtime/app.db)."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from .config import DB_PATH

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    module TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT,
    client_ip TEXT,
    data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT NOT NULL,
    module TEXT NOT NULL,
    agent TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    cached_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    reasoning_tokens INTEGER NOT NULL,
    requests INTEGER NOT NULL,
    tool_calls INTEGER NOT NULL,
    cost_usd REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    pages INTEGER NOT NULL,
    chars INTEGER NOT NULL,
    truncated INTEGER NOT NULL,
    text TEXT NOT NULL,
    findings_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta_json TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    role TEXT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail_json TEXT
);
CREATE TABLE IF NOT EXISTS recommendation_reviews (
    rec_key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    actor TEXT NOT NULL,
    role TEXT,
    note TEXT,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS safety_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    detail_json TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _migrate(db: sqlite3.Connection) -> None:
    """Small additive migrations for databases created by earlier versions."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(chats)").fetchall()}
    if "user_id" not in cols:
        db.execute("ALTER TABLE chats ADD COLUMN user_id INTEGER")
        db.commit()


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _migrate(_conn)
    return _conn


# ---------------------------------------------------------------------------- runs


def save_run(run_id: str, module: str, status: str, title: str, data: dict[str, Any], client_ip: str = "") -> None:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    ts = now_iso()
    with _lock:
        db = _db()
        db.execute(
            """INSERT INTO runs (id, module, created_at, updated_at, status, title, client_ip, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, status=excluded.status,
                   title=excluded.title, data_json=excluded.data_json""",
            (run_id, module, ts, ts, status, title, client_ip, payload),
        )
        db.commit()


def get_run(run_id: str) -> dict | None:
    with _lock:
        row = _db().execute("SELECT data_json FROM runs WHERE id = ?", (run_id,)).fetchone()
    return json.loads(row["data_json"]) if row else None


def list_runs(module: str, limit: int = 100) -> list[dict]:
    with _lock:
        rows = _db().execute(
            "SELECT data_json FROM runs WHERE module = ? ORDER BY created_at DESC LIMIT ?", (module, limit)
        ).fetchall()
    return [json.loads(r["data_json"]) for r in rows]


def mark_interrupted_runs() -> int:
    """Runs left 'running' by a server restart can never finish; mark them failed on startup."""
    with _lock:
        db = _db()
        rows = db.execute("SELECT id, data_json FROM runs WHERE status IN ('queued', 'running')").fetchall()
        for r in rows:
            data = json.loads(r["data_json"])
            data["status"] = "failed"
            data["error"] = "Server restarted while this run was in progress."
            db.execute("UPDATE runs SET status='failed', data_json=? WHERE id=?", (json.dumps(data, default=str), r["id"]))
        db.commit()
    return len(rows)


# ---------------------------------------------------------------------------- usage ledger


def add_usage(run_id: str, module: str, agent: str, u: dict[str, Any]) -> None:
    with _lock:
        db = _db()
        db.execute(
            """INSERT INTO usage_ledger (ts, run_id, module, agent, input_tokens, cached_tokens, output_tokens,
                   reasoning_tokens, requests, tool_calls, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now_iso(), run_id, module, agent, u["input_tokens"], u["cached_tokens"], u["output_tokens"],
             u["reasoning_tokens"], u["requests"], u["tool_calls"], u["cost_usd"]),
        )
        db.commit()


def _cost_sql() -> str:
    """SQL expression for dollars from token counts at the CURRENT prices (stored cost_usd may predate a price change)."""
    from .config import PRICE_CACHED_INPUT_PER_M, PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M

    return (f"((SUM(input_tokens) - SUM(cached_tokens)) * {PRICE_INPUT_PER_M} + SUM(cached_tokens) * {PRICE_CACHED_INPUT_PER_M}"
            f" + SUM(output_tokens) * {PRICE_OUTPUT_PER_M}) / 1000000.0")


def spent_today_usd() -> float:
    today = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        row = _db().execute(f"SELECT COALESCE({_cost_sql()}, 0) AS s FROM usage_ledger WHERE ts >= ?", (today,)).fetchone()
    return float(row["s"] or 0)


def usage_summary() -> dict[str, Any]:
    with _lock:
        db = _db()
        by_agent = [dict(r) for r in db.execute(
            """SELECT module, agent, COUNT(DISTINCT run_id) AS runs, SUM(input_tokens) AS input_tokens,
                      SUM(cached_tokens) AS cached_tokens, SUM(output_tokens) AS output_tokens,
                      SUM(reasoning_tokens) AS reasoning_tokens, SUM(requests) AS requests,
                      SUM(tool_calls) AS tool_calls, {cost} AS cost_usd
               FROM usage_ledger GROUP BY module, agent ORDER BY cost_usd DESC""".format(cost=_cost_sql()))]
        by_day = [dict(r) for r in db.execute(
            """SELECT substr(ts, 1, 10) AS day, COUNT(DISTINCT run_id) AS runs, SUM(input_tokens) AS input_tokens,
                      SUM(cached_tokens) AS cached_tokens, SUM(output_tokens) AS output_tokens, {cost} AS cost_usd
               FROM usage_ledger GROUP BY day ORDER BY day DESC LIMIT 30""".format(cost=_cost_sql()))]
        totals = dict(db.execute(
            """SELECT COUNT(DISTINCT run_id) AS runs, COALESCE(SUM(input_tokens),0) AS input_tokens,
                      COALESCE(SUM(cached_tokens),0) AS cached_tokens, COALESCE(SUM(output_tokens),0) AS output_tokens,
                      COALESCE(SUM(reasoning_tokens),0) AS reasoning_tokens, COALESCE({cost},0) AS cost_usd
               FROM usage_ledger""".format(cost=_cost_sql())).fetchone())
    return {"totals": totals, "by_agent": by_agent, "by_day": by_day}


# ---------------------------------------------------------------------------- safety events


def add_safety_event(kind: str, severity: str, message: str, run_id: str | None = None, detail: Any = None) -> None:
    with _lock:
        db = _db()
        db.execute(
            "INSERT INTO safety_events (ts, run_id, kind, severity, message, detail_json) VALUES (?, ?, ?, ?, ?, ?)",
            (now_iso(), run_id, kind, severity, message, json.dumps(detail, default=str) if detail is not None else None),
        )
        db.commit()


def list_safety_events(limit: int = 100) -> list[dict]:
    with _lock:
        rows = _db().execute("SELECT * FROM safety_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["detail"] = json.loads(d.pop("detail_json")) if d.get("detail_json") else None
        out.append(d)
    return out


def count_runs(module: str) -> int:
    with _lock:
        return int(_db().execute("SELECT COUNT(*) FROM runs WHERE module = ?", (module,)).fetchone()[0])


def import_demo_runs(folder, module: str) -> int:
    """On a fresh install, load example runs saved from real sessions (data/demo_runs) so the app
    has finished deals to explore before anyone spends tokens. Their usage is NOT added to the ledger."""
    from pathlib import Path

    folder = Path(folder)
    if count_runs(module) or not folder.exists():
        return 0
    n = 0
    for f in sorted(folder.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        data["demo"] = True
        save_run(data["id"], module, data["status"], data["title"], data)
        n += 1
    return n


# ---------------------------------------------------------------------------- attachments (uploaded client documents)


def save_attachment(att: dict[str, Any]) -> None:
    with _lock:
        db = _db()
        db.execute(
            """INSERT INTO attachments (id, created_at, name, kind, pages, chars, truncated, text, findings_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (att["id"], now_iso(), att["name"], att["kind"], att["pages"], att["chars"], int(att["truncated"]),
             att["text"], json.dumps(att["findings"])),
        )
        db.commit()


def get_attachment(att_id: str) -> dict | None:
    with _lock:
        row = _db().execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["findings"] = json.loads(d.pop("findings_json"))
    d["truncated"] = bool(d["truncated"])
    return d


# ---------------------------------------------------------------------------- copilot chats


def create_chat(chat_id: str, title: str, user_id: int | None = None) -> None:
    ts = now_iso()
    with _lock:
        db = _db()
        db.execute("INSERT INTO chats (id, created_at, updated_at, title, user_id) VALUES (?, ?, ?, ?, ?)",
                   (chat_id, ts, ts, title, user_id))
        db.commit()


def list_chats(limit: int = 50, user_id: int | None = None) -> list[dict]:
    with _lock:
        if user_id is None:
            rows = _db().execute("SELECT * FROM chats ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = _db().execute("SELECT * FROM chats WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                                 (user_id, limit)).fetchall()
    return [dict(r) for r in rows]


def get_chat(chat_id: str) -> dict | None:
    with _lock:
        row = _db().execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
    return dict(row) if row else None


def rename_chat(chat_id: str, title: str) -> None:
    with _lock:
        db = _db()
        db.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
        db.commit()


def delete_chat(chat_id: str) -> None:
    with _lock:
        db = _db()
        db.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
        db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        db.commit()


def add_chat_message(chat_id: str, role: str, content: str, meta: dict | None = None) -> int:
    ts = now_iso()
    with _lock:
        db = _db()
        cur = db.execute(
            "INSERT INTO chat_messages (chat_id, created_at, role, content, meta_json) VALUES (?, ?, ?, ?, ?)",
            (chat_id, ts, role, content, json.dumps(meta, default=str) if meta else None),
        )
        db.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (ts, chat_id))
        db.commit()
        return int(cur.lastrowid)


def chat_messages(chat_id: str, limit: int = 200) -> list[dict]:
    with _lock:
        rows = _db().execute(
            "SELECT * FROM (SELECT * FROM chat_messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
            (chat_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["meta"] = json.loads(d.pop("meta_json")) if d.get("meta_json") else None
        out.append(d)
    return out


# ---------------------------------------------------------------------------- users and sessions


def create_user(email: str, name: str, role: str, password_hash: str) -> int:
    with _lock:
        db = _db()
        cur = db.execute("INSERT INTO users (email, name, role, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                         (email.lower(), name, role, password_hash, now_iso()))
        db.commit()
        return int(cur.lastrowid)


def get_user_by_email(email: str) -> dict | None:
    with _lock:
        row = _db().execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with _lock:
        row = _db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def create_session(token_hash: str, user_id: int, expires_at: str, ip: str) -> None:
    with _lock:
        db = _db()
        db.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at, ip) VALUES (?, ?, ?, ?, ?)",
                   (token_hash, user_id, now_iso(), expires_at, ip))
        db.commit()


def get_session(token_hash: str) -> dict | None:
    with _lock:
        row = _db().execute("SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone()
    return dict(row) if row else None


def delete_session(token_hash: str) -> None:
    with _lock:
        db = _db()
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        db.commit()


# ---------------------------------------------------------------------------- audit trail and recommendation reviews


def audit(user: dict | None, action: str, entity_type: str, entity_id: str, summary: str, detail: Any = None) -> None:
    """Append-only record of who decided or triggered what. Never updated or deleted by the app."""
    u = user or {}
    with _lock:
        db = _db()
        db.execute("INSERT INTO audit_events (ts, actor, role, action, entity_type, entity_id, summary, detail_json) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (now_iso(), u.get("name", "system"), u.get("role"), action, entity_type, entity_id, summary[:500],
                    json.dumps(detail, ensure_ascii=False, default=str) if detail is not None else None))
        db.commit()


def list_audit(limit: int = 200, entity_id: str | None = None) -> list[dict]:
    with _lock:
        if entity_id:
            rows = _db().execute("SELECT * FROM audit_events WHERE entity_id = ? ORDER BY id DESC LIMIT ?", (entity_id, limit)).fetchall()
        else:
            rows = _db().execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["detail"] = json.loads(d.pop("detail_json")) if d.get("detail_json") else None
        out.append(d)
    return out


def review_recommendation(rec_key: str, status: str, user: dict, note: str = "") -> None:
    with _lock:
        db = _db()
        db.execute("INSERT OR REPLACE INTO recommendation_reviews (rec_key, status, actor, role, note, ts) VALUES (?, ?, ?, ?, ?, ?)",
                   (rec_key, status, user.get("name", ""), user.get("role"), note[:1000], now_iso()))
        db.commit()


def recommendation_reviews() -> dict[str, dict]:
    with _lock:
        rows = _db().execute("SELECT * FROM recommendation_reviews").fetchall()
    return {r["rec_key"]: dict(r) for r in rows}
