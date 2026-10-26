"""SOWs and sample client messages for the Scope-Creep Guard.

Seed SOWs live in DATA_DIR/scope_guard/sows.json (swap the folder for real data, like the rest of the app).
SOWs made from Deal Desk deals are stored in the runtime database as runs of module "scope_sow".
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from ...core import store
from ...core.company import CompanyData
from ...core.config import DATA_DIR

SOW_MODULE = "scope_sow"


@lru_cache(maxsize=1)
def seed_sows() -> dict[str, dict]:
    path = DATA_DIR / "scope_guard" / "sows.json"
    if not path.exists():
        return {}
    return {s["sow_id"]: {**s, "source": "seed"} for s in json.loads(path.read_text(encoding="utf-8"))}


@lru_cache(maxsize=1)
def sample_messages() -> list[dict]:
    path = DATA_DIR / "scope_guard" / "client_messages.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def deal_sows() -> dict[str, dict]:
    return {r["sow_id"]: r for r in store.list_runs(SOW_MODULE, 200) if r.get("sow_id")}


def all_sows() -> dict[str, dict]:
    return {**seed_sows(), **deal_sows()}


def get_sow(sow_id: str) -> dict | None:
    return all_sows().get((sow_id or "").strip())


def sow_summary(s: dict) -> dict:
    counts: dict[str, int] = {}
    for c in s["clauses"]:
        counts[c["type"]] = counts.get(c["type"], 0) + 1
    return {k: s.get(k) for k in ("sow_id", "project_code", "project_name", "client", "client_country", "contract_type",
                                    "currency", "contract_value", "start_date", "end_date", "warranty_days", "source",
                                    "deal_id")} | {"clause_counts": counts}


def _title(text: str, words: int = 6) -> str:
    w = re.sub(r"\s+", " ", text).strip().rstrip(".").split(" ")
    return " ".join(w[:words]) + ("…" if len(w) > words else "")


def sow_from_deal(deal: dict, c: CompanyData) -> dict:
    """Turn a finished Deal Desk deal (proposal scope, assumptions, price) into a numbered SOW."""
    r = deal.get("results") or {}
    pd, q, spec, sched = r.get("proposal_draft") or {}, r.get("quote") or {}, r.get("spec") or {}, r.get("schedule") or {}
    if not pd.get("scope_in"):
        raise ValueError("This deal has no proposal scope yet.")
    cur = q.get("currency") or "USD"
    pol = c.policy
    clauses = [{"id": f"S{i}", "type": "in_scope", "title": _title(t), "text": t} for i, t in enumerate(pd["scope_in"], 1)]
    clauses += [{"id": f"X{i}", "type": "out_of_scope", "title": _title(t), "text": t}
                for i, t in enumerate(pd.get("scope_out") or [], 1)]
    clauses += [{"id": f"A{i}", "type": "assumption", "title": _title(t), "text": t}
                for i, t in enumerate(pd.get("assumptions") or [], 1)]
    clauses.append({"id": "W1", "type": "warranty", "title": "Defect warranty",
                    "text": f"Defects against the agreed acceptance criteria, reported within {pol['warranty_days']} days of "
                            "go-live, are fixed at no charge."})
    clauses.append({"id": "C1", "type": "change_control", "title": "Change requests",
                    "text": "Anything not listed under S-clauses is a change request: Empower estimates it at the rates in "
                            "this SOW and the client approves the price in writing before work starts."})
    fixed = next((o for o in q.get("options", []) if o.get("model") == "fixed"), None)
    rec = next((o for o in q.get("options", []) if o.get("model") == q.get("recommended_model")), fixed)
    sow_id = f"SOW-{deal['id']}"
    return {
        "id": sow_id,
        "sow_id": sow_id,
        "deal_id": deal["id"],
        "project_code": deal["id"],
        "project_name": spec.get("project_title") or deal.get("title"),
        "client": spec.get("client_name") or "Client",
        "client_country": spec.get("client_country") or "",
        "contract_type": q.get("recommended_model") or "fixed",
        "currency": cur,
        "contract_value": (rec or {}).get("price"),
        "signed": None,
        "start_date": sched.get("start_date"),
        "end_date": sched.get("end_date"),
        "warranty_days": pol["warranty_days"],
        "cr_rates": {k: float(v) for k, v in c.rate_card["billing_rates"].get(cur, c.rate_card["billing_rates"]["USD"]).items()},
        "clauses": clauses,
        "source": "deal",
    }
