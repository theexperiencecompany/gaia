"""Finding a Dodo discount by its code: Dodo only lists discounts, so each answer is cached."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, call

from dodopayments.types import Discount
import pytest
import time_machine

from app.constants.cache import DISCOUNT_BY_CODE_CACHE_PREFIX
from app.constants.payments import DISCOUNT_LIST_PAGE_SIZE, DISCOUNT_LOOKUP_MAX_PAGES
from app.db.redis import AsyncRedisCommands
from app.services.payments import discount_lookup
from app.services.payments.discount_lookup import find_discount
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.usefixtures("fake_redis")


def _discount(code: str) -> Discount:
    return Discount(
        amount=4000,
        business_id="biz_1",
        code=code,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        discount_id=f"dsc_{code}",
        restricted_to=[],
        times_used=0,
        type="percentage",
    )


def _client(*pages: list[Discount]) -> MagicMock:
    client = MagicMock()
    client.discounts.list.side_effect = [SimpleNamespace(items=page) for page in pages]
    return client


async def test_a_code_on_a_later_page_is_found_and_cached(
    fake_redis: AsyncRedisCommands, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Apart from the cache's 3600s default, so the lookup is seen to pass its own TTL.
    monkeypatch.setattr(discount_lookup, "DISCOUNT_BY_CODE_CACHE_TTL", 60)
    full_page = [_discount(f"GIFT{i}") for i in range(DISCOUNT_LIST_PAGE_SIZE)]
    client = _client(full_page, [_discount("FOUNDER")])

    with time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False):
        found = await find_discount(client, "FOUNDER")
        again = await find_discount(client, "FOUNDER")
        ttl = await fake_redis.ttl(f"{DISCOUNT_BY_CODE_CACHE_PREFIX}FOUNDER")

    assert found == again == _discount("FOUNDER")
    assert client.discounts.list.call_args_list == [
        call(page_number=0, page_size=DISCOUNT_LIST_PAGE_SIZE),
        call(page_number=1, page_size=DISCOUNT_LIST_PAGE_SIZE),
    ]
    assert ttl == 60


async def test_a_code_dodo_does_not_have_is_cached_as_missing() -> None:
    client = _client([_discount("OTHER")])

    assert await find_discount(client, "NOPE") is None
    assert await find_discount(client, "NOPE") is None

    assert client.discounts.list.call_count == 1


async def test_a_scan_stops_at_its_page_limit() -> None:
    full_page = [_discount(f"GIFT{i}") for i in range(DISCOUNT_LIST_PAGE_SIZE)]
    client = _client(*([full_page] * DISCOUNT_LOOKUP_MAX_PAGES))

    async with captured_wide_event() as event:
        assert await find_discount(client, "FOUNDER") is None

    assert client.discounts.list.call_count == DISCOUNT_LOOKUP_MAX_PAGES
    assert event["warnings"] == [
        {"msg": "Discount lookup gave up before reaching the end of Dodo's list", "code": "FOUNDER"}
    ]
