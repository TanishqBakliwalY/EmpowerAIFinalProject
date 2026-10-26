"""Deal Room: a simulated client and Empower's negotiator rehearse the pricing call; code referees every offer."""

from ...core.registry import Module
from .agents import LABELS
from .api import router

MODULE = Module(
    key="deal_room",
    name="Deal Room",
    tagline="Rehearse the pricing call: a simulated client negotiates with Empower's negotiator, code prices every offer, "
            "and a coach writes the plan for the real call.",
    status="live",
    router=router,
    agents=[LABELS[k][0] for k in ("client", "negotiator", "coach")],
)
