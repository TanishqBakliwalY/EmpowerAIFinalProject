"""The list of modules the app knows about.

A module is one business capability (Deal Desk, Staffing, ...). It brings its own agents, prompts,
tools and API router, and reads company data through backend.core.company. To add one later
(e.g. an appraisal & hike planner), create backend/modules/<name>/ with a MODULE object and list it here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import APIRouter


@dataclass
class Module:
    key: str
    name: str
    tagline: str
    status: str = "live"  # "live" | "planned"
    router: APIRouter | None = None
    agents: list[str] = field(default_factory=list)

    def info(self) -> dict:
        return {"key": self.key, "name": self.name, "tagline": self.tagline, "status": self.status, "agents": self.agents}


def all_modules() -> list[Module]:
    from ..modules.appraisals import MODULE as appraisals
    from ..modules.bench import MODULE as bench
    from ..modules.copilot import MODULE as copilot
    from ..modules.deal_desk import MODULE as deal_desk
    from ..modules.deal_room import MODULE as deal_room
    from ..modules.project_health import MODULE as project_health
    from ..modules.scope_guard import MODULE as scope_guard
    from ..modules.staffing import MODULE as staffing

    return [deal_desk, deal_room, copilot, scope_guard, project_health, staffing, bench, appraisals]
