"""Unit tests for creating an integration from a blueprint.

The authoring path is reachable from a chat tool, so its inputs come from a
model reading a vendor's docs. The tests focus on what that implies: a
malformed blueprint must fail with a message the model can act on, and a
half-created integration must never be left behind.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.integrations.authoring import (
    CliBlueprint,
    McpBlueprint,
    create_integration,
    get_author,
)
from app.services.integrations.authoring.cli_author import CliIntegrationAuthor

USER = "user-1"


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
    return CliBlueprint(**base)  # type: ignore[arg-type]


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
    async def test_delegates_to_the_existing_custom_mcp_path(self):
        integration = MagicMock(name="integration")
        with (
            patch(
                "app.services.integrations.authoring.mcp_author.get_mcp_client",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.services.integrations.authoring.mcp_author.create_and_connect_custom_integration",
                AsyncMock(return_value=(integration, {"status": "connected", "tools_count": 7})),
            ) as create,
        ):
            authored = await create_integration(
                USER, McpBlueprint(name="Acme", server_url="https://mcp.example.test")
            )

        create.assert_awaited_once()
        assert authored.integration is integration
        assert authored.needs_connection is False
        assert "7 tools" in (authored.note or "")

    async def test_reports_when_the_server_still_needs_authentication(self):
        with (
            patch(
                "app.services.integrations.authoring.mcp_author.get_mcp_client",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.services.integrations.authoring.mcp_author.create_and_connect_custom_integration",
                AsyncMock(return_value=(MagicMock(), {"status": "oauth_required"})),
            ),
        ):
            authored = await create_integration(
                USER, McpBlueprint(name="Acme", server_url="https://mcp.example.test")
            )
        assert authored.needs_connection is True

    @pytest.mark.parametrize(
        "unsafe",
        ["http://127.0.0.1/mcp", "http://localhost:8080/mcp", "file:///etc/passwd", "ftp://x/y"],
    )
    async def test_rejects_unsafe_server_urls_from_a_chat_caller(self, unsafe: str):
        # This path never went through the HTTP request model that normally
        # applies the SSRF shape check.
        with pytest.raises(Exception):
            await create_integration(USER, McpBlueprint(name="Acme", server_url=unsafe))
