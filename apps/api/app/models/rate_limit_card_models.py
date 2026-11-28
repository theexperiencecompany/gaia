"""The rate_limit_data card's payload: the limit a call ran into, rendered inline in the chat."""

from app.schemas.common import ResponseModel


class RateLimitCardData(ResponseModel):
    """A rate, budget or cap limit; message, when set, replaces the card's generic copy."""

    feature: str
    plan_required: str | None
    reset_time: str | None
    current_plan: str
    message: str | None = None
