"""HTTP contracts for the pricing module. Decimals serialize as strings to keep precision."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from aios.modules.pricing.domain.models import (
    InstallmentPlanRequest,
    InstallmentSchedule,
    MortgageQuote,
    MortgageRequest,
    PaymentFrequency,
)

_Money = Decimal
_Pct = Decimal


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InstallmentPlanIn(_Strict):
    list_price: _Money = Field(gt=0, max_digits=14, decimal_places=2, examples=["4500000"])
    down_payment_pct: _Pct = Field(ge=0, le=100, examples=["10"])
    years: int = Field(ge=0, le=15, examples=[8])
    frequency: PaymentFrequency = PaymentFrequency.QUARTERLY
    delivery_payment_pct: _Pct = Field(default=Decimal("0"), ge=0, le=100)
    discount_pct: _Pct = Field(default=Decimal("0"), ge=0, le=100)

    def to_domain(self) -> InstallmentPlanRequest:
        return InstallmentPlanRequest(**self.model_dump())


class InstallmentOut(_Strict):
    number: int
    amount: _Money


class InstallmentScheduleOut(_Strict):
    list_price: _Money
    discount_amount: _Money
    net_price: _Money
    down_payment: _Money
    delivery_payment: _Money
    installment_count: int
    regular_installment: _Money
    total_paid: _Money
    installments: list[InstallmentOut]

    @classmethod
    def from_domain(cls, s: InstallmentSchedule) -> InstallmentScheduleOut:
        return cls(
            list_price=s.list_price,
            discount_amount=s.discount_amount,
            net_price=s.net_price,
            down_payment=s.down_payment,
            delivery_payment=s.delivery_payment,
            installment_count=s.installment_count,
            regular_installment=s.regular_installment,
            total_paid=s.total_paid,
            installments=[InstallmentOut(number=i.number, amount=i.amount) for i in s.installments],
        )


class MortgageIn(_Strict):
    property_price: _Money = Field(gt=0, max_digits=14, decimal_places=2, examples=["4500000"])
    down_payment_pct: _Pct = Field(ge=0, lt=100, examples=["20"])
    annual_rate_pct: _Pct = Field(ge=0, le=100, examples=["8"])
    years: int = Field(ge=1, le=30, examples=[15])

    def to_domain(self) -> MortgageRequest:
        return MortgageRequest(**self.model_dump())


class MortgageQuoteOut(_Strict):
    down_payment: _Money
    financed_amount: _Money
    months: int
    monthly_payment: _Money
    total_paid: _Money
    total_interest: _Money

    @classmethod
    def from_domain(cls, q: MortgageQuote) -> MortgageQuoteOut:
        return cls(
            down_payment=q.down_payment,
            financed_amount=q.financed_amount,
            months=q.months,
            monthly_payment=q.monthly_payment,
            total_paid=q.total_paid,
            total_interest=q.total_interest,
        )
