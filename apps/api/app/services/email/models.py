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
    idempotency_key: str | None = None


class ReferralInviteEmail(BaseModel):
    """A friend's invite as GAIA's domain sends it: under the referrer's name, replies going to them."""

    to: str
    referrer_name: str
    referrer_email: str
    referrer_picture: str | None = None
    price_line: str
    regular_price_line: str
    invite_link: str
    unsubscribe_url: str
