"""
Structured application errors with rich context for wide event logging.

Usage:
    from app.utils.errors import AppError, create_error

    # Raise with full context
    raise create_error(
        message="Payment failed",
        why="Card declined by issuer",
        fix="Try another card or contact your bank",
        status_code=402,
        provider="stripe",
        charge_id="ch_abc123",
    )

    # The AppError exception handler in app_factory.py sets the structured
    # error onto the wide event so it appears in the final log.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppError(Exception):
    """Structured application error with context for debugging and wide events."""

    message: str
    why: str = ""
    fix: str = ""
    status_code: int = 500
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"message": self.message}
        if self.why:
            d["why"] = self.why
        if self.fix:
            d["fix"] = self.fix
        d.update(self.meta)
        return d


def create_error(
    message: str,
    why: str = "",
    fix: str = "",
    status_code: int = 500,
    **meta: Any,
) -> AppError:
    """Create a structured AppError with optional context metadata."""
    return AppError(
        message=message,
        why=why,
        fix=fix,
        status_code=status_code,
        meta=meta,
    )


__all__ = ["AppError", "create_error"]
