"""Tools the Scope-Creep Guard agents can call. Read-only; the SOW comes from deps, never from the client text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic_ai import RunContext

from ...core.company import CompanyData
from ..deal_desk.tools import find_similar_projects, list_module_catalog, module_benchmarks  # noqa: F401 (re-exported)


@dataclass
class ScopeDeps:
    company: CompanyData
    sow: dict


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#.]+", text.lower()) if len(w) > 2}


def get_sow(ctx: RunContext[ScopeDeps]) -> dict:
    """The signed statement of work for this project: every numbered clause (S = in scope, X = out of scope,
    A = assumption, W = warranty, C = change control) with its exact wording."""
    s = ctx.deps.sow
    return {"sow_id": s["sow_id"], "project": s["project_name"], "client": s["client"], "contract_type": s["contract_type"],
            "warranty_days": s.get("warranty_days"), "end_date": s.get("end_date"),
            "clauses": [{"id": c["id"], "type": c["type"], "title": c["title"], "text": c["text"]} for c in s["clauses"]]}


def search_sow(ctx: RunContext[ScopeDeps], keywords: list[str]) -> list[dict]:
    """Find the SOW clauses that best match some keywords (e.g. ["apple pay", "wallet"]). Returns the top 5 with ids."""
    want: set[str] = set()
    for k in keywords:
        want |= _words(k)
    scored = []
    for c in ctx.deps.sow["clauses"]:
        score = len(want & _words(c["title"] + " " + c["text"]))
        if score:
            scored.append((score, c))
    scored.sort(key=lambda t: -t[0])
    return [{"id": c["id"], "type": c["type"], "title": c["title"], "text": c["text"], "match_score": s} for s, c in scored[:5]]
