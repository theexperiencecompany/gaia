"""The workflow assistant's one-line hint of the integrations the user has connected."""

from unittest.mock import AsyncMock, patch

from app.constants.integrations import IntegrationStatus
from app.schemas.integrations.responses import (
    MyIntegrationItem,
    MyIntegrationsResponse,
    MyIntegrationStatus,
)
from app.services.workflow.knowledge import build_connected_integrations_hint
from tests.factories import make_user_id

MODULE = "app.services.workflow.knowledge"


def _item(integration_id: str, name: str, status: MyIntegrationStatus) -> MyIntegrationItem:
    return MyIntegrationItem(
        id=integration_id,
        name=name,
        description="",
        category="productivity",
        source="platform",
        managed_by="composio",
        status=status,
    )


async def _hint_for(*items: MyIntegrationItem) -> str:
    user_id = make_user_id()
    mine = MyIntegrationsResponse(integrations=list(items), total=len(items))
    with patch(f"{MODULE}.get_my_integrations", AsyncMock(return_value=mine)) as get_mine:
        hint = await build_connected_integrations_hint(user_id)
    get_mine.assert_awaited_once_with(user_id)
    return hint


async def test_the_hint_names_only_the_integrations_that_are_connected() -> None:
    hint = await _hint_for(
        _item("gmail", "Gmail", IntegrationStatus.CONNECTED),
        _item("notion", "Notion", IntegrationStatus.CREATED),
        _item("slack", "Slack", "not_connected"),
        _item("github", "GitHub", IntegrationStatus.CONNECTED),
    )

    assert hint.splitlines()[1] == "Gmail (`gmail`), GitHub (`github`)"


async def test_a_user_with_nothing_connected_reads_none_yet() -> None:
    hint = await _hint_for(_item("notion", "Notion", IntegrationStatus.CREATED))

    assert hint.splitlines()[1] == "(none yet)"
