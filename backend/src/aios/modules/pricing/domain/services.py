"""Deterministic pricing calculations. The LLM never does arithmetic; it calls these."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, localcontext

from aios.modules.pricing.domain.models import (
    DiscountDecision,
    Installment,
    InstallmentPlanRequest,
    InstallmentSchedule,
    MortgageQuote,
    MortgageRequest,
)
from aios.modules.pricing.domain.money import HUNDRED, pct_of, to_money
from aios.shared.errors import InvalidInputError
from aios.shared.security import Role

_ZERO = Decimal("0")
_MONTHS_PER_YEAR = 12


def calculate_installment_plan(req: InstallmentPlanRequest) -> InstallmentSchedule:
    """Split the net price into down payment, delivery payment and equal installments.

    Percentages apply to the net (post-discount) price. The final installment absorbs
    rounding so the schedule always sums exactly to the net price.
    """
    discount = pct_of(req.list_price, req.discount_pct)
    net = req.list_price - discount
    down = pct_of(net, req.down_payment_pct)
    delivery = pct_of(net, req.delivery_payment_pct)
    remaining = net - down - delivery

    count = req.years * req.frequency.periods_per_year
    installments: tuple[Installment, ...] = ()
    if count and remaining > _ZERO:
        regular = to_money(remaining / count)
        last = remaining - regular * (count - 1)
        installments = (
            *(Installment(number=n, amount=regular) for n in range(1, count)),
            Installment(number=count, amount=last),
        )
    elif remaining > _ZERO:
        # Unreachable given request invariants, but never silently drop money.
        delivery += remaining

    return InstallmentSchedule(
        list_price=req.list_price,
        discount_amount=discount,
        net_price=net,
        down_payment=down,
        delivery_payment=delivery,
        installments=installments,
    )


def calculate_mortgage(req: MortgageRequest) -> MortgageQuote:
    """Fixed-rate amortizing loan, monthly payments (standard annuity formula)."""
    down = pct_of(req.property_price, req.down_payment_pct)
    principal = req.property_price - down
    months = req.years * _MONTHS_PER_YEAR

    with localcontext() as ctx:
        ctx.prec = 34
        rate = req.annual_rate_pct / HUNDRED / _MONTHS_PER_YEAR
        if rate == _ZERO:
            payment = principal / months
        else:
            payment = principal * rate / (1 - (1 + rate) ** -months)

    monthly = to_money(payment)
    total = monthly * months
    return MortgageQuote(
        down_payment=down,
        financed_amount=principal,
        months=months,
        monthly_payment=monthly,
        total_paid=total + down,
        total_interest=total - principal,
    )


def evaluate_discount(
    requested_pct: Decimal,
    role: Role,
    limits_pct: Mapping[Role, Decimal],
) -> DiscountDecision:
    """Check a requested discount against role limits and find who must approve it.

    Escalates to the lowest role whose limit covers the request, so a rep asking
    for 4% goes to the team lead, not straight to the manager.
    """
    if not _ZERO <= requested_pct <= HUNDRED:
        raise InvalidInputError("requested discount must be between 0 and 100")
    allowed = limits_pct.get(role, _ZERO)
    if requested_pct <= allowed:
        return DiscountDecision(requested_pct, allowed, approved=True, escalate_to=None)

    approver = role.next_up()
    while approver is not None and requested_pct > limits_pct.get(approver, _ZERO):
        approver = approver.next_up()
    # No role covers it: top role must decide as an exception.
    escalate_to = approver if approver is not None else max(Role, key=lambda r: r.rank)
    return DiscountDecision(requested_pct, allowed, approved=False, escalate_to=escalate_to)
