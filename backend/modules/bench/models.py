"""Structured outputs of the Bench Optimizer agents."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Match(BaseModel):
    emp_id: str = Field(description="Employee id, e.g. E029, exactly as list_rolloffs returns it.")
    target_type: Literal["deal", "internal"]
    target_id: str = Field(description="Deal id (10 characters) or internal initiative id (e.g. IW1).")
    allocation_pct: int = Field(ge=25, le=100, description="Share of a full week, in steps of 25.")
    start_date: str = Field(description="ISO date the person starts on it (not before they are free).")
    weeks: int = Field(ge=1, le=26)
    rationale: str = Field(description="One sentence: why this person fits (role, skills, timing).")
    confidence: Literal["low", "medium", "high"]


class MatchPlan(BaseModel):
    matches: list[Match]
    left_unmatched: list[str] = Field(default_factory=list, description="Employee ids with no good match.")
    notes: list[str] = Field(default_factory=list)


class Upskill(BaseModel):
    emp_id: str
    course_id: str = Field(description="Course id from course_catalog, e.g. C03.")
    start_date: str
    hours_per_week: int = Field(ge=2, le=40)
    reason: str = Field(description="Which demand gap this closes (skill, deals).")


class UpskillPlan(BaseModel):
    items: list[Upskill]
    notes: list[str] = Field(default_factory=list)


class BenchBrief(BaseModel):
    headline: str = Field(description="One line for the director.")
    summary: str = Field(description="Markdown, under 150 words, using only figures given to you.")
    decisions_needed: list[str]
    risks: list[str]
