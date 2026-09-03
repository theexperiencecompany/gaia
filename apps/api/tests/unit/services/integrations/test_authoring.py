"""Unit tests for creating an integration from a blueprint.

The authoring path is reachable from a chat tool, so its inputs come from a
model reading a vendor's docs. The tests focus on what that implies: a
malformed blueprint must fail with a message the model can act on, and a
half-created integration must never be left behind.
"""

from __future__ import annotations

from collections.abc import Iterator
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.integration_models import CreateCustomIntegrationRequest
from app.services.integrations.authoring import (
    CliBlueprint,
    McpBlueprint,
    create_integration,
    get_author,
)
from app.services.integrations.authoring.cli_author import CliIntegrationAuthor
from app.services.integrations.authoring.mcp_author import McpIntegrationAuthor

USER = "user-1"
MCP_MODULE = "app.services.integrations.authoring.mcp_author"


def cli_blueprint(**overrides: object) -> CliBlueprint:
    base: dict[str, object] = {
        "name": "GitHub CLI",
        "description": "Work with GitHub from the command line",
        "command": "gh",
        "install_command": "curl -fsSL https://example.test/gh.tgz | tar -xz",
        "capabilities": ["list pull requests", "create issues"],
        "auth_kind": "token",
        "verify_command": "gh auth status",
        "token_env": "GH_TOKEN",
        "token_label": "GitHub token",
    }
    base.update(overrides)
    return CliBlueprint(**base)  # type: ignore[arg-type]  # kwargs dict widens to object; the model validates the real types


def mcp_blueprint(**overrides: object) -> McpBlueprint:
    # Every field deliberately differs from the model's default, so a field the
    # author forgets to forward shows up as the default rather than passing.
    base: dict[str, object] = {
        "name": "Acme",
        "description": "Acme's own MCP server",
        "category": "business",
        "server_url": "https://mcp.example.test",
        "requires_auth": True,
        "auth_type": "bearer",
        "bearer_token": "tok-123",
    }
    base.update(overrides)
    return McpBlueprint(**base)  # type: ignore[arg-type]  # kwargs dict widens to object; the model validates the real types


@contextlib.contextmanager
def mcp_creation(result: dict[str, object]) -> Iterator[SimpleNamespace]:
    """Patch the two boundaries the MCP author delegates to.

    The author adds no logic of its own — it builds a request, gets a client,
    and hands both to the existing custom-MCP creation path — so those two
    calls are the observable behaviour.
    """
    client = MagicMock(name="mcp_client")
    integration = MagicMock(name="integration")
    with (
        patch(f"{MCP_MODULE}.get_mcp_client", AsyncMock(return_value=client)) as get_client,
        patch(
            f"{MCP_MODULE}.create_and_connect_custom_integration",
            AsyncMock(return_value=(integration, result)),
        ) as create,
    ):
        yield SimpleNamespace(
            client=client, integration=integration, get_client=get_client, create=create
        )


class TestAuthorRegistry:
    def test_both_transports_are_authorable(self):
        assert isinstance(get_author("cli"), CliIntegrationAuthor)
        assert get_author("mcp") is not None

    async def test_an_unknown_kind_fails_loudly(self):
        blueprint = MagicMock()
        blueprint.kind = "carrier-pigeon"
        with pytest.raises(ValueError, match="No author registered"):
            await create_integration(USER, blueprint)


class TestCliAuthor:
    async def test_persists_the_integration_and_attaches_it(self):
        with (
            patch("app.services.integrations.authoring.cli_author.integration_repository") as repo,
            patch(
                "app.services.integrations.authoring.cli_author.add_user_integration",
                AsyncMock(),
            ) as attach,
        ):
            repo.create = AsyncMock()
            authored = await create_integration(USER, cli_blueprint())

        repo.create.assert_awaited_once()
        stored = repo.create.await_args.args[0]
        assert stored.managed_by == "cli"
        assert stored.source == "custom"
        assert stored.created_by == USER
        assert stored.cli_config is not None
        assert stored.cli_config.command == "gh"
        attach.assert_awaited_once()
        assert authored.needs_connection is True

    async def test_capabilities_become_the_displayed_tool_list(self):
        # Publishing requires a non-empty tool list, and "one tool that wraps a
        # CLI" tells a user nothing — the capabilities are the real answer.
        with (
            patch("app.services.integrations.authoring.cli_author.integration_repository") as repo,
            patch(
                "app.services.integrations.authoring.cli_author.add_user_integration", AsyncMock()
            ),
        ):
            repo.create = AsyncMock()
            await create_integration(USER, cli_blueprint())

        stored = repo.create.await_args.args[0]
        assert [t.name for t in stored.tools] == ["list pull requests", "create issues"]

    async def test_rolls_back_the_catalog_row_if_attaching_fails(self):
        # Otherwise the marketplace shows an integration that belongs to nobody
        # and that nobody can connect or delete.
        with (
            patch("app.services.integrations.authoring.cli_author.integration_repository") as repo,
            patch(
                "app.services.integrations.authoring.cli_author.add_user_integration",
                AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
        ):
            repo.create = AsyncMock()
            repo.delete = AsyncMock()
            with pytest.raises(RuntimeError):
                await create_integration(USER, cli_blueprint())

        repo.delete.assert_awaited_once()

    async def test_an_incoherent_auth_spec_is_rejected_with_a_usable_message(self):
        # A model that read a vendor's docs badly gets told exactly what is
        # missing so it can retry, rather than a stack trace.
        with pytest.raises(ValueError, match="Invalid CLI configuration"):
            await create_integration(USER, cli_blueprint(auth_kind="device", login_command=None))

    async def test_a_no_auth_cli_still_needs_a_connect_to_install(self):
        with (
            patch("app.services.integrations.authoring.cli_author.integration_repository") as repo,
            patch(
                "app.services.integrations.authoring.cli_author.add_user_integration", AsyncMock()
            ),
        ):
            repo.create = AsyncMock()
            authored = await create_integration(
                USER,
                cli_blueprint(auth_kind="none", token_env=None, token_label=None),
            )
        assert authored.needs_connection is True
        assert repo.create.await_args.args[0].requires_auth is False

    async def test_does_not_touch_the_sandbox(self):
        # Creation is a catalog write. Installing here would make an ordinary
        # chat turn wait on a cold sandbox and an npm install.
        with (
            patch("app.services.integrations.authoring.cli_author.integration_repository") as repo,
            patch(
                "app.services.integrations.authoring.cli_author.add_user_integration", AsyncMock()
            ),
            patch("app.services.cli.runtime.ensure_installed", AsyncMock()) as install,
        ):
            repo.create = AsyncMock()
            await create_integration(USER, cli_blueprint())
        install.assert_not_awaited()


class TestMcpAuthor:
    async def test_an_authored_integration_starts_private(self):
        """Publishing is a separate, deliberate step.

        The request model defaults ``is_public`` to False, so the author does
        not restate it; this is what stops that default silently moving.
        """
        with (
            patch(
                "app.services.integrations.authoring.mcp_author.get_mcp_client",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.services.integrations.authoring.mcp_author.create_and_connect_custom_integration",
                AsyncMock(return_value=(MagicMock(), {"status": "connected"})),
            ) as create,
        ):
            await create_integration(
                USER, McpBlueprint(name="Acme", server_url="https://mcp.example.test")
            )

        assert create.await_args.args[1].is_public is False

    async def test_the_blueprint_reaches_the_custom_mcp_path_intact(self):
        # The whole request is asserted, not a field or two: the MCP creation
        # path branches on requires_auth and auth_type to decide whether to
        # probe for OAuth, and on bearer_token to decide whether it can skip
        # asking the user for one. A field dropped here becomes a connect
        # dialog that asks for a token the user already gave.
        with mcp_creation({"status": "connected", "tools_count": 7}) as mcp:
            authored = await create_integration(USER, mcp_blueprint())

        mcp.get_client.assert_awaited_once_with(user_id=USER)
        mcp.create.assert_awaited_once_with(
            USER,
            CreateCustomIntegrationRequest(
                name="Acme",
                description="Acme's own MCP server",
                category="business",
                server_url="https://mcp.example.test",
                requires_auth=True,
                auth_type="bearer",
                # An integration a chat turn created belongs to that user and
                # is not published to the marketplace behind their back.
                is_public=False,
                bearer_token="tok-123",
            ),
            mcp.client,
        )
        assert authored.integration is mcp.integration

    async def test_a_blank_description_is_stored_as_absent_not_as_an_empty_string(self):
        # The blueprint defaults description to "", and the catalog renders a
        # missing description differently from a present-but-empty one.
        with mcp_creation({"status": "connected"}) as mcp:
            await create_integration(USER, mcp_blueprint(description=""))

        assert mcp.create.await_args.args[1].description is None

    async def test_a_connected_server_reports_the_tool_count_it_returned(self):
        with mcp_creation({"status": "connected", "tools_count": 7}) as mcp:
            authored = await create_integration(USER, mcp_blueprint())

        assert authored.needs_connection is False
        assert authored.note == "Connected. 7 tools available."
        assert mcp.create.await_args.args[0] == USER

    async def test_a_connected_server_that_reported_no_tools_says_zero(self):
        # A server can connect and expose nothing. "0 tools available" is the
        # honest answer; anything invented here reads as tools the user has.
        with mcp_creation({"status": "connected"}):
            authored = await create_integration(USER, mcp_blueprint())

        assert authored.note == "Connected. 0 tools available."

    async def test_reports_when_the_server_still_needs_authentication(self):
        # Not an error — the user has one more step, and the note is what tells
        # them so.
        with mcp_creation({"status": "oauth_required"}):
            authored = await create_integration(USER, mcp_blueprint())

        assert authored.needs_connection is True
        assert authored.note == "Connect it to finish authenticating."

    async def test_a_failure_from_the_server_is_relayed_instead_of_the_generic_note(self):
        # The caller is a chat tool: "MCP server returned 502" lets the model
        # tell the user what went wrong, "connect it to finish" does not.
        with mcp_creation({"status": "error", "error": "MCP server returned 502"}):
            authored = await create_integration(USER, mcp_blueprint())

        assert authored.needs_connection is True
        assert authored.note == "MCP server returned 502"

    async def test_the_wrong_blueprint_kind_names_the_author_and_the_kind(self):
        # Unreachable through the registry, which dispatches on kind — it is the
        # guard that makes a future author wired to the wrong kind fail loudly
        # instead of quietly creating the wrong sort of integration.
        with pytest.raises(TypeError) as exc_info:
            await McpIntegrationAuthor().create(USER, cli_blueprint())

        assert str(exc_info.value) == "McpIntegrationAuthor cannot author a 'cli' blueprint"

    @pytest.mark.parametrize(
        "unsafe",
        ["http://127.0.0.1/mcp", "http://localhost:8080/mcp", "file:///etc/passwd", "ftp://x/y"],
    )
    async def test_rejects_unsafe_server_urls_from_a_chat_caller(self, unsafe: str):
        # This path never went through the HTTP request model that normally
        # applies the SSRF shape check.
        with pytest.raises(Exception):
            await create_integration(USER, McpBlueprint(name="Acme", server_url=unsafe))


class TestIconFromHomepage:
    """A CLI has no server URL, so the icon comes from a declared homepage.

    Declared rather than derived: pulling a URL out of ``install_command`` names
    where the bytes are hosted (github.com, registry.npmjs.org), not whose tool
    it is, and would give npm's icon to every npm-published vendor CLI.
    """

    async def test_stores_the_favicon_fetched_from_the_homepage(self):
        with (
            patch("app.services.integrations.authoring.cli_author.integration_repository") as repo,
            patch(
                "app.services.integrations.authoring.cli_author.add_user_integration", AsyncMock()
            ),
            patch(
                "app.services.integrations.authoring.cli_author.fetch_favicon_safely",
                AsyncMock(return_value="https://cdn.example.test/gh.png"),
            ) as fetch,
        ):
            repo.create = AsyncMock()
            await create_integration(USER, cli_blueprint(homepage="https://cli.github.com"))

        fetch.assert_awaited_once_with("https://cli.github.com")
        assert repo.create.await_args.args[0].icon_url == "https://cdn.example.test/gh.png"

    async def test_no_homepage_means_no_icon(self):
        # The blank-URL guard lives in the shared helper, not repeated here.
        with (
            patch("app.services.integrations.authoring.cli_author.integration_repository") as repo,
            patch(
                "app.services.integrations.authoring.cli_author.add_user_integration", AsyncMock()
            ),
            patch(
                "app.services.integrations.authoring.cli_author.fetch_favicon_safely",
                AsyncMock(return_value=None),
            ) as fetch,
        ):
            repo.create = AsyncMock()
            await create_integration(USER, cli_blueprint())

        fetch.assert_awaited_once_with(None)
        assert repo.create.await_args.args[0].icon_url is None

    async def test_an_unreachable_favicon_host_still_creates_the_integration(self):
        # The helper returns None rather than raising (its own tests pin that);
        # a missing icon must not cost the user the integration.
        with (
            patch("app.services.integrations.authoring.cli_author.integration_repository") as repo,
            patch(
                "app.services.integrations.authoring.cli_author.add_user_integration", AsyncMock()
            ),
            patch(
                "app.services.integrations.authoring.cli_author.fetch_favicon_safely",
                AsyncMock(return_value=None),
            ),
        ):
            repo.create = AsyncMock()
            authored = await create_integration(
                USER, cli_blueprint(homepage="https://slow.example.test")
            )

        assert authored.integration.name == "GitHub CLI"
        assert repo.create.await_args.args[0].icon_url is None

    @pytest.mark.parametrize(
        "unsafe",
        ["http://127.0.0.1/logo.png", "file:///etc/passwd", "ftp://example.test/x", "not-a-url"],
    )
    async def test_a_malformed_or_literal_private_homepage_is_rejected_outright(self, unsafe: str):
        # Caught by the model's cheap shape check, so the integration is never
        # created at all.
        with patch(
            "app.services.integrations.authoring.cli_author.fetch_favicon_safely", AsyncMock()
        ) as fetch:
            with pytest.raises(ValueError, match="Invalid CLI configuration"):
                await create_integration(USER, cli_blueprint(homepage=unsafe))
        fetch.assert_not_awaited()

    async def test_a_hostname_resolving_to_a_private_address_yields_no_icon(self):
        # The shape check does not resolve DNS, so `localhost` passes it; the
        # shared helper's resolving guard is what refuses the request. The
        # integration is still created, just without an icon.
        with (
            patch("app.services.integrations.authoring.cli_author.integration_repository") as repo,
            patch(
                "app.services.integrations.authoring.cli_author.add_user_integration", AsyncMock()
            ),
            patch(
                "app.services.integrations.authoring.cli_author.fetch_favicon_safely",
                AsyncMock(return_value=None),
            ) as fetch,
        ):
            repo.create = AsyncMock()
            authored = await create_integration(
                USER, cli_blueprint(homepage="http://localhost:8080/")
            )

        fetch.assert_awaited_once_with("http://localhost:8080/")
        assert authored.integration.icon_url is None
