"""The four appraisal agents: who they are, which tools they get, and how hard they think."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent

from ...core.config import AGENT_OUTPUT_RETRIES, PROMPT_CANARY
from ...core.llm import Effort, get_model, settings
from . import tools as t
from .data import AppraisalData
from .models import CalibrationReport, FairnessReview, ManagerBrief, StrategyDecision
from .tools import AppDeps

PROMPTS = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True)
class AgentSpec:
    key: str
    label: str
    job: str
    prompt_file: str
    output_type: type[BaseModel]
    tools: tuple[Any, ...]
    effort: Effort


# Judgment-heavy reviews (calibration, fairness) think harder; the rest run at low effort.
SPECS: dict[str, AgentSpec] = {s.key: s for s in [
    AgentSpec("calibration", "Calibration Analyst", "Flags ratings that don't match the evidence. Never sees gender or pay.",
              "calibration.md", CalibrationReport, (t.rating_distribution, t.team_evidence, t.employee_detail), "medium"),
    AgentSpec("strategy", "Hike Strategist", "Weighs performance, market correction and retention within HR's bounds.",
              "strategy.md", StrategyDecision, (t.hike_policy, t.pool_summary, t.simulate_strategy), "low"),
    AgentSpec("fairness", "Fairness Auditor", "Finds unfair gaps (gender, manager, office, tenure) and proposes fixes once.",
              "fairness.md", FairnessReview, (t.fairness_metrics, t.calibration_findings, t.proposal_for), "medium"),
    AgentSpec("briefs", "Manager Brief Writer", "Talking points for each manager about their own team only. No tools.",
              "brief.md", ManagerBrief, (), "low"),
]}


def system_prompt(d: AppraisalData, as_of: str, spec: AgentSpec) -> str:
    shared = (PROMPTS / "_shared.md").read_text(encoding="utf-8").format(
        canary=PROMPT_CANARY, as_of=as_of, cycle=d.policy.get("cycle", ""))
    return shared + "\n\n" + (PROMPTS / spec.prompt_file).read_text(encoding="utf-8")


def build_agent(d: AppraisalData, as_of: str, key: str, effort: Effort | None = None) -> Agent[AppDeps, Any]:
    spec = SPECS[key]
    return Agent(
        get_model(), name=f"appraisal_{key}", deps_type=AppDeps, output_type=spec.output_type,
        instructions=system_prompt(d, as_of, spec), tools=list(spec.tools), retries=AGENT_OUTPUT_RETRIES,
        model_settings=settings(f"appraisal-{key}", effort or spec.effort),
    )
