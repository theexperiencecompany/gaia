"""One brief, opened from the email image, the chat link or the Briefings list.

The repository is faked; the route, its owner scoping and its analytics run for real.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from app.models.briefing_models import BriefingModel, BriefingPayload
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingOpened
from tests.conftest import FAKE_USER

BASE = "/api/v1/briefings"
MODULE = "app.api.v1.endpoints.briefings"


def _brief(*, opened: bool) -> BriefingModel:
    return BriefingModel(
        id="brief_abc123",
        user_id=FAKE_USER.user_id,
        date="2026-10-14",
        kind="daily",
        payload=BriefingPayload(
            kicker="THE MORNING BRIEF",
            date="2026-10-14",
            headline="Two replies need you",
            lede="Priya and Dhruv.",
            mood="packed",
            caption="Onward.",
        ),
        edition_image_url="https://cdn.example/brief.png",
        opened_at=MagicMock() if opened else None,
    )


async def test_opening_a_brief_returns_it_marks_it_opened_and_reports_it_once(
    client: AsyncClient,
) -> None:
    unopened, opened = _brief(opened=False), _brief(opened=True)
    with (
        patch(f"{MODULE}.briefing_repository.get", AsyncMock(return_value=unopened)) as get,
        patch(f"{MODULE}.briefing_repository.mark_opened", AsyncMock(return_value=opened)),
        patch(f"{MODULE}.capture") as capture,
    ):
        response = await client.get(f"{BASE}/brief_abc123")

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["edition_image_url"]) == (
        "brief_abc123",
        "https://cdn.example/brief.png",
    )
    get.assert_awaited_once_with("brief_abc123", user_id=FAKE_USER.user_id)
    capture.assert_called_once_with(UserId(FAKE_USER.user_id), BriefingOpened(kind="daily"))


async def test_reopening_a_brief_reports_nothing(client: AsyncClient) -> None:
    with (
        patch(f"{MODULE}.briefing_repository.get", AsyncMock(return_value=_brief(opened=True))),
        patch(f"{MODULE}.briefing_repository.mark_opened", AsyncMock()) as mark,
        patch(f"{MODULE}.capture") as capture,
    ):
        response = await client.get(f"{BASE}/brief_abc123")

    assert response.status_code == 200
    mark.assert_not_awaited()
    capture.assert_not_called()


async def test_someone_elses_or_a_missing_brief_is_a_404(client: AsyncClient) -> None:
    with patch(f"{MODULE}.briefing_repository.get", AsyncMock(return_value=None)):
        response = await client.get(f"{BASE}/brief_nope")

    assert response.status_code == 404
