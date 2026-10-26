"""Scope-Creep Guard: check client asks against the signed SOW and price change requests consistently."""

from ...core.registry import Module
from .agents import SPECS
from .api import router

MODULE = Module(
    key="scope_guard",
    name="Scope-Creep Guard",
    tagline="Check every client ask against the signed SOW, price change requests from the SOW's rates, and draft the reply.",
    status="live",
    router=router,
    agents=[s.label for s in SPECS.values()],
)
