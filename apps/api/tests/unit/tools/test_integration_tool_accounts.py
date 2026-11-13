"""connect_integration and check_integrations_status on integrations that hold several accounts."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest

from app.agents.tools.integration_tool import check_integrations_status, connect_integration
from app.constants.integrations import MAX_ACCOUNTS_PER_INTEGRATION, ConnectMode
from app.models.integration_models import IntegrationAccountStatus
from tests.helpers import captured_wide_event
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
            patch(f"{MODULE}.current_stream_writer", return_value=MagicMock()),
            patch(
                "app.config.oauth_config.OAUTH_INTEGRATIONS",
                [
                    _integration("gmail", "Gmail", composio=True),
                    _integration("posthog", "PostHog", composio=False),
                ],
            ),
            patch(
                "app.services.integrations.connect_steps.check_integration_status",
                new_callable=AsyncMock,
            ) as check,
            patch(
                "app.services.integrations.connect_steps.get_account_record", new_callable=AsyncMock
            ) as record,
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
            "✅ Gmail is already connected (ca_1@acme.com, Work). If the user wants another "
            "account, call connect_integration with mode='add_account'; if you're not sure "
            "they do, ask them."
        )
        record.assert_awaited_once_with(FAKE_USER_ID, "gmail")
        request.assert_not_awaited()

    async def test_a_connected_integration_with_no_account_record_lists_none(
        self, seams: tuple[AsyncMock, AsyncMock, AsyncMock]
    ) -> None:
        _, record, _ = seams
        record.return_value = None

        async with captured_wide_event() as event:
            result = await self._connect("gmail")

        assert result == (
            "✅ Gmail is already connected. If the user wants another account, call "
            "connect_integration with mode='add_account'; if you're not sure they do, ask them."
        )
        assert event["tool"] == {
            "name": "connect_integration",
            "action": "connect",
            "mode": "connect",
        }

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
            "gmail", "Gmail", FAKE_USER_ID, mode=ConnectMode.ADD_ACCOUNT, account=None
        )

    @pytest.mark.parametrize("last", ["connected", "expired"])
    async def test_add_account_stops_at_the_account_cap(
        self, seams: tuple[AsyncMock, AsyncMock, AsyncMock], last: IntegrationAccountStatus
    ) -> None:
        """An expired account counts: it comes back by reconnecting, not by adding."""
        _, record, request = seams
        statuses = ["connected"] * (MAX_ACCOUNTS_PER_INTEGRATION - 1) + [last]
        record.return_value = make_integration_record(
            *(make_integration_account(f"ca_{i}", st) for i, st in enumerate(statuses)),
            user_id=FAKE_USER_ID,
        )

        result = await self._connect("gmail", "add_account")

        assert result == (
            f"Gmail already has {MAX_ACCOUNTS_PER_INTEGRATION} accounts, the most allowed. "
            "One must be disconnected (disconnect_integration) or, if expired, reconnected "
            "(mode='reconnect') first."
        )
        request.assert_not_awaited()

    async def test_add_account_on_an_unconnected_integration_is_a_first_connect(
        self, seams: tuple[AsyncMock, AsyncMock, AsyncMock]
    ) -> None:
        check, record, request = seams
        check.return_value = False

        await self._connect("gmail", "add_account")

        request.assert_awaited_once_with(
            "gmail", "Gmail", FAKE_USER_ID, mode=ConnectMode.CONNECT, account=None
        )
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


class TestReconnectMode:
    """A reconnect signs an expired account back in place; it never adds one."""

    @pytest.fixture
    def seams(self) -> Iterator[tuple[AsyncMock, AsyncMock]]:
        with (
            patch(f"{MODULE}.current_stream_writer", return_value=MagicMock()),
            patch(
                "app.config.oauth_config.OAUTH_INTEGRATIONS",
                [
                    _integration("gmail", "Gmail", composio=True),
                    _integration("posthog", "PostHog", composio=False),
                ],
            ),
            patch(
                "app.services.integrations.connect_steps.get_account_record", new_callable=AsyncMock
            ) as record,
            patch(
                f"{MODULE}.request_integration_connection",
                new_callable=AsyncMock,
                return_value="card shown",
            ) as request,
        ):
            yield record, request

    @staticmethod
    async def _reconnect(integration_id: str, account: str | None = None) -> str:
        args: dict[str, object] = {"integration_ids": [integration_id], "mode": "reconnect"}
        if account is not None:
            args["account"] = account
        return await connect_integration.ainvoke(args, config=_cfg())

    async def test_the_one_expired_account_is_the_one_signed_back_in(
        self, seams: tuple[AsyncMock, AsyncMock]
    ) -> None:
        record, request = seams
        dead = make_integration_account("ca_2", "expired")
        record.return_value = make_integration_record(
            make_integration_account("ca_1"), dead, user_id=FAKE_USER_ID
        )

        assert await self._reconnect("gmail") == "card shown"
        request.assert_awaited_once_with(
            "gmail", "Gmail", FAKE_USER_ID, mode=ConnectMode.RECONNECT, account=dead
        )
        record.assert_awaited_once_with(FAKE_USER_ID, "gmail")

    async def test_a_named_expired_account_is_the_one_signed_back_in(
        self, seams: tuple[AsyncMock, AsyncMock]
    ) -> None:
        record, request = seams
        work = make_integration_account("ca_2", "expired", nickname="Work")
        record.return_value = make_integration_record(
            make_integration_account("ca_1", "expired"), work, user_id=FAKE_USER_ID
        )

        assert await self._reconnect("gmail", "work") == "card shown"
        request.assert_awaited_once_with(
            "gmail", "Gmail", FAKE_USER_ID, mode=ConnectMode.RECONNECT, account=work
        )

    @pytest.mark.parametrize(
        ("account", "statuses", "answer"),
        [
            (
                None,
                ["expired", "expired"],
                "Several Gmail accounts lost their connection (ca_0@acme.com, ca_1@acme.com). "
                "Ask the user which to reconnect, then pass it as account.",
            ),
            (
                None,
                ["connected", "connected"],
                "✅ Every Gmail account is connected and working (ca_0@acme.com, ca_1@acme.com), "
                "so there is nothing to reconnect. To add another, use mode='add_account'.",
            ),
            (
                "ca_0@acme.com",
                ["connected", "expired"],
                "✅ Gmail account ca_0@acme.com is connected and working.",
            ),
            (
                "Personal",
                ["connected", "expired"],
                "No Gmail account is named 'Personal'. Its accounts: ca_0@acme.com, ca_1@acme.com.",
            ),
        ],
        ids=["several_expired", "none_expired", "named_working", "unknown_name"],
    )
    async def test_no_card_starts_without_one_expired_account_to_sign_back_in(
        self,
        seams: tuple[AsyncMock, AsyncMock],
        account: str | None,
        statuses: list[IntegrationAccountStatus],
        answer: str,
    ) -> None:
        record, request = seams
        record.return_value = make_integration_record(
            *(make_integration_account(f"ca_{i}", st) for i, st in enumerate(statuses)),
            user_id=FAKE_USER_ID,
        )

        assert await self._reconnect("gmail", account) == answer
        request.assert_not_awaited()

    async def test_an_integration_never_connected_gets_a_first_connect(
        self, seams: tuple[AsyncMock, AsyncMock]
    ) -> None:
        record, request = seams
        record.return_value = None

        await self._reconnect("gmail")

        request.assert_awaited_once_with(
            "gmail", "Gmail", FAKE_USER_ID, mode=ConnectMode.CONNECT, account=None
        )

    async def test_a_single_connection_integration_reconnects_as_a_whole(
        self, seams: tuple[AsyncMock, AsyncMock]
    ) -> None:
        record, request = seams

        await self._reconnect("posthog")

        request.assert_awaited_once_with(
            "posthog", "PostHog", FAKE_USER_ID, mode=ConnectMode.RECONNECT, account=None
        )
        record.assert_not_awaited()


class TestCheckIntegrationsStatusAccounts:
    async def test_a_composio_integration_with_no_account_record_lists_no_accounts(self) -> None:
        with (
            patch(f"{MODULE}.check_single_integration_status", AsyncMock(return_value=True)),
            patch(
                "app.config.oauth_config.OAUTH_INTEGRATIONS",
                [_integration("gmail", "Gmail", composio=True)],
            ),
            patch(f"{MODULE}.get_account_record", AsyncMock(return_value=None)),
        ):
            result = await check_integrations_status.ainvoke(
                {"integration_names": ["gmail"]}, config=_cfg()
            )

        assert result == "Gmail: ✅ Connected"

    async def test_a_multi_account_integration_reports_each_account(self) -> None:
        record = make_integration_record(
            make_integration_account("ca_1"),
            make_integration_account("ca_2", "expired", nickname="Work"),
            user_id=FAKE_USER_ID,
        )
        with (
            patch(f"{MODULE}.check_single_integration_status", AsyncMock(return_value=True)),
            patch(
                "app.config.oauth_config.OAUTH_INTEGRATIONS",
                [_integration("gmail", "Gmail", composio=True)],
            ),
            patch(f"{MODULE}.get_account_record", AsyncMock(return_value=record)) as lookup,
        ):
            result = await check_integrations_status.ainvoke(
                {"integration_names": ["gmail"]}, config=_cfg()
            )

        assert result == (
            'Gmail: ✅ Connected; accounts: "ca_1@acme.com" (id ca_1, default), '
            '"Work" or "ca_2@acme.com" (id ca_2, expired)'
        )
        lookup.assert_awaited_once_with(FAKE_USER_ID, "gmail")
