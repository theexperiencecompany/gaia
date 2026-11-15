"""A Dodo discount found by its code: Dodo only lists discounts, so a found (or missing) code is cached."""

import asyncio

from dodopayments import DodoPayments
from dodopayments.types import Discount
from pydantic import BaseModel

from app.constants.cache import DISCOUNT_BY_CODE_CACHE_PREFIX, DISCOUNT_BY_CODE_CACHE_TTL
from app.constants.payments import DISCOUNT_LIST_PAGE_SIZE, DISCOUNT_LOOKUP_MAX_PAGES
from app.db.redis import redis_cache
from shared.py.wide_events import log


class DiscountByCode(BaseModel):
    """What Dodo answered for a code: its discount, or None when no discount carries it."""

    discount: Discount | None


async def _scan_for(client: DodoPayments, code: str) -> Discount | None:
    for page_number in range(DISCOUNT_LOOKUP_MAX_PAGES):
        page = await asyncio.to_thread(
            client.discounts.list, page_number=page_number, page_size=DISCOUNT_LIST_PAGE_SIZE
        )
        found = next((discount for discount in page.items if discount.code == code), None)
        if found is not None or len(page.items) < DISCOUNT_LIST_PAGE_SIZE:
            return found
    log.warning("Discount lookup gave up before reaching the end of Dodo's list", code=code)
    return None


async def find_discount(client: DodoPayments, code: str) -> Discount | None:
    """Return the Dodo discount whose code this is, or None when Dodo has none."""
    key = f"{DISCOUNT_BY_CODE_CACHE_PREFIX}{code}"
    cached = await redis_cache.get(key, model=DiscountByCode)
    if cached is not None:
        return cached.discount
    found = await _scan_for(client, code)
    await redis_cache.set(key, DiscountByCode(discount=found), ttl=DISCOUNT_BY_CODE_CACHE_TTL)
    return found
