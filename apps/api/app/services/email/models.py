"""Provider-agnostic message model for outbound platform email."""

from pydantic import BaseModel


class EmailMessage(BaseModel):
    """One outbound email, provider-agnostic; headers carry e.g. List-Unsubscribe."""

    sender: str
    to: list[str]
    subject: str
    html: str
    reply_to: str | None = None
    headers: dict[str, str] | None = None
