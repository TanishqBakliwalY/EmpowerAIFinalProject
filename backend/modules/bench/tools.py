"""Tools for the Bench Optimizer agents. Read-only; matches are only proposals until a person approves."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pydantic_ai import RunContext

from ...core.company import CompanyData
from ..staffing.tools import find_people, person_schedule  # noqa: F401 (re-exported to the agents)
from . import calculators as calc
from .data import courses


@dataclass
class BenchDeps:
    company: CompanyData
    horizon_weeks: int
    min_free_pct: int
    horizon_end: date
    rolloffs: list[dict]
    deals: list[dict]
    internal: list[dict]
    gaps: list[dict] = field(default_factory=list)
    matches: list[dict] = field(default_factory=list)  # validated matches (for the Upskilling Planner)
    allowed_figures: list[float] = field(default_factory=list)  # figures the Brief may quote (grounding check)


def list_rolloffs(ctx: RunContext[BenchDeps], role: str | None = None) -> list[dict]:
    """People who are free (>= the plan's minimum %) now or within the horizon, with when, how much and why.

    Args:
        role: optional role filter: pm, ba, uiux, fe, be, mobile, qa, devops, data, ml, lead.
    """
    return [
        {k: r[k] for k in ("emp_id", "name", "role", "title", "level", "office", "skills", "free_from", "free_pct",
                           "status", "leave_weeks", "bench_hours")}
        | {"ending_project": (r["ending_project"] or {}).get("project"), "next_project": r["next_project"]}
        for r in ctx.deps.rolloffs if not role or r["role"] == role
    ]


def list_demand(ctx: RunContext[BenchDeps]) -> dict:
    """Where people could go: Deal Desk deals that are approved or awaiting a decision (with win probability,
    dates, roles and FTE needed, stack), and Empower's internal initiatives (capacity in FTE)."""
    d = ctx.deps
    return {
        "deals": [{k: x[k] for k in ("deal_id", "title", "client", "status", "win_probability", "start", "end", "weeks",
                                     "roles", "stack")} for x in d.deals],
        "internal_work": [{k: w.get(k) for k in ("id", "name", "roles", "skills", "capacity_fte", "min_weeks", "max_weeks",
                                                 "priority", "value")}
                          for w in d.internal],
        "today": d.company.as_of.isoformat(), "horizon_end": d.horizon_end.isoformat(),
    }


def check_match(ctx: RunContext[BenchDeps], emp_id: str, target_type: str, target_id: str, allocation_pct: int,
                start_date: str, weeks: int) -> dict:
    """Test one candidate match before proposing it: is the person free then, is the role needed, how good is the
    skill fit, and how many bench hours it fills. Returns ok / flagged / rejected with reasons.

    Args:
        emp_id: employee id.
        target_type: "deal" or "internal".
        target_id: deal id or internal initiative id.
        allocation_pct: 25, 50, 75 or 100.
        start_date: ISO date.
        weeks: duration in weeks.
    """
    d = ctx.deps
    planned = sum(m["allocation_pct"] for m in d.matches if m["emp_id"] == emp_id.strip().upper())
    v = calc.validate_match(d.company, {"emp_id": emp_id, "target_type": target_type, "target_id": target_id,
                                        "allocation_pct": allocation_pct, "start_date": start_date, "weeks": weeks},
                            {x["deal_id"]: x for x in d.deals}, {w["id"]: w for w in d.internal},
                            {r["emp_id"]: r for r in d.rolloffs}, d.horizon_end, planned)
    return {k: v.get(k) for k in ("status", "issues", "fit", "matched_skills", "allocation_pct", "start_date",
                                  "hours_in_horizon", "win_probability")}


def skills_gap(ctx: RunContext[BenchDeps]) -> list[dict]:
    """Skills the pipeline asks for (weighted by win probability), how many people have them, how many of those
    are coming free, and which courses teach them. gap=true means nobody free has the skill."""
    return ctx.deps.gaps[:20]


def course_catalog(ctx: RunContext[BenchDeps], skill: str | None = None) -> list[dict]:
    """Courses Empower can use (id, skill, title, provider, hours, cost in INR, format). Optional skill filter."""
    out = courses()
    if skill:
        s = skill.lower()
        out = [x for x in out if s in x["skill"].lower() or s in x["title"].lower()]
    return out


def people_without_match(ctx: RunContext[BenchDeps]) -> list[dict]:
    """People coming free who have no (or only partial) match after the Matcher, with free % left."""
    d = ctx.deps
    planned: dict[str, int] = {}
    for m in d.matches:
        planned[m["emp_id"]] = planned.get(m["emp_id"], 0) + m["allocation_pct"]
    out = []
    for r in d.rolloffs:
        left = r["free_pct"] - planned.get(r["emp_id"], 0)
        if left >= 25:
            out.append({k: r[k] for k in ("emp_id", "name", "role", "title", "level", "skills", "free_from")}
                       | {"free_pct_left": left})
    return out
