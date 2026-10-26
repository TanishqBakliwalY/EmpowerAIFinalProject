"""The three Deal Room agents: a simulated client, Empower's negotiator, and a coach."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, RunContext

from ...core.company import CompanyData
from ...core.config import AGENT_OUTPUT_RETRIES
from ...core.llm import get_model, settings
from . import referee
from .models import ClientTurn, CoachReport, Offer

PROMPTS = Path(__file__).resolve().parent / "prompts"

LABELS = {
    "client": ("Client (simulated)", "Plays the client from their own email: budget, deadline, priorities, a hidden ceiling."),
    "negotiator": ("Empower Negotiator", "Chooses model, scope, discount and concessions; never types a price."),
    "referee": ("Referee", "Code: prices every offer with the Deal Desk calculator and enforces discount and margin rules."),
    "coach": ("Sales Coach", "Reads the rehearsal, including the client's private thoughts, and writes the call plan."),
}


@dataclass
class RoomDeps:
    company: CompanyData
    facts: dict[str, Any]
    checked: list[dict] = field(default_factory=list)


def price_offer(ctx: RunContext[RoomDeps], model: str = "fixed", scope: str = "full", discount_pct: float = 0.0) -> dict:
    """Price a possible offer with Empower's calculator before you make it (policy caps and margin floor apply).

    Args:
        model: "fixed" or "tm".
        scope: "full", "phase1" (must-have packages only, if the deal has a Phase 1 option), or "discovery"
            (a short paid discovery ending in a fixed quote for the build).
        discount_pct: discount on list price in percent.
    """
    model = model if model in ("fixed", "tm") else "fixed"
    scope = scope if scope in ("full", "phase1", "discovery") else "full"
    out = referee.price_offer(ctx.deps.company, ctx.deps.facts, model, scope, discount_pct)
    ctx.deps.checked.append(out)
    return out


def _agent(output_type, prompt: str, key: str, tools: tuple = (), effort: str = "low") -> Agent:
    return Agent(get_model(), name=key, deps_type=RoomDeps, output_type=output_type, instructions=prompt,
                 tools=list(tools), retries=AGENT_OUTPUT_RETRIES, model_settings=settings(f"room-{key}", effort))


def client_agent(private_position: str, style_text: str) -> Agent:
    text = (PROMPTS / "client.md").read_text(encoding="utf-8")
    return _agent(ClientTurn, text.format(private_position=private_position, style_text=style_text), "client")


def negotiator_agent(deal_facts: str) -> Agent:
    text = (PROMPTS / "negotiator.md").read_text(encoding="utf-8")
    return _agent(Offer, text.format(deal_facts=deal_facts), "negotiator", (price_offer,))


def coach_agent(deal_facts: str) -> Agent:
    text = (PROMPTS / "coach.md").read_text(encoding="utf-8")
    return _agent(CoachReport, text.format(deal_facts=deal_facts), "coach")
