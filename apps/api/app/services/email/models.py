"""Provider-agnostic message model for outbound platform email."""

from pydantic import BaseModel


class EmailRejectedError(Exception):
    """The provider refused the message for what it is (an address, a domain, the account); sending it again will not change that."""


class EmailMessage(BaseModel):
    """One outbound email, provider-agnostic; headers carry e.g. List-Unsubscribe."""

    sender: str
    to: list[str]
    subject: str
    html: str
    reply_to: str | None = None
    headers: dict[str, str] | None = None
    idempotency_key: str | None = None
