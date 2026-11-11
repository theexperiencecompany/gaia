"""Finding a Dodo discount by its code: Dodo only lists discounts, so each answer is cached."""

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from dodopayments.types import Discount
import pytest

from app.constants.cache import DISCOUNT_BY_CODE_CACHE_PREFIX, DISCOUNT_BY_CODE_CACHE_TTL
from app.constants.payments import DISCOUNT_LIST_PAGE_SIZE, DISCOUNT_LOOKUP_MAX_PAGES
from app.services.payments.discount_lookup import DiscountByCode, find_discount

LOOKUP = "app.services.payments.discount_lookup"


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


@pytest.fixture
def cache() -> Iterator[SimpleNamespace]:
    with (
        patch(f"{LOOKUP}.redis_cache.get", AsyncMock(return_value=None)) as get,
        patch(f"{LOOKUP}.redis_cache.set", AsyncMock(return_value=True)) as set_,
    ):
        yield SimpleNamespace(get=get, set=set_)


async def test_a_code_on_a_later_page_is_found_and_cached(cache: SimpleNamespace) -> None:
    full_page = [_discount(f"GIFT{i}") for i in range(DISCOUNT_LIST_PAGE_SIZE)]
    client = _client(full_page, [_discount("FOUNDER")])

    found = await find_discount(client, "FOUNDER")

    assert found == _discount("FOUNDER")
    assert client.discounts.list.call_args_list == [
        call(page_number=0, page_size=DISCOUNT_LIST_PAGE_SIZE),
        call(page_number=1, page_size=DISCOUNT_LIST_PAGE_SIZE),
    ]
    cache.set.assert_awaited_once_with(
        f"{DISCOUNT_BY_CODE_CACHE_PREFIX}FOUNDER",
        DiscountByCode(discount=found),
        ttl=DISCOUNT_BY_CODE_CACHE_TTL,
        model=DiscountByCode,
    )


async def test_a_code_dodo_does_not_have_is_cached_as_missing(cache: SimpleNamespace) -> None:
    client = _client([_discount("OTHER")])

    assert await find_discount(client, "NOPE") is None

    assert cache.set.await_args.args[1] == DiscountByCode(discount=None)


async def test_a_cached_answer_never_asks_dodo(cache: SimpleNamespace) -> None:
    cache.get.return_value = DiscountByCode(discount=_discount("FOUNDER"))
    client = _client()

    assert await find_discount(client, "FOUNDER") == _discount("FOUNDER")

    client.discounts.list.assert_not_called()


async def test_a_scan_stops_at_its_page_limit(cache: SimpleNamespace) -> None:
    full_page = [_discount(f"GIFT{i}") for i in range(DISCOUNT_LIST_PAGE_SIZE)]
    client = _client(*([full_page] * DISCOUNT_LOOKUP_MAX_PAGES))

    with patch(f"{LOOKUP}.log") as log:
        assert await find_discount(client, "FOUNDER") is None

    assert client.discounts.list.call_count == DISCOUNT_LOOKUP_MAX_PAGES
    log.warning.assert_called_once()
