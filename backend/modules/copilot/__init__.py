"""Empower Copilot: a chat assistant that runs and explains Deal Desk work, staffing and pricing."""

from ...core.registry import Module
from .api import router

MODULE = Module(
    key="copilot",
    name="Emi (Copilot)",
    tagline="Chat with Empower's data: start a deal from a PDF, ask why a price is what it is, check who is free, draft client emails.",
    router=router,
    agents=["Emi (Empower Copilot)", "Email Writer"],
)
