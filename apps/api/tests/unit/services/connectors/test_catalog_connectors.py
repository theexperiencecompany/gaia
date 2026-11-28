"""A catalog connector takes the same path as one the agent defined, for every user, with no draft."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.subagents.integration_activation import (
    _activate_connector,
    load_integration,
)
from app.agents.core.subagents.integration_target import (
    get_integration_target,
)
from app.agents.tools.connector_tools import define_connector
from app.services.connectors.connect import connect_connector
from app.services.connectors.runner import RunOutcome
from app.services.connectors.service import (
    ConnectorCallResult,
    ConnectorNotFoundError,
    load_connector,
)
from app.services.integrations.integration_connection_service import build_integrations_config
from tests.factories import make_connector_spec

USER_ID = "507f1f77bcf86cd799439011"
ACTIVATION = "app.agents.core.subagents.integration_activation"
CONNECT = "app.services.connectors.connect"


async def test_any_user_loads_a_catalog_connector_without_touching_the_database() -> None:
    repo = MagicMock(get_custom=AsyncMock(return_value=None))
    with patch("app.services.connectors.service.integration_repository", repo):
        doc, spec = await load_connector(USER_ID, "resend")

    assert (doc.integration_id, doc.source, spec.provider_domain) == (
        "resend",
        "platform",
        "resend.com",
    )
    repo.get_custom.assert_not_awaited()


async def test_an_unknown_id_is_still_not_found() -> None:
    repo = MagicMock(get_custom=AsyncMock(return_value=None))
    with patch("app.services.connectors.service.integration_repository", repo):
        with pytest.raises(ConnectorNotFoundError):
            await load_connector(USER_ID, "not-a-connector")


async def test_a_catalog_connector_resolves_to_a_connector_target() -> None:
    target = await get_integration_target("Resend")

    assert target is not None
    assert (target.id, target.managed_by, target.source) == ("resend", "connector", "platform")


async def test_activating_an_unconnected_catalog_connector_shows_the_connect_card() -> None:
    target = await get_integration_target("resend")
    assert target is not None and target is not None
    card = AsyncMock(return_value="connect card shown")
    with (
        patch(f"{ACTIVATION}.check_user_has_integration", AsyncMock(return_value=False)),
        patch(
            f"{ACTIVATION}.user_integration_repository",
            MagicMock(is_connected=AsyncMock(return_value=False)),
        ),
        patch(f"{ACTIVATION}.request_integration_connection", card),
    ):
        reply = await _activate_connector(target, USER_ID)

    assert reply == "connect card shown"
    assert card.await_args.args == ("resend", "Resend", USER_ID)


async def test_defining_a_connector_for_a_shipped_provider_points_at_the_catalog() -> None:
    save = AsyncMock()
    with patch("app.agents.tools.connector_tools.save_connector", save):
        reply = await define_connector.ainvoke(
            {
                "name": "Resend",
                "description": "Email API.",
                "spec": make_connector_spec("rest").model_dump(),
            },
            config={"configurable": {"user_id": USER_ID}},
        )

    assert "'resend'" in reply
    assert "connect_integration" in reply
    save.assert_not_awaited()


def test_the_catalog_lists_each_connector_with_its_connect_card() -> None:
    [item] = [i for i in build_integrations_config().integrations if i.id == "resend"]

    assert item.managed_by == "connector"
    assert item.connector is not None
    assert item.connector.allowed_hosts == ["api.resend.com"]
    assert item.connector.token_url == "https://resend.com/api-keys"


async def test_connecting_a_catalog_connector_never_writes_an_integration_document() -> None:
    doc, spec = await load_connector(USER_ID, "resend")
    verified = ConnectorCallResult(
        outcome=RunOutcome.OK,
        is_write=False,
        exit_code=0,
        stdout='{"data":[{"name":"heygaia.io"}]}',
        stderr="",
        failure=None,
        output_capped=False,
        duration_ms=10,
    )
    repo = MagicMock(update=AsyncMock())
    with (
        patch(f"{CONNECT}.load_connector", AsyncMock(return_value=(doc, spec))),
        patch(f"{CONNECT}.run_with_secret", AsyncMock(return_value=verified)),
        patch(
            f"{CONNECT}.MCPTokenStore",
            MagicMock(return_value=MagicMock(store_bearer_token=AsyncMock())),
        ),
        patch(f"{CONNECT}.save_accounts", AsyncMock()),
        patch(f"{CONNECT}.publish_connected", AsyncMock()),
        patch(f"{CONNECT}.invalidate_user_integration_caches", AsyncMock()),
        patch(f"{CONNECT}.integration_repository", repo),
        patch(f"{CONNECT}.capture"),
    ):
        response = await connect_connector(USER_ID, "resend", "re_key")

    assert (response.status, response.account_label) == ("connected", "heygaia.io")
    repo.update.assert_not_awaited()


async def test_defining_a_binary_with_no_arm64_build_is_refused_before_anything_is_saved() -> None:
    save = AsyncMock()
    package = {
        "manager": "binary",
        "name": "terraform",
        "version": "1.17.2",
        "arch": "amd64",
        "url": "https://releases.hashicorp.com/terraform_1.17.2_linux_amd64.zip",
        "sha256": "a" * 64,
        "archive_member": "terraform",
    }
    spec = make_connector_spec(
        "cli",
        provider_domain="hashicorp.com",
        allowed_hosts=["app.terraform.io"],
        install=[package],
    )
    with patch("app.agents.tools.connector_tools.save_connector", save):
        reply = await define_connector.ainvoke(
            {"name": "Terraform", "description": "IaC.", "spec": spec.model_dump()},
            config={"configurable": {"user_id": USER_ID}},
        )

    assert "terraform has no arm64 build" in reply
    save.assert_not_awaited()


async def test_activating_a_guessed_provider_name_points_at_the_catalog_connector() -> None:
    with patch(
        "app.agents.core.subagents.integration_target.integration_repository",
        MagicMock(find_by_id_prefix_or_name=AsyncMock(return_value=None)),
    ):
        load = await load_integration("vercel", {"user_id": USER_ID}, [])

    assert "Unknown integration 'vercel'" in load.text
    assert "'vercel-cli' (Vercel CLI)" in load.text
