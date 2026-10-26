"""Staffing tools shared by the Staffing Assistant and the Deal Desk's Staffing Planner and Architect.

They only need `ctx.deps.company`, so any module's deps object with a `company` attribute works.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic_ai import RunContext

from . import availability as av


def _date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def find_people(ctx: RunContext[Any], role: str | None = None, skills: list[str] | None = None,
                start_date: str | None = None, weeks: int = 12, min_free_pct: int = 0) -> list[dict]:
    """Search Empower employees by role and skills, with their free capacity in a time window.

    Args:
        role: one of pm, ba, uiux, fe, be, mobile, qa, devops, data, ml, lead (optional).
        skills: skills to match, e.g. ["React Native", "Firebase"] (optional).
        start_date: ISO date the window starts (default: today).
        weeks: window length in weeks.
        min_free_pct: only people with at least this % free in EVERY week of the window.
    """
    return av.search_people(ctx.deps.company, skills=skills, role=role, start=_date(start_date),
                            weeks=max(1, min(weeks, 26)), min_free_pct=min_free_pct)


def person_schedule(ctx: RunContext[Any], emp_id: str) -> dict:
    """One employee's current/upcoming assignments, leave, and weekly allocation for the next 12 weeks."""
    c = ctx.deps.company
    e = c.employees.get(emp_id.strip().upper())
    if not e:
        return {"error": f"No employee {emp_id}."}
    return av.person_card(c, e)


def role_capacity(ctx: RunContext[Any], role: str, start_date: str | None = None, weeks: int = 12) -> dict:
    """Total free FTE for a role, week by week, across the whole company."""
    return av.team_capacity(ctx.deps.company, role, _date(start_date), max(1, min(weeks, 26)))


def check_capability(ctx: RunContext[Any], skills: list[str]) -> list[dict]:
    """For each technology/skill, how many Empower people have it, how senior, how many are free soon,
    and which past projects used it. Use concrete technology names (e.g. "Stripe", "Twilio", "React Native"),
    not generic phrases; client concepts like "card payments" are mapped to in-house skills where possible.

    Args:
        skills: e.g. ["React Native", ".NET Core", "Azure", "MQTT", "SAP"].
    """
    return av.capability(ctx.deps.company, skills[:15])


def skills_inventory(ctx: RunContext[Any]) -> dict[str, int]:
    """Every skill Empower's people list, with how many people have it. Use these exact names in other tools."""
    return av.skill_inventory(ctx.deps.company)
