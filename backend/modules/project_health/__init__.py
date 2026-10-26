"""Project Health: code computes delivery-risk indicators; the Delivery Risk Agent explains them and proposes mitigations."""

from ...core.registry import Module
from .api import router

MODULE = Module(
    key="project_health",
    name="Project Health",
    tagline="Earned value, milestone slip, late dependencies, staffing and scope signals for every active project; a Delivery "
            "Risk Agent explains each risk and proposes mitigations.",
    status="live",
    router=router,
    agents=["Delivery Risk Agent"],
)
