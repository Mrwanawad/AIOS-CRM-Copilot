"""Adapter: discount limits read from application settings."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType

from aios.shared.config import Settings
from aios.shared.security import Role


class SettingsDiscountLimits:
    """Implements ``DiscountLimitsProvider`` from ``Settings.discount_limits_pct``."""

    def __init__(self, settings: Settings) -> None:
        unknown = set(settings.discount_limits_pct) - {r.value for r in Role}
        if unknown:
            raise ValueError(f"unknown roles in discount_limits_pct: {sorted(unknown)}")
        self._limits: Mapping[Role, Decimal] = MappingProxyType(
            {Role(k): v for k, v in settings.discount_limits_pct.items()}
        )

    def limits(self) -> Mapping[Role, Decimal]:
        return self._limits
