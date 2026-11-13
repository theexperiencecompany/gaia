"""The coupon codes the clients advertise, owned by server settings."""

from app.config.settings import settings
from app.models.payment_models import DiscountCodesResponse


def get_discount_codes() -> DiscountCodesResponse:
    """Return the configured codes; the Dodo coupon each names is the authority on its terms."""
    return DiscountCodesResponse(founder_letter=settings.FOUNDER_LETTER_DISCOUNT_CODE)
