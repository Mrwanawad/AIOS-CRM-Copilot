"""FastAPI routes for pricing.

Discount checks are not exposed here yet: the approver role must come from an
authenticated principal, which lands with the auth module.

No ``from __future__ import annotations`` here: FastAPI must resolve the locally
defined ``Annotated`` dependency at runtime.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends

from aios.modules.pricing.api.schemas import (
    InstallmentPlanIn,
    InstallmentScheduleOut,
    MortgageIn,
    MortgageQuoteOut,
)
from aios.modules.pricing.application.service import PricingService


def build_router(get_service: Callable[[], PricingService]) -> APIRouter:
    """Build the router with an injected service factory (set by the composition root)."""
    router = APIRouter(prefix="/pricing", tags=["pricing"])
    service_dep = Annotated[PricingService, Depends(get_service)]

    @router.post("/installments", response_model=InstallmentScheduleOut)
    def installment_plan(body: InstallmentPlanIn, service: service_dep) -> InstallmentScheduleOut:
        return InstallmentScheduleOut.from_domain(service.installment_plan(body.to_domain()))

    @router.post("/mortgage", response_model=MortgageQuoteOut)
    def mortgage(body: MortgageIn, service: service_dep) -> MortgageQuoteOut:
        return MortgageQuoteOut.from_domain(service.mortgage(body.to_domain()))

    return router
