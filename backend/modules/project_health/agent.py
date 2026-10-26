"""The Delivery Risk Agent: explains code-computed risk signals and proposes mitigations, using staffing tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from ...core.company import CompanyData
from ...core.config import AGENT_OUTPUT_RETRIES
from ...core.llm import get_model, settings
from ..staffing import availability as av
from . import health


class Mitigation(BaseModel):
    action: str = Field(description="A concrete step, e.g. 'Move Ritika Tiwari (free from 2 Nov) onto the mobile bottleneck'.")
    owner: Literal["delivery lead", "account manager", "director", "client", "staffing"]
    effect: str = Field(description="What it changes, in words; cite the signal it addresses. No new numbers.")


class RiskReview(BaseModel):
    project_code: str
    headline: str = Field(description="One sentence a director can act on.")
    why: list[str] = Field(description="The causes, each tied to a signal or tool result (quote the evidence).")
    mitigations: list[Mitigation]
    escalate: bool = Field(description="True if a director or the client must decide something now.")
    escalation_reason: str | None = None
    client_message: str | None = Field(default=None, description="A short note to the client if they must act (e.g. a late dependency).")
    unknowns: list[str] = Field(default_factory=list, description="What the data does not tell us and should be checked.")


@dataclass
class RiskDeps:
    company: CompanyData


PROMPT = """You are Empower's DELIVERY RISK AGENT. You review one active project at a time.

The project's numbers and risk signals were computed by code from the delivery tracker, the team assignments and the
Scope Guard ledger. Treat them as facts. Do not invent, recompute or round them differently; quote them.
Your job: explain why the project is at risk, propose concrete mitigations, and say whether a director must decide now.

Use your tools: `project_team` to see who is on it and until when, `scope_history` for change requests, and
`find_cover` to find people who are free to strengthen a bottleneck or replace a roll-off (name them only if the tool
returned them). Prefer mitigations that protect delivery quality and continuity over pure utilisation. If a cause is
outside Empower's control (a late client dependency), say so and suggest a dated request to the client.
Mark anything the data cannot tell you as an unknown. Be brief and concrete."""


def project_team(ctx: RunContext[RiskDeps], project_code: str) -> list[dict]:
    """Who is assigned to the project, their role, allocation and assignment end date."""
    return health.team_for(ctx.deps.company, project_code)


def scope_history(ctx: RunContext[RiskDeps], sow_id: str) -> dict:
    """Approved, pending and clarifying change requests for a SOW (from Scope Guard)."""
    return health.scope_history(sow_id)


def find_cover(ctx: RunContext[RiskDeps], role: str, skills: list[str] | None = None, start: str | None = None,
               weeks: int = 6) -> list[dict]:
    """People in a role (optionally with skills) and how free they are from a start date.

    Args:
        role: pm, ba, uiux, fe, be, mobile, qa, devops, data, ml or lead.
        skills: optional skills to match.
        start: ISO date; default today.
        weeks: window length.
    """
    try:
        s = date.fromisoformat(start) if start else None
    except ValueError:
        s = None
    rows = av.search_people(ctx.deps.company, skills=skills or [], role=role, start=s, weeks=weeks, min_free_pct=30, limit=5)
    return [{k: r[k] for k in ("emp_id", "name", "role", "level", "matched_skills", "free_pct_in_window",
                               "earliest_start_50pct_or_more", "busy_with")} for r in rows]


def build_agent() -> Agent:
    return Agent(get_model(), name="delivery_risk", deps_type=RiskDeps, output_type=RiskReview, instructions=PROMPT,
                 tools=[project_team, scope_history, find_cover], retries=AGENT_OUTPUT_RETRIES,
                 model_settings=settings("delivery-risk", "low"))
