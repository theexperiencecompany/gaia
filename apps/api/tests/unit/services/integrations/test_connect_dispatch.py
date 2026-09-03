"""Unit tests for the shared connect dispatch and the provider registry.

This is the single place a transport is chosen, for both the authenticated
endpoint and the login-free connect-link path. The behaviour that matters is
that every registered transport is reachable, an unregistered one fails
loudly, no transport can leak an exception to the caller, and the context each
transport receives carries the caller's arguments unchanged — a dropped field
here is a connect that fails for a reason the user cannot act on.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.models.cli_config import CliAuthSpec, CliConfig
from app.schemas.integrations.responses import CliConnectDetail, ConnectIntegrationResponse
from app.services.analytics_service import AnalyticsEvents
from app.services.cli.connect import CliConnectOutcome
from app.services.integrations import connect_dispatch
from app.services.integrations.providers import (
    CliIntegrationProvider,
    ComposioIntegrationProvider,
    ConnectContext,
    IntegrationProvider,
    McpIntegrationProvider,
    SelfIntegrationProvider,
    get_provider,
    register_provider,
)
from tests.helpers import captured_wide_event

USER = "user-1"


def _resolved(
    managed_by: str = "mcp",
    *,
    source: str = "platform",
    available: bool = True,
    provider: str | None = "acme",
    cli_config: CliConfig | None = None,
) -> MagicMock:
    resolved = MagicMock()
    resolved.managed_by = managed_by
    resolved.source = source
    resolved.name = "Acme"
    resolved.requires_auth = False
    resolved.cli_config = cli_config
    resolved.mcp_config = MagicMock(server_url="https://mcp.example.test")
    if source == "platform":
        resolved.platform_integration = MagicMock(available=available, provider=provider)
    else:
        resolved.platform_integration = None
    return resolved


def _resolver(catalog: dict[str, MagicMock]) -> AsyncMock:
    """A resolver that answers for the ids it was given and ``None`` otherwise.

    Keyed rather than constant so a dispatch that looked up the wrong id
    resolves nothing — exactly what would happen against the real catalog.
    """
    return AsyncMock(side_effect=lambda integration_id: catalog.get(integration_id))


def _registry(managed_by: str, provider: IntegrationProvider | MagicMock) -> MagicMock:
    """A ``get_provider`` stub that serves exactly one transport.

    The registry is keyed on ``managed_by``; looking the wrong key up in
    production yields ``None`` and the connect is refused, so the stub must
    behave the same way rather than answering every key alike.
    """
    return MagicMock(side_effect=lambda key: provider if key == managed_by else None)


def _provider_returning(response: ConnectIntegrationResponse) -> MagicMock:
    provider = MagicMock()
    provider.connect = AsyncMock(return_value=response)
    return provider


@pytest.fixture
def restored_registry():
    """Put the real transports back after a test registers over one.

    ``_PROVIDERS`` is process-wide, so a stub left behind would silently serve
    every later test in the session.
    """
    original = {
        managed_by: get_provider(managed_by) for managed_by in ("mcp", "composio", "self", "cli")
    }
    yield
    for provider in original.values():
        if provider is not None:
            register_provider(provider)


class TestProviderRegistry:
    @pytest.mark.parametrize(
        ("managed_by", "expected"),
        [
            ("mcp", McpIntegrationProvider),
            ("composio", ComposioIntegrationProvider),
            ("self", SelfIntegrationProvider),
            ("cli", CliIntegrationProvider),
        ],
    )
    def test_every_connectable_transport_is_registered(self, managed_by, expected):
        assert isinstance(get_provider(managed_by), expected)

    def test_internal_integrations_have_no_provider(self):
        # They are always on and have nothing to connect; the dispatch turns
        # this into a clear error rather than a crash.
        assert get_provider("internal") is None

    def test_registering_a_transport_is_what_makes_it_reachable(self, restored_registry):
        # Registration is the whole mechanism: a registry that stored anything
        # but the provider leaves the dispatch with nothing to call, and every
        # entry point refuses a transport that is in fact implemented.
        replacement = CliIntegrationProvider()
        register_provider(replacement)
        assert get_provider("cli") is replacement


class TestDispatch:
    async def test_unknown_integration_returns_none_for_a_404(self):
        with patch.object(
            connect_dispatch.IntegrationResolver, "resolve", _resolver({"known": _resolved()})
        ):
            assert await connect_dispatch.initiate_integration_connection(USER, "nope") is None

    async def test_unavailable_platform_integration_is_refused_by_name(self):
        # The user sees this string on the integration card, so it has to name
        # the integration they clicked rather than fail anonymously.
        with patch.object(
            connect_dispatch.IntegrationResolver,
            "resolve",
            _resolver({"acme": _resolved(available=False)}),
        ):
            result = await connect_dispatch.initiate_integration_connection(USER, "acme")
        assert result is not None
        assert result.status == "error"
        assert result.error == "Integration acme is not available yet"
        assert result.name == "Acme"

    async def test_transport_without_a_provider_is_reported_with_the_transport_name(self):
        with patch.object(
            connect_dispatch.IntegrationResolver,
            "resolve",
            _resolver({"todos": _resolved(managed_by="internal")}),
        ):
            result = await connect_dispatch.initiate_integration_connection(USER, "todos")
        assert result is not None
        assert result.status == "error"
        assert result.error == "Unsupported integration type: internal"

    async def test_provider_exceptions_never_escape_and_are_recorded(self):
        # The endpoint returns this straight to a client; an unhandled exception
        # here would be a 500 for something as ordinary as a dead MCP server.
        # What the user is told names the integration and what to do; the raw
        # upstream text stays on the wide event, which is the only place the
        # cause survives and the only place it is useful.
        provider = MagicMock()
        provider.connect = AsyncMock(side_effect=RuntimeError("upstream exploded"))
        with (
            patch.object(
                connect_dispatch.IntegrationResolver, "resolve", _resolver({"x": _resolved()})
            ),
            patch.object(connect_dispatch, "get_provider", _registry("mcp", provider)),
        ):
            async with captured_wide_event() as event:
                result = await connect_dispatch.initiate_integration_connection(USER, "x")

        assert result is not None
        assert result.status == "error"
        assert result.error == (
            "Something went wrong connecting Acme. This is usually temporary; try again in a moment."
        )
        (failure,) = event["errors"]
        assert failure == {
            "msg": f"{LogTag.INTEGRATION} Failed to initiate connection",
            "integration_id": "x",
            "user_id": USER,
            "error": "upstream exploded",
            "error_type": "RuntimeError",
        }

    async def test_a_completed_connection_is_recorded_once_with_its_transport(self):
        provider = _provider_returning(
            ConnectIntegrationResponse(status="connected", integration_id="x", name="Acme")
        )
        with (
            patch.object(
                connect_dispatch.IntegrationResolver, "resolve", _resolver({"x": _resolved()})
            ),
            patch.object(connect_dispatch, "get_provider", _registry("mcp", provider)),
            patch.object(connect_dispatch, "capture_context_event") as capture,
        ):
            await connect_dispatch.initiate_integration_connection(USER, "x")
        # The analytics funnel is grouped by transport; the property names are
        # the schema PostHog joins on, so neither may drift.
        capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "x", "managed_by": "mcp"},
        )

    async def test_a_pending_connection_is_not_recorded_as_connected(self):
        provider = _provider_returning(
            ConnectIntegrationResponse(status="pending", integration_id="x", name="Acme")
        )
        with (
            patch.object(
                connect_dispatch.IntegrationResolver, "resolve", _resolver({"x": _resolved()})
            ),
            patch.object(connect_dispatch, "get_provider", _registry("mcp", provider)),
            patch.object(connect_dispatch, "capture_context_event") as capture,
        ):
            await connect_dispatch.initiate_integration_connection(USER, "x")
        capture.assert_not_called()

    async def test_the_context_carries_every_caller_argument_to_the_transport(self):
        # The transports read this and nothing else: a dropped secret sends the
        # user back to a token dialog that already has their token, and a
        # dropped redirect path returns them to the wrong page after OAuth.
        resolved = _resolved()
        provider = _provider_returning(
            ConnectIntegrationResponse(status="pending", integration_id="x", name="Acme")
        )
        with (
            patch.object(
                connect_dispatch.IntegrationResolver, "resolve", _resolver({"x": resolved})
            ),
            patch.object(connect_dispatch, "get_provider", _registry("mcp", provider)),
        ):
            await connect_dispatch.initiate_integration_connection(
                USER,
                "x",
                user_email="user@example.test",
                redirect_path="/chat/42",
                bearer_token="paste-me",
            )
        assert provider.connect.await_args.args == (
            ConnectContext(
                user_id=USER,
                integration_id="x",
                resolved=resolved,
                redirect_path="/chat/42",
                user_email="user@example.test",
                secret="paste-me",
            ),
        )

    async def test_a_bare_connect_returns_the_user_to_the_integrations_page(self):
        # The login-free connect-link path calls with neither argument: the
        # redirect has to land somewhere real, and an unknown email must stay
        # empty rather than become a bogus OAuth login hint.
        resolved = _resolved()
        provider = _provider_returning(
            ConnectIntegrationResponse(status="pending", integration_id="x", name="Acme")
        )
        with (
            patch.object(
                connect_dispatch.IntegrationResolver, "resolve", _resolver({"x": resolved})
            ),
            patch.object(connect_dispatch, "get_provider", _registry("mcp", provider)),
        ):
            await connect_dispatch.initiate_integration_connection(USER, "x")
        ctx: ConnectContext = provider.connect.await_args.args[0]
        assert ctx.redirect_path == "/integrations"
        assert ctx.user_email == ""
        assert ctx.secret is None


class TestDispatchWideEvent:
    """The wide event is how a failed connect is diagnosed in production.

    Nothing else records which user asked for which integration, or how the
    attempt ended, so a renamed key or a dropped namespace is an outage that
    cannot be investigated afterwards.
    """

    async def test_the_event_identifies_the_user_the_integration_and_the_outcome(self):
        provider = _provider_returning(
            ConnectIntegrationResponse(status="pending", integration_id="x", name="Acme")
        )
        with (
            patch.object(
                connect_dispatch.IntegrationResolver, "resolve", _resolver({"x": _resolved()})
            ),
            patch.object(connect_dispatch, "get_provider", _registry("mcp", provider)),
        ):
            async with captured_wide_event() as event:
                await connect_dispatch.initiate_integration_connection(USER, "x")
                # Read inside the boundary: closing it stamps its own
                # ``outcome`` over whatever the dispatch recorded.
                outcome = event["outcome"]

        assert event["user"] == {"id": USER}
        assert event["integration"] == {"id": "x", "managed_by": "mcp", "source": "platform"}
        assert outcome == "pending"

    async def test_a_refused_connect_is_recorded_as_an_error_outcome(self):
        with patch.object(
            connect_dispatch.IntegrationResolver,
            "resolve",
            _resolver({"acme": _resolved(available=False)}),
        ):
            async with captured_wide_event() as event:
                await connect_dispatch.initiate_integration_connection(USER, "acme")
                outcome = event["outcome"]

        assert outcome == "error"


class TestCliProvider:
    CONFIG = CliConfig(
        command="link-cli",
        install_command="npm install x",
        auth=CliAuthSpec(
            kind="device",
            login_command="link-cli auth login",
            verify_command="link-cli auth status",
        ),
    )

    def _ctx(self, cli_config: CliConfig | None, *, secret: str | None = None) -> ConnectContext:
        return ConnectContext(
            user_id=USER,
            integration_id="stripe_link",
            resolved=_resolved(managed_by="cli", cli_config=cli_config),
            redirect_path="/integrations",
            secret=secret,
        )

    async def test_missing_configuration_is_an_error_naming_the_integration(self):
        # Only reachable via a hand-written Mongo document, so the message has
        # to say which document is wrong.
        result = await CliIntegrationProvider().connect(self._ctx(None))
        assert result.status == "error"
        assert result.error == "stripe_link has no CLI configuration"

    async def test_the_state_machine_is_driven_for_this_user_and_integration(self):
        # advance() is the whole transport; the pasted token is the credential
        # the user just typed, and driving the wrong (user, integration, config)
        # would authenticate someone else's sandbox.
        outcome = CliConnectOutcome(phase="connected", message="Signed in")
        with patch(
            "app.services.integrations.providers.cli_provider.advance",
            AsyncMock(return_value=outcome),
        ) as advance:
            await CliIntegrationProvider().connect(self._ctx(self.CONFIG, secret="paste-me"))
        advance.assert_awaited_once_with(USER, "stripe_link", self.CONFIG, token="paste-me")

    async def test_an_empty_paste_is_not_forwarded_as_a_token(self):
        # The connect dialog submits an empty field on the first poll; an empty
        # string is not a credential and must not be written to the CLI's HOME.
        outcome = CliConnectOutcome(phase="needs_token")
        with patch(
            "app.services.integrations.providers.cli_provider.advance",
            AsyncMock(return_value=outcome),
        ) as advance:
            await CliIntegrationProvider().connect(self._ctx(self.CONFIG, secret=""))
        assert advance.await_args.kwargs["token"] is None

    @pytest.mark.parametrize(
        ("phase", "expected_status"),
        [
            ("installing", "pending"),
            ("awaiting_approval", "pending"),
            ("needs_token", "pending"),
            ("connected", "connected"),
        ],
    )
    async def test_a_phase_short_of_failure_is_progress_not_an_error(self, phase, expected_status):
        # The client polls while `pending` and stops on `error`. Reporting
        # progress as an error would abandon an install that was going fine,
        # and the instructions are what the user needs to act on meanwhile.
        outcome = CliConnectOutcome(
            phase=phase, message="Installing link-cli", instructions="Visit https://link.test/abc"
        )
        with patch(
            "app.services.integrations.providers.cli_provider.advance",
            AsyncMock(return_value=outcome),
        ):
            result = await CliIntegrationProvider().connect(self._ctx(self.CONFIG))
        assert result.status == expected_status
        assert result.message == "Installing link-cli"
        assert result.error is None
        assert result.cli == CliConnectDetail(
            phase=phase, instructions="Visit https://link.test/abc"
        )

    async def test_a_failed_phase_surfaces_the_reason_as_the_error(self):
        outcome = CliConnectOutcome(phase="failed", message="npm install exited 1")
        with patch(
            "app.services.integrations.providers.cli_provider.advance",
            AsyncMock(return_value=outcome),
        ):
            result = await CliIntegrationProvider().connect(self._ctx(self.CONFIG))
        assert result.status == "error"
        assert result.error == "npm install exited 1"
        assert result.message == "npm install exited 1"
        assert result.cli == CliConnectDetail(phase="failed")

    async def test_token_prompt_copy_is_carried_to_the_client(self):
        outcome = CliConnectOutcome(
            phase="needs_token", token_label="GitHub token", token_help_url="https://gh.test/t"
        )
        with patch(
            "app.services.integrations.providers.cli_provider.advance",
            AsyncMock(return_value=outcome),
        ):
            result = await CliIntegrationProvider().connect(self._ctx(self.CONFIG))
        assert result.cli is not None
        assert result.cli.token_label == "GitHub token"
        assert result.cli.token_help_url == "https://gh.test/t"
