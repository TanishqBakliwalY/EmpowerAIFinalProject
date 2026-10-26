"""Bench Optimizer: match people rolling off projects to upcoming deals or internal work, and upskill the rest."""

from ...core.registry import Module
from .agents import SPECS
from .api import router

MODULE = Module(
    key="bench",
    name="Bench Optimizer",
    tagline="See who comes free and what it costs, then match them to upcoming deals, internal work or courses.",
    status="live",
    router=router,
    agents=[s.label for s in SPECS.values()],
)
