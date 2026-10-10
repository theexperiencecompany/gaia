"""connect_integration and check_integrations_status on integrations that hold several accounts."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest

from app.agents.tools.integration_tool import check_integrations_status, connect_integration
from app.constants.integrations import MAX_ACCOUNTS_PER_INTEGRATION, ConnectMode
from app.models.integration_models import IntegrationAccountStatus
from tests.integration_account_factories import make_integration_account, make_integration_record

FAKE_USER_ID = "507f1f77bcf86cd799439011"
MODULE = "app.agents.tools.integration_tool"


def _cfg() -> dict[str, object]:
    return {"configurable": {"user_id": FAKE_USER_ID}}


def _integration(integration_id: str, name: str, *, composio: bool) -> MagicMock:
    integration = MagicMock()
    integration.id = integration_id
    integration.name = name
    integration.short_name = integration_id
    integration.available = True
    integration.composio_config = MagicMock() if composio else None
    return integration


class TestConnectModes:
    """Which connect starts per mode, for an integration that may hold several accounts."""

    @pytest.fixture
    def seams(self) -> Iterator[tuple[AsyncMock, AsyncMock, AsyncMock]]:
        with (
            patch(f"{MODULE}.get_stream_writer", return_value=MagicMock()),
            patch(
                f"{MODULE}.OAUTH_INTEGRATIONS",
                [
                    _integration("gmail", "Gmail", composio=True),
                    _integration("posthog", "PostHog", composio=False),
                ],
            ),
            patch(f"{MODULE}.check_single_integration_status", new_callable=AsyncMock) as check,
            patch(f"{MODULE}.get_account_record", new_callable=AsyncMock) as record,
            patch(
                f"{MODULE}.request_integration_connection",
                new_callable=AsyncMock,
                return_value="card shown",
            ) as request,
        ):
            check.return_value = True
            yield check, record, request

    @staticmethod
    async def _connect(integration_id: str, mode: str | None = None) -> str:
        args: dict[str, object] = {"integration_ids": [integration_id]}
        if mode is not None:
            args["mode"] = mode
        return await connect_integration.ainvoke(args, config=_cfg())

    async def test_connect_on_a_connected_integration_lists_its_accounts_and_points_at_add(
        self, seams: tuple[AsyncMock, AsyncMock, AsyncMock]
    ) -> None:
        _, record, request = seams
        record.return_value = make_integration_record(
            make_integration_account("ca_1"),
            make_integration_account("ca_2", nickname="Work"),
            user_id=FAKE_USER_ID,
        )

        result = await self._connect("gmail")

        assert result == (
            "✅ Gmail is already connected (ca_1@acme.com, Work). To add another account, "
            "call connect_integration with mode='add_account'."
        )
        record.assert_awaited_once_with(FAKE_USER_ID, "gmail")
        request.assert_not_awaited()

    async def test_add_account_on_a_connected_integration_shows_the_add_card(
        self, seams: tuple[AsyncMock, AsyncMock, AsyncMock]
    ) -> None:
        _, record, request = seams
        record.return_value = make_integration_record(
            make_integration_account("ca_1"), user_id=FAKE_USER_ID
        )

        result = await self._connect("gmail", "add_account")

        assert result == "card shown"
        request.assert_awaited_once_with(
            "gmail", "Gmail", FAKE_USER_ID, mode=ConnectMode.ADD_ACCOUNT
        )

    @pytest.mark.parametrize(
        ("statuses", "refused"),
        [
            (["connected"] * MAX_ACCOUNTS_PER_INTEGRATION, True),
            (["connected"] * (MAX_ACCOUNTS_PER_INTEGRATION - 1) + ["expired"], False),
        ],
        ids=["at_cap", "an_expired_one_does_not_count"],
    )
    async def test_add_account_stops_at_the_account_cap(
        self,
        seams: tuple[AsyncMock, AsyncMock, AsyncMock],
        statuses: list[IntegrationAccountStatus],
        refused: bool,
    ) -> None:
        _, record, request = seams
        record.return_value = make_integration_record(
            *(make_integration_account(f"ca_{i}", st) for i, st in enumerate(statuses)),
            user_id=FAKE_USER_ID,
        )

        result = await self._connect("gmail", "add_account")

        if refused:
            assert result == (
                f"Gmail already has {MAX_ACCOUNTS_PER_INTEGRATION} accounts, the most allowed. "
                "One must be disconnected (disconnect_integration) first."
            )
            request.assert_not_awaited()
        else:
            assert result == "card shown"

    async def test_add_account_on_an_unconnected_integration_is_a_first_connect(
        self, seams: tuple[AsyncMock, AsyncMock, AsyncMock]
    ) -> None:
        check, record, request = seams
        check.return_value = False

        await self._connect("gmail", "add_account")

        request.assert_awaited_once_with("gmail", "Gmail", FAKE_USER_ID, mode=ConnectMode.CONNECT)
        record.assert_not_awaited()

    async def test_add_account_on_a_single_connection_integration_is_refused(
        self, seams: tuple[AsyncMock, AsyncMock, AsyncMock]
    ) -> None:
        _, _, request = seams

        result = await self._connect("posthog", "add_account")

        assert result == "PostHog connects a single account; it cannot have several."
        request.assert_not_awaited()

    async def test_an_unknown_mode_is_rejected_by_the_schema(
        self, seams: tuple[AsyncMock, AsyncMock, AsyncMock]
    ) -> None:
        with pytest.raises(ValidationError):
            await self._connect("gmail", "add")


class TestCheckIntegrationsStatusAccounts:
    async def test_a_multi_account_integration_reports_each_account(self) -> None:
        record = make_integration_record(
            make_integration_account("ca_1"),
            make_integration_account("ca_2", "expired", nickname="Work"),
            user_id=FAKE_USER_ID,
        )
        with (
            patch(f"{MODULE}.check_single_integration_status", AsyncMock(return_value=True)),
            patch(
                f"{MODULE}.OAUTH_INTEGRATIONS",
                [_integration("gmail", "Gmail", composio=True)],
            ),
            patch(f"{MODULE}.get_account_record", AsyncMock(return_value=record)) as lookup,
        ):
            result = await check_integrations_status.ainvoke(
                {"integration_names": ["gmail"]}, config=_cfg()
            )

        assert result == (
            'Gmail: ✅ Connected; accounts: "ca_1@acme.com" (primary), '
            '"Work" or "ca_2@acme.com" (expired)'
        )
        lookup.assert_awaited_once_with(FAKE_USER_ID, "gmail")
