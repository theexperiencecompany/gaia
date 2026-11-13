"""GET /api/v1/updates: the feed's query contract."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.models.updates_models import UnseenUpdates, UpdateFilter, UpdatesResponse
from tests.conftest import FAKE_USER

READ = "app.api.v1.endpoints.updates.read_updates"
URL = "/api/v1/updates"


@pytest.fixture
def feed():
    with patch(READ, new_callable=AsyncMock) as read:
        read.return_value = UpdatesResponse(updates=[], next_before=None)
        yield read


async def test_the_default_read_is_the_first_page_of_everything(
    client: AsyncClient, feed: AsyncMock
) -> None:
    read = feed

    response = await client.get(URL)

    assert response.status_code == 200
    assert response.json() == {"updates": [], "next_before": None}
    read.assert_awaited_once_with(FAKE_USER.user_id, UpdateFilter.ALL, before=None, limit=30)


async def test_the_filter_cursor_and_limit_reach_the_read(
    client: AsyncClient, feed: AsyncMock
) -> None:
    read = feed

    response = await client.get(
        URL, params={"filter": "needs_you", "before": "2026-11-10T09:00:00Z", "limit": 5}
    )

    assert response.status_code == 200
    read.assert_awaited_once_with(
        FAKE_USER.user_id,
        UpdateFilter.NEEDS_YOU,
        before=datetime(2026, 11, 10, 9, 0, tzinfo=UTC),
        limit=5,
    )


@pytest.mark.parametrize(
    "params", [{"filter": "everything"}, {"limit": 0}, {"limit": 101}, {"before": "yesterday"}]
)
async def test_a_query_the_contract_refuses_is_a_422_that_reads_nothing(
    client: AsyncClient, feed: AsyncMock, params: dict[str, object]
) -> None:
    read = feed

    response = await client.get(URL, params=params)

    assert response.status_code == 422
    read.assert_not_awaited()


async def test_the_feed_is_for_signed_in_users(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.get(URL)

    assert response.status_code == 401


async def test_the_unseen_count_is_read_since_the_instant(client: AsyncClient) -> None:
    with patch(
        "app.api.v1.endpoints.updates.count_unseen_updates", new_callable=AsyncMock
    ) as count:
        count.return_value = UnseenUpdates(count=4)

        response = await client.get(f"{URL}/unseen", params={"since": "2026-11-10T09:00:00Z"})

    assert response.status_code == 200
    assert response.json() == {"count": 4}
    count.assert_awaited_once_with(FAKE_USER.user_id, datetime(2026, 11, 10, 9, 0, tzinfo=UTC))


async def test_the_unseen_count_needs_an_instant(client: AsyncClient) -> None:
    response = await client.get(f"{URL}/unseen")

    assert response.status_code == 422
