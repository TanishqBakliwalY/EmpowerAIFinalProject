"""Structured outputs of the appraisal agents."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CalibrationFlag(BaseModel):
    emp_id: str
    issue: Literal["rating_above_evidence", "rating_below_evidence", "promotion_ready",
                   "promotion_not_supported", "notes_inconsistent"]
    current_rating: int = Field(ge=1, le=5)
    suggested_rating: int | None = Field(default=None, ge=1, le=5, description="Only if the evidence clearly supports another rating.")
    evidence: str = Field(description="The specific numbers or notes behind the flag (one sentence).")
    confidence: Literal["low", "medium", "high"]


class ManagerPattern(BaseModel):
    manager_emp_id: str
    pattern: str = Field(description="A pattern across this manager's ratings, e.g. 'rates consistently below evidence'.")


class CalibrationReport(BaseModel):
    flags: list[CalibrationFlag]
    manager_patterns: list[ManagerPattern] = Field(default_factory=list)
    summary: str = Field(description="2-3 sentences for the HR director.")


class StrategyDecision(BaseModel):
    performance_weight: float = Field(description="Weight on the rating-based guideline hike.")
    market_weight: float = Field(description="Weight on moving people toward their market band (compa-ratio).")
    retention_weight: float = Field(description="Weight on retention-risk bonuses for strong performers below market.")
    promotion_share_pct: float = Field(description="Share of the pool reserved for promotion add-ons, in percent.")
    rationale: list[str] = Field(description="3-5 bullets citing the pool summary and simulations.")


class FairnessIssue(BaseModel):
    kind: Literal["gender_gap", "manager_pattern", "office_gap", "tenure_gap", "compa_outlier", "other"]
    group: str = Field(description="Which group, e.g. 'women rated 3 on E054's team' or 'Bhopal office'.")
    finding: str = Field(description="What the metrics show, with the numbers.")
    severity: Literal["low", "medium", "high"]


class Adjustment(BaseModel):
    emp_id: str
    add_pp: float = Field(description="Percentage points to add to (or subtract from) this person's proposed hike.")
    reason: str


class FairnessReview(BaseModel):
    verdict: Literal["fair", "adjust", "escalate"] = Field(
        description="fair = no material issue; adjust = apply the adjustments below; escalate = HR must act beyond pay (e.g. re-review ratings).")
    issues: list[FairnessIssue]
    adjustments: list[Adjustment] = Field(default_factory=list, description="Targeted corrections; the pool is rebalanced in code.")
    summary: str = Field(description="One paragraph for the HR director.")


class TalkingPoint(BaseModel):
    emp_id: str
    points: list[str] = Field(description="2-3 short, specific points the manager can use in the conversation.")


class ManagerBrief(BaseModel):
    headline: str = Field(description="One line summary of this team's outcome.")
    team_summary: str = Field(description="2-3 sentences: how the team did, how hikes were decided.")
    talking_points: list[TalkingPoint]
    reminders: list[str] = Field(default_factory=list, description="Process reminders (e.g. confidentiality, effective date).")
