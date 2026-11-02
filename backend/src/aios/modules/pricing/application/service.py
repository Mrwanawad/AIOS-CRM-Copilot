"""Pricing use cases. Entry point for the API layer and, later, the agent's calculator tool."""

from __future__ import annotations

from decimal import Decimal

from aios.modules.pricing.domain.models import (
    DiscountDecision,
    InstallmentPlanRequest,
    InstallmentSchedule,
    MortgageQuote,
    MortgageRequest,
)
from aios.modules.pricing.domain.services import (
    calculate_installment_plan,
    calculate_mortgage,
    evaluate_discount,
)
from aios.modules.pricing.ports.discount_limits import DiscountLimitsProvider
from aios.shared.security import Role


class PricingService:
    def __init__(self, discount_limits: DiscountLimitsProvider) -> None:
        self._discount_limits = discount_limits

    def installment_plan(self, req: InstallmentPlanRequest) -> InstallmentSchedule:
        return calculate_installment_plan(req)

    def mortgage(self, req: MortgageRequest) -> MortgageQuote:
        return calculate_mortgage(req)

    def check_discount(self, requested_pct: Decimal, role: Role) -> DiscountDecision:
        """``role`` must come from the authenticated principal, never from user input."""
        return evaluate_discount(requested_pct, role, self._discount_limits.limits())
