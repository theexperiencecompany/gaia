"""Endpoint tests for /api/v1/triggers/options.

Pins the paging/search contract of the route: page and search are
declared query parameters (so they reach the generated client types) and are
handed to the handler explicitly, not scraped from the raw query string.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from app.constants.general import MAX_PAGE_NUMBER
from app.models.trigger_config import TriggerOption, TriggerOptionsQuery
from tests.conftest import FAKE_USER

TRIGGERS_ENDPOINT = "app.api.v1.endpoints.triggers"
USER_ID = FAKE_USER.user_id
OPTIONS_URL = "/api/v1/triggers/options?integration_id=github&trigger_slug=github_commit_event&field_name=repo"


def _handler(options: list[TriggerOption]) -> MagicMock:
    handler = MagicMock()
    handler.get_config_options = AsyncMock(return_value=options)
    return handler


class TestGetTriggerOptions:
    """GET /api/v1/triggers/options."""

    async def test_page_and_search_reach_the_handler(self, client: AsyncClient) -> None:
        handler = _handler([TriggerOption(value="owner/repo", label="owner/repo")])
        with patch(f"{TRIGGERS_ENDPOINT}.get_handler_by_name", return_value=handler) as get_handler:
            resp = await client.get(f"{OPTIONS_URL}&page=3&search=repo")

        assert resp.status_code == 200
        get_handler.assert_called_once_with("github_commit_event")
        assert resp.json() == {"options": [{"value": "owner/repo", "label": "owner/repo"}]}
        handler.get_config_options.assert_awaited_once_with(
            TriggerOptionsQuery(
                trigger_name="github_commit_event",
                field_name="repo",
                user_id=USER_ID,
                integration_id="github",
                parent_ids=None,
                page=3,
                search="repo",
            )
        )

    async def test_page_and_search_default_when_omitted(self, client: AsyncClient) -> None:
        handler = _handler([])
        with patch(f"{TRIGGERS_ENDPOINT}.get_handler_by_name", return_value=handler):
            resp = await client.get(f"{OPTIONS_URL}&parent_values=sheet-1, sheet-2,")

        assert resp.status_code == 200
        handler.get_config_options.assert_awaited_once_with(
            TriggerOptionsQuery(
                trigger_name="github_commit_event",
                field_name="repo",
                user_id=USER_ID,
                integration_id="github",
                parent_ids=["sheet-1", "sheet-2"],
                page=1,
                search="",
            )
        )

    async def test_page_below_one_returns_422(self, client: AsyncClient) -> None:
        with patch(f"{TRIGGERS_ENDPOINT}.get_handler_by_name") as get_handler:
            resp = await client.get(f"{OPTIONS_URL}&page=0")

        assert resp.status_code == 422
        get_handler.assert_not_called()

    async def test_page_over_max_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"{OPTIONS_URL}&page={MAX_PAGE_NUMBER + 1}")

        assert resp.status_code == 422

    async def test_unknown_trigger_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{TRIGGERS_ENDPOINT}.get_handler_by_name", return_value=None):
            resp = await client.get(OPTIONS_URL)

        assert resp.status_code == 404

    async def test_returns_401_without_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(OPTIONS_URL)

        assert resp.status_code == 401
