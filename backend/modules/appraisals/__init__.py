"""Appraisal & Hike Planner: split a fixed hike budget fairly, with a bias audit before HR signs off."""

from ...core.registry import Module
from .agents import SPECS
from .api import router

MODULE = Module(
    key="appraisals",
    name="Appraisal & Hike Planner",
    tagline="Split a fixed hike budget fairly: calibrated ratings, market-aware hikes, a bias audit, manager briefs.",
    status="live",
    router=router,
    agents=[s.label for s in SPECS.values()],
)
