"""Port: where role discount limits come from (config today, a policy DB table later)."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Protocol

from aios.shared.security import Role


class DiscountLimitsProvider(Protocol):
    def limits(self) -> Mapping[Role, Decimal]:
        """Return the max discount percent each role may grant without escalation."""
        ...
