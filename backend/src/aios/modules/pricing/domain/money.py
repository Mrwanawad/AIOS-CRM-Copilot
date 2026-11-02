"""Decimal money helpers. Floats are never used for currency."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def to_money(value: Decimal) -> Decimal:
    """Round to 2 decimal places using commercial (half-up) rounding."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def pct_of(amount: Decimal, pct: Decimal) -> Decimal:
    """Return ``pct`` percent of ``amount``, rounded to money."""
    return to_money(amount * pct / HUNDRED)
