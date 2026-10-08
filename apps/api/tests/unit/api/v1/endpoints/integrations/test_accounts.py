"""The connected-accounts routes, driven through the real lifecycle service.

Only the repository and the Composio client are mocked, so what each route
returns is what the service actually decided.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.constants.integrations import MAX_ACCOUNTS_PER_INTEGRATION
from app.models.integration_models import (
    IntegrationAccount,
    IntegrationAccountStatus,
    UserIntegrationDocument,
)

BASE = "/api/v1/integrations"
USER_ID = "507f1f77bcf86cd799439011"
LIFECYCLE = "app.services.integrations.integration_account_lifecycle"


def _account(account_id: str, status: IntegrationAccountStatus = "connected") -> IntegrationAccount:
    return IntegrationAccount(
        connected_account_id=account_id, label=f"{account_id}@acme.com", status=status
    )


def _record(*accounts: IntegrationAccount, primary: str = "ca_1") -> UserIntegrationDocument:
    return UserIntegrationDocument(
        user_id=USER_ID,
        integration_id="gmail",
        status="connected",
        accounts=list(accounts),
        primary_account_id=primary,
    )


@pytest.fixture
def repo(fake_redis: object) -> Iterator[MagicMock]:
    async def save(user_id: str, integration_id: str, **fields: object) -> UserIntegrationDocument:
        fields.pop("expired_reason", None)
        doc = UserIntegrationDocument(user_id=user_id, integration_id=integration_id, **fields)
        repository.get_for_user.return_value = doc
        return doc

    with patch(
        "app.services.integrations.integration_accounts.user_integration_repository"
    ) as repository:
        repository.get_for_user = AsyncMock(return_value=None)
        repository.save_accounts = AsyncMock(side_effect=save)
        yield repository


@pytest.fixture
def composio() -> Iterator[MagicMock]:
    service = MagicMock()
    service.delete_connected_account = AsyncMock()
    with (
        patch(f"{LIFECYCLE}.get_composio_service", return_value=service),
        patch(f"{LIFECYCLE}.capture_event"),
        patch(f"{LIFECYCLE}.resync_primary_bound_triggers", AsyncMock()),
    ):
        yield service


class TestListAccounts:
    async def test_it_lists_every_account_with_the_primary_marked(
        self, client: AsyncClient, repo: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(
            _account("ca_1"), _account("ca_2", status="expired"), primary="ca_1"
        )

        resp = await client.get(f"{BASE}/gmail/accounts")

        assert resp.status_code == 200
        body = resp.json()
        assert body["integrationId"] == "gmail"
        assert body["maxAccounts"] == MAX_ACCOUNTS_PER_INTEGRATION
        assert [
            (a["id"], a["displayName"], a["status"], a["isPrimary"]) for a in body["accounts"]
        ] == [
            ("ca_1", "ca_1@acme.com", "connected", True),
            ("ca_2", "ca_2@acme.com", "expired", False),
        ]
        repo.get_for_user.assert_awaited_once_with(USER_ID, "gmail")

    async def test_an_integration_without_accounts_lists_none(
        self, client: AsyncClient, repo: MagicMock
    ) -> None:
        resp = await client.get(f"{BASE}/gmail/accounts")

        assert resp.status_code == 200
        assert resp.json()["accounts"] == []

    async def test_an_integration_that_is_not_composio_is_404(
        self, client: AsyncClient, repo: MagicMock
    ) -> None:
        resp = await client.get(f"{BASE}/deepwiki/accounts")

        assert resp.status_code == 404
        repo.get_for_user.assert_not_awaited()


class TestUpdateAccount:
    async def test_making_an_account_primary_is_reflected_in_the_response(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(_account("ca_1"), _account("ca_2"))

        resp = await client.patch(f"{BASE}/gmail/accounts/ca_2", json={"isPrimary": True})

        assert resp.status_code == 200
        primary = [a["id"] for a in resp.json()["accounts"] if a["isPrimary"]]
        assert primary == ["ca_2"]

    async def test_a_nickname_renames_the_account_and_an_empty_one_clears_it(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(_account("ca_1"))

        renamed = await client.patch(f"{BASE}/gmail/accounts/ca_1", json={"nickname": "Work"})
        cleared = await client.patch(f"{BASE}/gmail/accounts/ca_1", json={"nickname": ""})

        assert renamed.json()["accounts"][0]["displayName"] == "Work"
        assert cleared.json()["accounts"][0]["displayName"] == "ca_1@acme.com"
        assert cleared.json()["accounts"][0]["nickname"] is None

    async def test_an_expired_account_cannot_become_primary(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(_account("ca_1"), _account("ca_2", "expired"))

        resp = await client.patch(f"{BASE}/gmail/accounts/ca_2", json={"isPrimary": True})

        assert resp.status_code == 409
        repo.save_accounts.assert_not_awaited()

    async def test_an_unknown_account_is_404(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(_account("ca_1"))

        resp = await client.patch(f"{BASE}/gmail/accounts/ca_nope", json={"isPrimary": True})

        assert resp.status_code == 404


class TestRemoveAccount:
    async def test_removing_one_of_several_revokes_it_and_returns_the_rest(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(_account("ca_1"), _account("ca_2"))

        resp = await client.delete(f"{BASE}/gmail/accounts/ca_1")

        assert resp.status_code == 200
        accounts = resp.json()["accounts"]
        assert [(a["id"], a["isPrimary"]) for a in accounts] == [("ca_2", True)]
        composio.delete_connected_account.assert_awaited_once_with("ca_1")

    async def test_removing_the_last_account_disconnects_the_integration(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(_account("ca_1"))

        with patch(f"{LIFECYCLE}.disconnect_integration", AsyncMock()) as disconnect:
            resp = await client.delete(f"{BASE}/gmail/accounts/ca_1")

        assert resp.status_code == 200
        assert resp.json()["accounts"] == []
        disconnect.assert_awaited_once_with(USER_ID, "gmail")
