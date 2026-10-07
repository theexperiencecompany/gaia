"""Contract tests for UserIntegrationsRepository (user-scoped, per-integration)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.user_integrations import UserIntegrationsRepository
from app.models.integration_models import IntegrationAccount, UserIntegrationDocument


@pytest.fixture
def repo(raw_collection) -> UserIntegrationsRepository:
    return UserIntegrationsRepository()


def _ui(user_id: str, integration_id: str, **overrides: object) -> UserIntegrationDocument:
    data: dict[str, object] = {
        "user_id": user_id,
        "integration_id": integration_id,
        "status": "created",
        "created_at": datetime.now(UTC),
    }
    data.update(overrides)
    return UserIntegrationDocument.model_validate(data)


class TestUserIntegrationsRepository:
    async def test_create_get_and_exists(self, repo):
        await repo.create(_ui("u", "slack", status="connected"))
        got = await repo.get_for_user("u", "slack")
        assert got is not None and got.status == "connected"
        assert await repo.exists("u", "slack") is True
        assert await repo.exists("u", "github") is False

    async def test_scoped_to_user(self, repo):
        await repo.create(_ui("owner", "slack"))
        assert await repo.get_for_user("intruder", "slack") is None
        assert await repo.exists("intruder", "slack") is False

    async def test_list_newest_first(self, repo):
        await repo.create(_ui("u", "old", created_at=datetime(2026, 1, 1, tzinfo=UTC)))
        await repo.create(_ui("u", "new", created_at=datetime(2026, 2, 1, tzinfo=UTC)))
        await repo.create(_ui("other", "theirs"))

        listed = await repo.list_for_user_newest_first("u")
        assert [d.integration_id for d in listed] == ["new", "old"]  # created_at desc

    async def test_delete_for_user_is_scoped(self, repo):
        await repo.create(_ui("u", "slack"))
        assert await repo.delete_for_user("other", "slack") is False
        assert await repo.delete_for_user("u", "slack") is True
        assert await repo.exists("u", "slack") is False

    async def test_connected_at_roundtrips(self, repo):
        when = datetime.now(UTC) - timedelta(hours=1)
        await repo.create(_ui("u", "gmail", status="connected", connected_at=when))
        got = await repo.get_for_user("u", "gmail")
        assert got is not None and got.connected_at is not None

    async def test_is_expired_separates_a_dead_connection_from_one_never_made(self, repo):
        # The whole point of the pair: "not connected" is not one state. Only the
        # stored record tells a grant that died from one that was never granted.
        await repo.create(_ui("u", "gmail", status="expired"))
        await repo.create(_ui("u", "slack", status="created"))
        await repo.create(_ui("u", "notion", status="connected"))

        assert await repo.is_expired("u", "gmail") is True
        assert await repo.is_expired("u", "slack") is False
        assert await repo.is_expired("u", "notion") is False
        assert await repo.is_expired("u", "never_added") is False

        assert await repo.is_connected("u", "gmail") is False
        assert await repo.is_connected("u", "notion") is True

    async def test_is_expired_is_scoped_to_the_user(self, repo):
        await repo.create(_ui("owner", "gmail", status="expired"))
        assert await repo.is_expired("intruder", "gmail") is False


class TestSetStatusStamps:
    """The expiry stamps every downstream reader branches on; the service layer's tests use a fake repo, so this is the only proof of the real document shape."""

    async def test_expiring_stamps_when_and_why_the_grant_died(self, repo):
        await repo.create(_ui("u", "gmail", status="connected"))

        assert await repo.set_status(
            "u", "gmail", status="expired", expired_reason="refresh_token_revoked"
        )

        doc = await repo.get_for_user("u", "gmail")
        assert doc.status == "expired"
        assert doc.expired_reason == "refresh_token_revoked"
        assert doc.expired_at is not None

    async def test_reconnecting_clears_the_stamps_so_it_does_not_read_as_broken(self, repo):
        """A live record carrying a stale expired_at looks dead to anything that reads it."""
        await repo.create(_ui("u", "gmail", status="connected"))
        await repo.set_status("u", "gmail", status="expired", expired_reason="revoked")

        assert await repo.set_status("u", "gmail", status="connected")

        doc = await repo.get_for_user("u", "gmail")
        assert doc.status == "connected"
        assert doc.expired_at is None
        assert doc.expired_reason is None
        assert doc.connected_at is not None

    async def test_saving_accounts_round_trips_them_with_their_primary(self, repo):
        await repo.create(_ui("u", "gmail", status="created"))
        accounts = [
            IntegrationAccount(connected_account_id="ca_1", label="work@acme.com"),
            IntegrationAccount(
                connected_account_id="ca_2",
                label="me@gmail.com",
                identity={"email": "me@gmail.com"},
            ),
        ]

        saved = await repo.save_accounts(
            "u", "gmail", accounts=accounts, primary_account_id="ca_2", status="connected"
        )

        stored = await repo.get_for_user("u", "gmail")
        assert stored == saved
        assert [a.connected_account_id for a in stored.accounts] == ["ca_1", "ca_2"]
        assert stored.accounts[1].identity == {"email": "me@gmail.com"}
        assert stored.primary_account_id == "ca_2"
        assert stored.status == "connected"
        assert stored.connected_at is not None

    async def test_saving_accounts_creates_the_record_when_the_callback_is_first(self, repo):
        saved = await repo.save_accounts(
            "u",
            "gmail",
            accounts=[IntegrationAccount(connected_account_id="ca_1", label="a")],
            primary_account_id="ca_1",
            status="connected",
        )

        assert saved.created_at is not None
        assert (await repo.get_for_user("u", "gmail")) is not None

    async def test_every_account_dead_stamps_the_expiry_and_a_revival_clears_it(self, repo):
        dead = IntegrationAccount(connected_account_id="ca_1", label="a", status="expired")
        await repo.save_accounts(
            "u",
            "gmail",
            accounts=[dead],
            primary_account_id="ca_1",
            status="expired",
            expired_reason="revoked",
        )
        expired = await repo.get_for_user("u", "gmail")
        assert expired.expired_at is not None
        assert expired.expired_reason == "revoked"

        live = dead.model_copy(update={"status": "connected"})
        await repo.save_accounts(
            "u", "gmail", accounts=[live], primary_account_id="ca_1", status="connected"
        )

        revived = await repo.get_for_user("u", "gmail")
        assert revived.expired_at is None
        assert revived.expired_reason is None

    async def test_a_status_write_keeps_the_accounts(self, repo):
        await repo.save_accounts(
            "u",
            "gmail",
            accounts=[IntegrationAccount(connected_account_id="ca_1", label="a")],
            primary_account_id="ca_1",
            status="connected",
        )

        await repo.set_status("u", "gmail", status="created")

        assert [
            a.connected_account_id for a in (await repo.get_for_user("u", "gmail")).accounts
        ] == ["ca_1"]

    async def test_it_is_scoped_to_the_owning_user(self, repo):
        await repo.create(_ui("owner", "gmail", status="connected"))
        await repo.create(_ui("stranger", "gmail", status="connected"))

        await repo.set_status("owner", "gmail", status="expired", expired_reason="revoked")

        assert (await repo.get_for_user("stranger", "gmail")).status == "connected"
