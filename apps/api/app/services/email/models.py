"""Provider-agnostic message model for outbound platform email."""

from pydantic import BaseModel


class EmailMessage(BaseModel):
    sender: str
    to: list[str]
    subject: str
    html: str
    reply_to: str | None = None
