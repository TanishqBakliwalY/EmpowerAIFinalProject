"""The four Scope-Creep Guard agents: who they are, which tools they get, and how hard they think."""

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
from .models import ClientReply, CREstimate, MatchResult, SplitResult
from .tools import ScopeDeps

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
    AgentSpec("splitter", "Request Splitter", "Splits the client's message into atomic asks, quoting their words.",
              "splitter.md", SplitResult, (), "low"),
    AgentSpec("matcher", "Scope Matcher", "Classifies each ask against the signed SOW and cites the clauses.",
              "matcher.md", MatchResult, (t.get_sow, t.search_sow), "medium"),
    AgentSpec("estimator", "Change-Request Estimator", "Estimates hours by role for out-of-scope asks from Empower's history.",
              "estimator.md", CREstimate, (t.list_module_catalog, t.module_benchmarks, t.find_similar_projects, t.get_sow), "low"),
    AgentSpec("reply", "Reply Drafter", "Drafts the client reply: covered, change request with price, or a question.",
              "reply.md", ClientReply, (), "low"),
]}


def system_prompt(company: CompanyData, spec: AgentSpec) -> str:
    shared = (PROMPTS / "_shared.md").read_text(encoding="utf-8").format(canary=PROMPT_CANARY, as_of=company.as_of.isoformat())
    return shared + "\n\n" + (PROMPTS / spec.prompt_file).read_text(encoding="utf-8")


def build_agent(company: CompanyData, key: str) -> Agent[ScopeDeps, Any]:
    spec = SPECS[key]
    return Agent(
        get_model(),
        name=f"scope_{key}",
        deps_type=ScopeDeps,
        output_type=spec.output_type,
        instructions=system_prompt(company, spec),
        tools=list(spec.tools),
        retries=AGENT_OUTPUT_RETRIES,
        model_settings=settings(f"scope-{key}", spec.effort),
    )
