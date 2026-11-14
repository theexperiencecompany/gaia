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

from app.constants.error_codes import INTEGRATION_NOT_CONNECTED


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


class IntegrationNotConnectedError(AppError):
    """No connection of an integration can act on this call; only the user can fix it.

    grant_died is True when the call's own grant died just now (a provider 401 after
    the refresh failed, a connected account the provider no longer holds), so the
    stored account must be expired; False when nothing usable was connected.
    integration_name is None when the raiser knows only the id (an MCP tool).
    """

    def __init__(
        self,
        *,
        integration_id: str,
        integration_name: str | None,
        why: str,
        toolkit: str | None = None,
        grant_died: bool = False,
        meta: dict[str, object] | None = None,
    ) -> None:
        name = integration_name or integration_id
        # 403, not 401: a 401 trips the web client's session-expiry interceptor.
        super().__init__(
            message=f"{name} is not connected. Reconnect it to continue.",
            why=why,
            fix=f"Reconnect {name}",
            status_code=403,
            code=INTEGRATION_NOT_CONNECTED,
            # The web keys its reconnect toast on toolkit and starts the connect from integration_id.
            public={"integration_id": integration_id, **({"toolkit": toolkit} if toolkit else {})},
            meta=meta or {},
        )
        self.integration_id = integration_id
        self.integration_name = integration_name
        self.grant_died = grant_died


@dataclass
class EmptyUpdateError(AppError):
    """An update model carried no set fields — a silent no-op write is a bug."""


@dataclass
class RepositoryMisconfiguredError(AppError):
    """A repository subclass is missing required ClassVars (raised at import)."""


@dataclass
class ConversationNotFoundError(AppError):
    """The conversation a write named does not exist for this user."""

    status_code: int = 404


@dataclass
class ConversationAlreadyExistsError(AppError):
    """The conversation a create named already exists for this user."""

    status_code: int = 409


@dataclass
class ConversationIdTakenError(AppError):
    """The conversation id a create named already belongs to another user."""

    status_code: int = 409
    code: str = "conversation_id_taken"


@dataclass
class ConversationEntryNotFoundError(AppError):
    """The log entry a write named is not in the conversation, or is another kind."""

    status_code: int = 404


@dataclass
class UnmigratedConversationError(AppError):
    """A conversation still keeps its messages only in the embedded array the entries migration replaces."""


@dataclass
class ConversationStoreError(AppError):
    """The conversation store failed or kept losing a conditional write; the operation did not happen."""


__all__ = [
    "AppError",
    "ConversationAlreadyExistsError",
    "ConversationIdTakenError",
    "ConversationNotFoundError",
    "ConversationStoreError",
    "EmptyUpdateError",
    "IntegrationNotConnectedError",
    "RepositoryMisconfiguredError",
    "UnmigratedConversationError",
    "create_error",
]
