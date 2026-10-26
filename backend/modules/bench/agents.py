"""The three Bench Optimizer agents: Matcher, Upskilling Planner and Bench Brief writer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext

from ...core.company import CompanyData
from ...core.config import AGENT_OUTPUT_RETRIES, PROMPT_CANARY
from ...core.llm import Effort, get_model, settings
from . import tools as t
from .models import BenchBrief, MatchPlan, UpskillPlan
from .tools import BenchDeps

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


SPECS: dict[str, AgentSpec] = {s.key: s for s in [
    AgentSpec("matcher", "Matcher", "Matches people coming free to deals that need their role and skills, or to internal work.",
              "matcher.md", MatchPlan, (t.list_rolloffs, t.list_demand, t.check_match, t.find_people, t.person_schedule), "low"),
    AgentSpec("upskill", "Upskilling Planner", "Plans short courses for people still free, toward skills the pipeline asks for.",
              "upskill.md", UpskillPlan, (t.people_without_match, t.skills_gap, t.course_catalog, t.person_schedule), "low"),
    AgentSpec("brief", "Bench Brief", "Writes the director's summary from the computed plan figures.",
              "brief.md", BenchBrief, (), "low"),
]}


def system_prompt(company: CompanyData, spec: AgentSpec) -> str:
    shared = (PROMPTS / "_shared.md").read_text(encoding="utf-8").format(canary=PROMPT_CANARY, as_of=company.as_of.isoformat())
    return shared + "\n\n" + (PROMPTS / spec.prompt_file).read_text(encoding="utf-8")


_BIG_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def figures_not_in(text: str, allowed: list[float]) -> list[str]:
    """Numbers >= 1,000 in `text` that are not within 2% of a figure we gave the model."""
    bad = []
    for m in _BIG_NUMBER.finditer(text):
        try:
            v = float(m.group().replace(",", ""))
        except ValueError:
            continue
        if v < 1000 or (1900 <= v <= 2100 and "," not in m.group()):  # skip small numbers and years
            continue
        if not any(abs(v - a) <= 0.02 * max(1.0, abs(a)) for a in allowed):
            bad.append(m.group())
    return bad


def build_agent(company: CompanyData, key: str) -> Agent[BenchDeps, Any]:
    spec = SPECS[key]
    agent: Agent[BenchDeps, Any] = Agent(
        get_model(), name=f"bench_{key}", deps_type=BenchDeps, output_type=spec.output_type,
        instructions=system_prompt(company, spec), tools=list(spec.tools), retries=AGENT_OUTPUT_RETRIES,
        model_settings=settings(f"bench-{key}", spec.effort),
    )
    if key == "brief":

        @agent.output_validator
        def grounded(ctx: RunContext[BenchDeps], out: BenchBrief) -> BenchBrief:
            allowed = ctx.deps.allowed_figures
            bad = figures_not_in(" ".join([out.headline, out.summary, *out.decisions_needed, *out.risks]), allowed)
            if bad:
                raise ModelRetry("These figures are not in <plan>: " + ", ".join(bad[:6])
                                 + ". Use only figures from <plan>, copied as given.")
            return out

    return agent
