"""Structured application errors with rich context for wide event logging.

An AppError carries two audiences. The message, why, fix and code fields and
the public mapping are the contract the client reads; meta is diagnostic
context for the wide event and never reaches the wire. A provider body, a user
id or str(e) is therefore safe in meta, and putting one in public is a
deliberate decision.

The AppError exception handler in app/core/exception_handlers.py sets the
structured error onto the wide event so it appears in the final log.
"""

from dataclasses import dataclass, field


@dataclass
class AppError(Exception):
    """Structured application error with context for debugging and wide events."""

    message: str
    why: str = ""
    fix: str = ""
    status_code: int = 500
    code: str = ""
    public: dict[str, object] = field(default_factory=dict)
    meta: dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        # The dataclass-generated __init__ never populates Exception.args, so
        # the default Exception.__str__ would return "". Surface the message so
        # f-string logging and any str(exc) callers see a meaningful error.
        return self.message

    def to_dict(self) -> dict[str, object]:
        """Render the wide-event payload: everything the error knows, public or not."""
        d: dict[str, object] = {"message": self.message}
        if self.why:
            d["why"] = self.why
        if self.fix:
            d["fix"] = self.fix
        if self.code:
            d["code"] = self.code
        d.update(self.public)
        d.update(self.meta)
        return d


def create_error(
    message: str,
    why: str = "",
    fix: str = "",
    status_code: int = 500,
    code: str = "",
    public: dict[str, object] | None = None,
    **meta: object,
) -> AppError:
    """Create a structured AppError; keyword extras become wide-event-only meta."""
    return AppError(
        message=message,
        why=why,
        fix=fix,
        status_code=status_code,
        code=code,
        public=dict(public) if public else {},
        meta=meta,
    )


@dataclass
class EmptyUpdateError(AppError):
    """An update model carried no set fields — a silent no-op write is a bug."""


@dataclass
class RepositoryMisconfiguredError(AppError):
    """A repository subclass is missing required ClassVars (raised at import)."""


__all__ = ["AppError", "EmptyUpdateError", "RepositoryMisconfiguredError", "create_error"]
