"""The seven Deal Desk agents: who they are, which tools they get, and how hard they think."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent

from ...core.company import CompanyData
from ...core.config import AGENT_OUTPUT_RETRIES, PROMPT_CANARY
from ...core.llm import Effort, get_model, settings
from . import tools as t
from .models import CriticReview, EstimateDraft, PricingDecision, ProjectSpec, ProposalDraft, SolutionDesign, StaffingDraft
from .tools import DealDeps

PROMPTS = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True)
class AgentSpec:
    key: str
    label: str
    job: str  # one line, shown in the UI
    prompt_file: str
    output_type: type[BaseModel]
    tools: tuple[Any, ...]
    effort: Effort


# Reasoning effort: "low" everywhere except the Critic. Backtest on 6 past projects (scripts/backtest.py):
# low effort for Analyst+Architect+Estimator gave the same accuracy (19.6% vs 19.8% mean abs. error)
# at 33% lower cost and 37% less time than medium.
SPECS: dict[str, AgentSpec] = {s.key: s for s in [
    AgentSpec("analyst", "Requirements Analyst", "Turns the client's message into a structured spec, questions and assumptions.",
              "analyst.md", ProjectSpec, (t.lookup_client, t.list_module_catalog), "low"),
    AgentSpec("architect", "Solution Architect", "Judges feasibility against Empower's skills, picks the stack, splits scope into work packages.",
              "architect.md", SolutionDesign, (t.find_similar_projects, t.skills_inventory, t.check_capability, t.list_module_catalog), "low"),
    AgentSpec("estimator", "Estimator", "Estimates hours per role from what similar work actually took Empower.",
              "estimator.md", EstimateDraft, (t.module_benchmarks, t.estimation_track_record, t.find_similar_projects, t.project_breakdown), "low"),
    AgentSpec("staffing", "Staffing Planner", "Builds the team from people who are actually free and sets the start date.",
              "staffing.md", StaffingDraft, (t.required_hours, t.suggest_team, t.find_people, t.person_schedule, t.role_capacity, t.simulate_schedule), "low"),
    AgentSpec("pricing", "Pricing Strategist", "Chooses fixed vs T&M and discount; the calculator enforces the margin floor.",
              "pricing.md", PricingDecision, (t.get_rate_card, t.pricing_history, t.quote_calculator), "low"),
    AgentSpec("critic", "Deal Critic", "Red-teams the whole deal and sends fixable problems back once.",
              "critic.md", CriticReview, (t.deal_checks, t.compliance_checklist, t.find_similar_projects), "medium"),
    AgentSpec("writer", "Proposal Writer", "Writes the client-facing proposal prose. Has no tools and never sees costs.",
              "writer.md", ProposalDraft, (), "low"),
]}


def system_prompt(company: CompanyData, spec: AgentSpec) -> str:
    """Long static part first (shared rules + company profile), role part after: maximises prompt-cache hits."""
    shared = (PROMPTS / "_shared.md").read_text(encoding="utf-8").format(
        canary=PROMPT_CANARY, company_profile=company.company_profile.strip(), as_of=company.as_of.isoformat()
    )
    return shared + "\n\n" + (PROMPTS / spec.prompt_file).read_text(encoding="utf-8")


def build_agent(company: CompanyData, key: str, effort: Effort | None = None) -> Agent[DealDeps, Any]:
    spec = SPECS[key]
    return Agent(
        get_model(),
        name=key,
        deps_type=DealDeps,
        output_type=spec.output_type,
        instructions=system_prompt(company, spec),
        tools=list(spec.tools),
        retries=AGENT_OUTPUT_RETRIES,
        model_settings=settings(f"deal-{key}", effort or spec.effort),
    )
