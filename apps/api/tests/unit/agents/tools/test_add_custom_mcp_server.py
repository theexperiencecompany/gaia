"""Unit tests for the add_custom_mcp_server executor tool.

The tool must never leak a secret or an OAuth URL into its return value (the
ToolMessage the LLM reads): OAuth/bearer flows are delivered through the
capability-free connect card (request_integration_connection), and a token is
never accepted as an argument.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.core.registry import ToolRegistry
from app.agents.tools.integration_tool import add_custom_mcp_server
from tests.helpers import captured_wide_event

_MODULE = "app.agents.tools.integration_tool"
_CONFIG = {"configurable": {"user_id": "u1"}}
_URL = "https://mcp.sentry.dev/mcp"


def _integration(integration_id: str = "int-1", name: str = "Sentry") -> SimpleNamespace:
    return SimpleNamespace(integration_id=integration_id, name=name)


@pytest.fixture
def seams():
    """Patch every external seam of the tool; each test drives the mocks it needs."""
    mcp_client = AsyncMock()
    mcp_client.probe_connection = AsyncMock(return_value={})
    repo = MagicMock()
    repo.find_custom_by_server_url = AsyncMock(return_value=None)
    user_repo = MagicMock()
    user_repo.is_connected = AsyncMock(return_value=False)
    with (
        patch(f"{_MODULE}.OAUTH_INTEGRATIONS", []),
        patch(f"{_MODULE}.get_mcp_client", AsyncMock(return_value=mcp_client)) as get_client,
        patch(f"{_MODULE}.integration_repository", repo),
        patch(f"{_MODULE}.user_integration_repository", user_repo),
        patch(
            f"{_MODULE}.create_and_connect_custom_integration", new=AsyncMock()
        ) as create_connect,
        patch(f"{_MODULE}.create_custom_integration", new=AsyncMock()) as create,
        patch(
            f"{_MODULE}.request_integration_connection",
            new=AsyncMock(return_value="A connect button has been shown to the user."),
        ) as request_card,
    ):
        yield SimpleNamespace(
            mcp_client=mcp_client,
            get_client=get_client,
            repo=repo,
            user_repo=user_repo,
            create_connect=create_connect,
            create=create,
            request_card=request_card,
        )


async def _run(server_url: str = _URL, name: str = "Sentry", config=_CONFIG) -> str:
    return await add_custom_mcp_server.ainvoke(
        {"server_url": server_url, "name": name}, config=config
    )


async def test_no_auth_server_connects_and_reports_tool_count(seams):
    seams.mcp_client.probe_connection.return_value = {}
    seams.create_connect.return_value = (
        _integration(name="Sentry"),
        {"status": "connected", "tools_count": 3},
    )

    async with captured_wide_event() as event:
        result = await _run()

    assert result == "✅ Added and connected Sentry (3 tools available)."
    assert event["tool"] == {"name": "add_custom_mcp_server", "action": "create"}
    seams.request_card.assert_not_awaited()
    # The client is fetched for this user; the URL is probed and looked up
    # normalized (never the raw argument).
    seams.get_client.assert_awaited_once_with(user_id="u1")
    seams.mcp_client.probe_connection.assert_awaited_once_with(_URL)
    seams.repo.find_custom_by_server_url.assert_awaited_once_with(_URL, "u1")
    # The created integration carries the normalized url, no token, and is private.
    passed_request = seams.create_connect.await_args.args[1]
    assert seams.create_connect.await_args.args[0] == "u1"
    assert seams.create_connect.await_args.args[2] is seams.mcp_client
    assert passed_request.server_url == _URL
    assert passed_request.bearer_token is None
    assert passed_request.is_public is False


async def test_no_auth_server_missing_tool_count_reports_zero(seams):
    # tools_count absent -> the "or 0" fallback, not a crash or a blank.
    seams.mcp_client.probe_connection.return_value = {}
    seams.create_connect.return_value = (_integration(name="Sentry"), {"status": "connected"})

    result = await _run()

    assert result == "✅ Added and connected Sentry (0 tools available)."


async def test_oauth_server_shows_card_and_never_leaks_the_oauth_url(seams):
    seams.mcp_client.probe_connection.return_value = {"requires_auth": True, "auth_type": "oauth"}
    seams.create_connect.return_value = (
        _integration(integration_id="int-oauth"),
        {"status": "requires_oauth", "oauth_url": "https://evil.example/secret-state-token"},
    )

    result = await _run()

    assert result == "A connect button has been shown to the user."
    assert "secret-state-token" not in result
    assert "http" not in result  # the tool return carries no URL at all
    # The card is handed the created integration id, the name, and this user.
    seams.request_card.assert_awaited_once_with("int-oauth", "Sentry", "u1")


async def test_bearer_server_hands_off_to_ui_without_taking_a_token(seams):
    seams.mcp_client.probe_connection.return_value = {"requires_auth": True, "auth_type": "bearer"}
    seams.create.return_value = _integration(integration_id="int-bearer")

    result = await _run()

    # created (so the UI has a target for the token) but never auto-connected,
    # and the connect+token flow is delegated to the secure card.
    seams.create.assert_awaited_once()
    assert seams.create.await_args.args[0] == "u1"
    seams.create_connect.assert_not_awaited()
    created_request = seams.create.await_args.args[1]
    assert created_request.auth_type == "bearer"
    assert created_request.requires_auth is True
    assert created_request.server_url == _URL
    assert created_request.bearer_token is None
    seams.request_card.assert_awaited_once_with("int-bearer", "Sentry", "u1")
    assert result == "A connect button has been shown to the user."


async def test_auth_required_but_not_bearer_still_connects(seams):
    # requires_auth with a non-bearer type is NOT the bearer hand-off; it goes
    # through the connect path with the probed auth_type carried onto the request.
    seams.mcp_client.probe_connection.return_value = {"requires_auth": True, "auth_type": "oauth"}
    seams.create_connect.return_value = (
        _integration(),
        {"status": "connected", "tools_count": 1},
    )

    result = await _run()

    seams.create.assert_not_awaited()
    seams.create_connect.assert_awaited_once()
    req = seams.create_connect.await_args.args[1]
    assert req.requires_auth is True
    assert req.auth_type == "oauth"
    assert result == "✅ Added and connected Sentry (1 tools available)."


@pytest.mark.parametrize(
    ("probed", "expected"),
    [("none", "none"), ("oauth", "oauth"), ("bearer", "bearer"), ("weird", None), (None, None)],
)
async def test_probe_auth_type_is_carried_only_when_known(seams, probed, expected):
    # Each known auth_type flows onto the record verbatim; anything else (or a
    # missing type) is dropped to None. requires_auth is False so this stays on
    # the connect path, not the bearer hand-off.
    seams.mcp_client.probe_connection.return_value = {"requires_auth": False, "auth_type": probed}
    seams.create_connect.return_value = (_integration(), {"status": "connected", "tools_count": 0})

    await _run()

    assert seams.create_connect.await_args.args[1].auth_type == expected


async def test_probe_unreachable_is_reported_without_writing(seams):
    seams.mcp_client.probe_connection.return_value = {"error": "connection refused"}

    result = await _run()

    assert result == "❌ Couldn't reach that MCP server: connection refused"
    seams.create.assert_not_awaited()
    seams.create_connect.assert_not_awaited()


async def test_duplicate_already_connected_short_circuits(seams):
    seams.repo.find_custom_by_server_url.return_value = _integration(name="Sentry")
    seams.user_repo.is_connected.return_value = True

    result = await _run()

    assert result == "✅ Sentry is already added and connected."
    seams.mcp_client.probe_connection.assert_not_awaited()
    seams.create_connect.assert_not_awaited()
    seams.create.assert_not_awaited()


async def test_duplicate_not_connected_shows_connect_card(seams):
    existing = _integration(integration_id="int-dup", name="Sentry")
    seams.repo.find_custom_by_server_url.return_value = existing
    seams.user_repo.is_connected.return_value = False

    result = await _run()

    assert result == "A connect button has been shown to the user."
    # is_connected is checked for this user + the existing id, and the card is
    # handed the existing integration's own id and name.
    seams.user_repo.is_connected.assert_awaited_once_with("u1", "int-dup")
    seams.request_card.assert_awaited_once_with("int-dup", "Sentry", "u1")
    seams.mcp_client.probe_connection.assert_not_awaited()


async def test_trailing_slash_url_probed_and_stored_verbatim(seams):
    # Normalization is for dedup only: the probe and the persisted record keep
    # the exact path the vendor docs gave — some servers distinguish /mcp from
    # /mcp/ — while the idempotency lookup uses the normalized form.
    raw = "https://mcp.sentry.dev/mcp/"
    seams.mcp_client.probe_connection.return_value = {}
    seams.create_connect.return_value = (
        _integration(),
        {"status": "connected", "tools_count": 0},
    )

    await _run(server_url=raw)

    seams.mcp_client.probe_connection.assert_awaited_once_with(raw)
    seams.repo.find_custom_by_server_url.assert_awaited_once_with(
        "https://mcp.sentry.dev/mcp", "u1"
    )
    assert seams.create_connect.await_args.args[1].server_url == raw


# Distinct id/name/short_name so each match isolates exactly one branch of the
# `id or name or short_name` test — no single field can stand in for another.
_CATALOG = [SimpleNamespace(id="gh-id", name="GitHub Name", short_name="ghs")]


@pytest.mark.parametrize(
    "name_arg",
    ["gh-id", "github name", "  GH-ID  ", "GHS"],
    ids=["by-id", "by-name-caseless", "by-id-case-and-space", "by-short-name"],
)
async def test_catalog_app_redirects_to_connect_integration(seams, name_arg):
    with patch(f"{_MODULE}.OAUTH_INTEGRATIONS", _CATALOG):
        result = await _run(name=name_arg)

    assert result == (
        "GitHub Name is a built-in integration; use connect_integration with id "
        "'gh-id' instead of adding it as a custom MCP server."
    )
    seams.create_connect.assert_not_awaited()
    seams.create.assert_not_awaited()
    seams.mcp_client.probe_connection.assert_not_awaited()


async def test_a_name_matching_no_catalog_field_is_not_a_redirect(seams):
    # A name that matches neither id, name, nor short_name proceeds to probe —
    # proving the catalog guard is a real match, not an always-true short circuit.
    seams.mcp_client.probe_connection.return_value = {}
    seams.create_connect.return_value = (_integration(), {"status": "connected", "tools_count": 0})
    with patch(f"{_MODULE}.OAUTH_INTEGRATIONS", _CATALOG):
        result = await _run(name="Totally Unrelated")

    assert "built-in integration" not in result
    seams.mcp_client.probe_connection.assert_awaited_once()


async def test_disallowed_url_is_rejected_before_any_write(seams):
    result = await _run(server_url="ftp://evil.example/mcp")

    assert result.startswith("❌ That server URL can't be used:")
    seams.create_connect.assert_not_awaited()
    seams.create.assert_not_awaited()
    seams.mcp_client.probe_connection.assert_not_awaited()
    seams.get_client.assert_not_awaited()


async def test_missing_user_id_fails_loud(seams):
    result = await _run(config={"configurable": {}})
    assert result == "Error: User ID not found in configuration."


async def test_failed_connect_keeps_record_and_surfaces_id(seams):
    seams.mcp_client.probe_connection.return_value = {}
    seams.create_connect.return_value = (
        _integration(integration_id="int-9", name="Sentry"),
        {"status": "failed", "error": "boom"},
    )

    result = await _run()

    assert result == (
        "❌ Added Sentry but couldn't connect: boom. "
        "It's saved (id int-9); you can ask me to retry connecting it."
    )


async def test_failed_connect_without_error_uses_a_default_reason(seams):
    seams.mcp_client.probe_connection.return_value = {}
    seams.create_connect.return_value = (_integration(integration_id="int-9"), {"status": "failed"})

    result = await _run()

    assert "couldn't connect: unknown error." in result


async def test_unexpected_failure_is_caught_and_logged(seams):
    seams.repo.find_custom_by_server_url.side_effect = RuntimeError("mongo down")

    async with captured_wide_event() as event:
        result = await _run()

    assert result == "Error adding MCP server: mongo down"
    (error,) = event["errors"]
    assert "Error adding custom MCP server" in error["msg"]
    assert error["error_type"] == "RuntimeError"


def test_add_custom_mcp_server_is_force_gated():
    """HIL is globally always_allow pre-launch; only always_gate_tools force a confirmation card."""
    registry = ToolRegistry()
    registry._initialize_categories()

    add_meta = registry.get_tool_meta("add_custom_mcp_server")
    assert add_meta is not None
    assert add_meta.always_gate is True

    # Control: connect_integration is destructive but not force-gated, so the
    # assertion above proves the stamp is selective, not blanket-true.
    connect_meta = registry.get_tool_meta("connect_integration")
    assert connect_meta is not None
    assert connect_meta.always_gate is False
