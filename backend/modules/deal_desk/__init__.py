"""Deal Desk: client request -> feasibility -> estimate -> staffing -> price -> review -> proposal."""

from ...core.registry import Module
from .agents import SPECS
from .api import router

MODULE = Module(
    key="deal_desk",
    name="Deal Desk",
    tagline="Turn a client request into a feasibility view, a history-based estimate, a real team, a price and a proposal.",
    router=router,
    agents=[s.label for s in SPECS.values()],
)
