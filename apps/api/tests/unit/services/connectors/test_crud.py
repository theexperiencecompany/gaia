"""Redefining a connector: any change to what runs with the key or where it goes asks every user again."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.constants.integrations import IntegrationStatus
from app.models.connector_models import ConnectorSpec
from app.services.connectors.crud import REACH_CHANGED_REASON, define_connector
from tests.factories import make_connector_doc, make_connector_spec

MODULE = "app.services.connectors.crud"
OWNER = "507f1f77bcf86cd799439011"
MEMBER = "507f1f77bcf86cd799439012"
NEVER_CONNECTED = "507f1f77bcf86cd799439013"
CONNECTOR_ID = "c0ffee00-0000-4000-8000-000000000003"


class _Patched:
    def __init__(self, existing_spec: ConnectorSpec, *, is_public: bool) -> None:
        existing = make_connector_doc(CONNECTOR_ID, OWNER, existing_spec, name="GitHub CLI")
        existing.is_public = is_public
        self.expire = AsyncMock(return_value=True)
        users = MagicMock(
            user_ids_with_integration=AsyncMock(return_value=[OWNER, MEMBER, NEVER_CONNECTED]),
            is_connected=AsyncMock(side_effect=lambda user, _id: user != NEVER_CONNECTED),
        )
        integrations = MagicMock(
            find_custom_connector=AsyncMock(return_value=existing),
            update=AsyncMock(return_value=existing),
            store_tools=AsyncMock(),
        )
        self.patches = [
            patch(f"{MODULE}.integration_repository", integrations),
            patch(f"{MODULE}.user_integration_repository", users),
            patch(f"{MODULE}.update_user_integration_status", self.expire),
            patch(f"{MODULE}.capture"),
            patch(f"{MODULE}.log"),
        ]

    def __enter__(self) -> "_Patched":
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *_: object) -> None:
        for p in self.patches:
            p.stop()


def _expired(user_id: str) -> object:
    return call(
        user_id, CONNECTOR_ID, IntegrationStatus.EXPIRED, expired_reason=REACH_CHANGED_REASON
    )


@pytest.mark.parametrize(
    "change",
    [
        {"allowed_hosts": ["api.github.com", "github.com", "collector.github.com"]},
        {"risk": {"read_commands": ["api", "repo list", "issue list", "issue create"]}},
    ],
)
@pytest.mark.parametrize("is_public", [True, False])
async def test_a_redefinition_that_changes_the_spec_expires_every_connected_user_owner_included(
    change: dict[str, object], is_public: bool
) -> None:
    with _Patched(make_connector_spec("cli"), is_public=is_public) as patched:
        defined = await define_connector(
            OWNER, "GitHub CLI", "", make_connector_spec("cli", **change)
        )

    assert defined.reach_changed
    assert patched.expire.await_args_list == [_expired(OWNER), _expired(MEMBER)]


async def test_a_cosmetic_redefinition_keeps_everyone_connected() -> None:
    with _Patched(make_connector_spec("cli"), is_public=True) as patched:
        defined = await define_connector(
            OWNER, "GitHub CLI", "", make_connector_spec("cli", capability="Other words")
        )

    assert not defined.reach_changed
    patched.expire.assert_not_awaited()
