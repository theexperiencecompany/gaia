"""The connected-accounts routes, driven through the real lifecycle service.

Only the repository and the Composio client are mocked, so what each route
returns is what the service actually decided.
"""

from collections.abc import Iterator
from functools import partial
from unittest.mock import AsyncMock, MagicMock, call, patch

from httpx import AsyncClient
import pytest
from tests.integration_account_factories import (
    make_integration_account,
    make_integration_record,
    with_nickname,
)

from app.constants.integrations import MAX_ACCOUNTS_PER_INTEGRATION
from app.models.integration_models import (
    IntegrationAccount,
    UserIntegrationDocument,
    UserIntegrationStatus,
)

BASE = "/api/v1/integrations"
USER_ID = "507f1f77bcf86cd799439011"
LIFECYCLE = "app.services.integrations.integration_account_lifecycle"
ROUTES = "app.api.v1.endpoints.integrations.accounts"


_record = partial(make_integration_record, user_id=USER_ID, integration_id="gmail")


@pytest.fixture
def repo(fake_redis: object) -> Iterator[MagicMock]:
    async def save(
        user_id: str,
        integration_id: str,
        *,
        accounts: list[IntegrationAccount],
        primary_account_id: str | None,
        status: UserIntegrationStatus,
        expired_reason: str | None = None,
    ) -> UserIntegrationDocument:
        doc = UserIntegrationDocument(
            user_id=user_id,
            integration_id=integration_id,
            accounts=accounts,
            primary_account_id=primary_account_id,
            status=status,
        )
        repository.get_for_user.return_value = doc
        return doc

    async def name(
        _user_id: str, _integration_id: str, connected_account_id: str, nickname: str | None
    ) -> UserIntegrationDocument | None:
        doc = with_nickname(repository.get_for_user.return_value, connected_account_id, nickname)
        if doc is not None:
            repository.get_for_user.return_value = doc
        return doc

    with patch(
        "app.services.integrations.integration_accounts.user_integration_repository"
    ) as repository:
        repository.get_for_user = AsyncMock(return_value=None)
        repository.set_account_nickname = AsyncMock(side_effect=name)
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


@pytest.fixture
def wide_log() -> Iterator[MagicMock]:
    with patch(f"{ROUTES}.log") as log:
        yield log


class TestListAccounts:
    async def test_it_lists_every_account_with_the_primary_marked(
        self, client: AsyncClient, repo: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(
            make_integration_account("ca_1"),
            make_integration_account("ca_2", status="expired"),
            primary="ca_1",
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

    async def test_the_wide_event_names_the_listing_and_its_size(
        self, client: AsyncClient, repo: MagicMock, wide_log: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(
            make_integration_account("ca_1"), make_integration_account("ca_2")
        )

        await client.get(f"{BASE}/gmail/accounts")

        assert wide_log.set.call_args_list == [
            call(user={"id": USER_ID}, integration={"id": "gmail", "action": "list_accounts"}),
            call(result_count=2, outcome="success"),
        ]

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
        repo.get_for_user.return_value = _record(
            make_integration_account("ca_1"), make_integration_account("ca_2")
        )

        resp = await client.patch(f"{BASE}/gmail/accounts/ca_2", json={"isPrimary": True})

        assert resp.status_code == 200
        primary = [a["id"] for a in resp.json()["accounts"] if a["isPrimary"]]
        assert primary == ["ca_2"]

    async def test_a_nickname_renames_the_account_and_an_empty_one_clears_it(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(make_integration_account("ca_1"))

        renamed = await client.patch(f"{BASE}/gmail/accounts/ca_1", json={"nickname": "Work"})
        cleared = await client.patch(f"{BASE}/gmail/accounts/ca_1", json={"nickname": ""})

        assert renamed.json()["accounts"][0]["displayName"] == "Work"
        assert cleared.json()["accounts"][0]["displayName"] == "ca_1@acme.com"
        assert cleared.json()["accounts"][0]["nickname"] is None

    async def test_the_wide_event_names_the_account_and_the_fields_changed(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock, wide_log: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(
            make_integration_account("ca_1"), make_integration_account("ca_2")
        )

        await client.patch(
            f"{BASE}/gmail/accounts/ca_2", json={"nickname": "Work", "isPrimary": True}
        )

        assert wide_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                integration={"id": "gmail", "action": "update_account"},
                account={"id": "ca_2", "fields": ["is_primary", "nickname"]},
            ),
            call(outcome="success"),
        ]

    async def test_an_expired_account_cannot_become_primary(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(
            make_integration_account("ca_1"), make_integration_account("ca_2", "expired")
        )

        resp = await client.patch(f"{BASE}/gmail/accounts/ca_2", json={"isPrimary": True})

        assert resp.status_code == 409
        repo.save_accounts.assert_not_awaited()

    async def test_an_unknown_account_is_404(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(make_integration_account("ca_1"))

        resp = await client.patch(f"{BASE}/gmail/accounts/ca_nope", json={"isPrimary": True})

        assert resp.status_code == 404


class TestRemoveAccount:
    async def test_removing_one_of_several_revokes_it_and_returns_the_rest(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(
            make_integration_account("ca_1"), make_integration_account("ca_2")
        )

        resp = await client.delete(f"{BASE}/gmail/accounts/ca_1")

        assert resp.status_code == 200
        accounts = resp.json()["accounts"]
        assert [(a["id"], a["isPrimary"]) for a in accounts] == [("ca_2", True)]
        composio.delete_connected_account.assert_awaited_once_with("ca_1")

    async def test_removal_is_audited_and_the_wide_event_counts_what_remains(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock, wide_log: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(
            make_integration_account("ca_1"), make_integration_account("ca_2")
        )

        await client.delete(f"{BASE}/gmail/accounts/ca_1")

        wide_log.audit.assert_called_once_with(
            "integration account removed", actor=USER_ID, resource="gmail", account_id="ca_1"
        )
        assert wide_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                integration={"id": "gmail", "action": "remove_account"},
                account={"id": "ca_1"},
            ),
            call(outcome="success", remaining=1),
        ]

    async def test_removing_the_last_account_disconnects_the_integration(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(make_integration_account("ca_1"))

        with patch(f"{LIFECYCLE}.disconnect_integration", AsyncMock()) as disconnect:
            resp = await client.delete(f"{BASE}/gmail/accounts/ca_1")

        assert resp.status_code == 200
        assert resp.json()["accounts"] == []
        disconnect.assert_awaited_once_with(USER_ID, "gmail")

    async def test_removing_the_last_account_leaves_none_on_the_wide_event(
        self, client: AsyncClient, repo: MagicMock, composio: MagicMock, wide_log: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(make_integration_account("ca_1"))

        with patch(f"{LIFECYCLE}.disconnect_integration", AsyncMock()):
            await client.delete(f"{BASE}/gmail/accounts/ca_1")

        assert wide_log.set.call_args_list[-1] == call(outcome="success", remaining=0)
