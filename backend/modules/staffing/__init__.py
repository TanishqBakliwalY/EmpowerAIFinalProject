"""Staffing: who is free, when, with which skills. Also supplies tools to the Deal Desk."""

from ...core.registry import Module
from .api import router

MODULE = Module(
    key="staffing",
    name="Staffing Board",
    tagline="Live availability by person and role, plus an assistant that answers 'who can start on X?'.",
    router=router,
    agents=["Staffing Assistant"],
)
