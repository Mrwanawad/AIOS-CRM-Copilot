"""Pricing value objects. Pure data + invariants; no IO, no framework imports."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from aios.shared.errors import InvalidInputError
from aios.shared.security import Role

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
MAX_PLAN_YEARS = 15
MAX_MORTGAGE_YEARS = 30


class PaymentFrequency(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"

    @property
    def periods_per_year(self) -> int:
        return {"monthly": 12, "quarterly": 4, "semi_annual": 2, "annual": 1}[self.value]


def _require_pct(name: str, value: Decimal) -> None:
    if not _ZERO <= value <= _HUNDRED:
        raise InvalidInputError(f"{name} must be between 0 and 100, got {value}")


@dataclass(frozen=True, slots=True)
class InstallmentPlanRequest:
    """Developer payment plan: down payment, optional delivery payment, equal installments."""

    list_price: Decimal
    down_payment_pct: Decimal
    years: int
    frequency: PaymentFrequency
    delivery_payment_pct: Decimal = _ZERO
    discount_pct: Decimal = _ZERO

    def __post_init__(self) -> None:
        if self.list_price <= _ZERO:
            raise InvalidInputError("list_price must be positive")
        _require_pct("down_payment_pct", self.down_payment_pct)
        _require_pct("delivery_payment_pct", self.delivery_payment_pct)
        _require_pct("discount_pct", self.discount_pct)
        if self.down_payment_pct + self.delivery_payment_pct > _HUNDRED:
            raise InvalidInputError("down payment + delivery payment cannot exceed 100%")
        if not 0 <= self.years <= MAX_PLAN_YEARS:
            raise InvalidInputError(f"years must be between 0 and {MAX_PLAN_YEARS}")
        remaining = _HUNDRED - self.down_payment_pct - self.delivery_payment_pct
        if self.years == 0 and remaining > _ZERO:
            raise InvalidInputError("a 0-year plan must be fully covered by down + delivery")


@dataclass(frozen=True, slots=True)
class Installment:
    number: int
    amount: Decimal


@dataclass(frozen=True, slots=True)
class InstallmentSchedule:
    list_price: Decimal
    discount_amount: Decimal
    net_price: Decimal
    down_payment: Decimal
    delivery_payment: Decimal
    installments: tuple[Installment, ...]

    @property
    def installment_count(self) -> int:
        return len(self.installments)

    @property
    def regular_installment(self) -> Decimal:
        """Amount of a typical installment (the last one may differ by rounding cents)."""
        return self.installments[0].amount if self.installments else _ZERO

    @property
    def total_paid(self) -> Decimal:
        return (
            self.down_payment
            + self.delivery_payment
            + sum((i.amount for i in self.installments), _ZERO)
        )


@dataclass(frozen=True, slots=True)
class MortgageRequest:
    property_price: Decimal
    down_payment_pct: Decimal
    annual_rate_pct: Decimal
    years: int

    def __post_init__(self) -> None:
        if self.property_price <= _ZERO:
            raise InvalidInputError("property_price must be positive")
        _require_pct("down_payment_pct", self.down_payment_pct)
        if self.down_payment_pct == _HUNDRED:
            raise InvalidInputError("down payment of 100% leaves nothing to finance")
        if not _ZERO <= self.annual_rate_pct <= _HUNDRED:
            raise InvalidInputError("annual_rate_pct must be between 0 and 100")
        if not 1 <= self.years <= MAX_MORTGAGE_YEARS:
            raise InvalidInputError(f"years must be between 1 and {MAX_MORTGAGE_YEARS}")


@dataclass(frozen=True, slots=True)
class MortgageQuote:
    down_payment: Decimal
    financed_amount: Decimal
    months: int
    monthly_payment: Decimal
    total_paid: Decimal
    total_interest: Decimal


@dataclass(frozen=True, slots=True)
class DiscountDecision:
    requested_pct: Decimal
    allowed_pct: Decimal
    approved: bool
    escalate_to: Role | None
