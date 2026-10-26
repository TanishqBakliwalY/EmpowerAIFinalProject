"""Structured outputs of the three Deal Room agents."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ClientTurn(BaseModel):
    message: str = Field(description="What you say to Empower, in your own voice: 2-5 sentences, like a real email or call.")
    stance: Literal["negotiating", "accept", "walk_away"] = Field(
        description="'accept' only if the latest offer is one you would sign now; 'walk_away' if you would end talks.")
    objections: list[str] = Field(default_factory=list, description="Your concrete concerns right now, short phrases.")
    private_thoughts: str = Field(
        description="What you really think and what would close the deal for you. Empower does not see this during the "
                    "rehearsal; it is shown to the sales team afterwards as coaching.")


class Offer(BaseModel):
    message: str = Field(description="What you say to the client: 2-5 sentences. Do NOT type prices, discounts or percentages; "
                                     "the offer card the referee attaches states the numbers.")
    model: Literal["fixed", "tm"] = Field(description="Commercial model: 'fixed' price or 'tm' (time & materials).")
    scope: Literal["full", "phase1", "discovery"] = Field(
        description="'full' scope; 'phase1' (must-have packages only) if one exists; or 'discovery', a short paid discovery that "
                    "ends in a fixed quote for the build (use when requirements or dates are too uncertain to commit).")
    discount_pct: float = Field(ge=0, le=30, description="Discount on list price in percent. Policy caps apply.")
    concessions: list[str] = Field(default_factory=list,
                                   description="Non-price terms you offer, e.g. payment schedule, start date, warranty, a pilot.")
    internal_reasoning: str = Field(description="One or two sentences for the Empower team: why this move.")


class CoachReport(BaseModel):
    outcome: Literal["deal", "no_deal", "close"] = Field(description="'close' if talks ended without agreement but near one.")
    headline: str = Field(description="One sentence a sales lead can act on.")
    likely_objections: list[str] = Field(description="The client's real objections, most important first.")
    concession_path: list[str] = Field(description="The order in which to offer concessions in the real call.")
    walk_away_point: str = Field(description="Where Empower should stop conceding, and why (no internal cost figures).")
    what_worked: list[str] = Field(default_factory=list)
    what_to_avoid: list[str] = Field(default_factory=list)
    questions_to_ask: list[str] = Field(default_factory=list, description="Questions that would unlock the deal.")
