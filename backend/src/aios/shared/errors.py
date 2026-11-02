"""Domain error hierarchy. Adapters translate these into transport-level responses."""

from __future__ import annotations


class AIOSError(Exception):
    """Base class for all application errors."""

    code: str = "aios_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidInputError(AIOSError):
    """Input violates a domain invariant (e.g. negative price, down payment over 100%)."""

    code = "invalid_input"


class NotFoundError(AIOSError):
    """A referenced entity does not exist."""

    code = "not_found"
