"""Identity and role primitives shared across modules."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Role-based access levels, ordered from least to most privileged."""

    REP = "rep"
    TEAM_LEAD = "team_lead"
    MANAGER = "manager"

    @property
    def rank(self) -> int:
        return _ROLE_ORDER.index(self)

    def next_up(self) -> Role | None:
        """Return the role one level above this one, or ``None`` for the top role."""
        idx = self.rank + 1
        return _ROLE_ORDER[idx] if idx < len(_ROLE_ORDER) else None


_ROLE_ORDER: tuple[Role, ...] = (Role.REP, Role.TEAM_LEAD, Role.MANAGER)
