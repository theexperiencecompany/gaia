"""Contract tests for UserIntegrationsRepository (user-scoped, per-integration)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.user_integrations import UserIntegrationsRepository
from app.models.integration_models import UserIntegrationDocument


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
    """The expiry stamps are what every reader downstream branches on: the
    integrations page renders "Disconnected <n> ago" from ``expired_at``, and the
    connect prompt tells "expired" from "never connected" by the status alone.
    The service layer's tests run against a fake repo, so this is the only place
    the real document shape is proven."""

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
        """A live record carrying a stale ``expired_at`` looks dead to anything
        that reads it."""
        await repo.create(_ui("u", "gmail", status="connected"))
        await repo.set_status("u", "gmail", status="expired", expired_reason="revoked")

        assert await repo.set_status("u", "gmail", status="connected")

        doc = await repo.get_for_user("u", "gmail")
        assert doc.status == "connected"
        assert doc.expired_at is None
        assert doc.expired_reason is None
        assert doc.connected_at is not None

    async def test_the_account_that_died_is_recorded_and_never_cleared(self, repo):
        """The id of the account that died is what lets us address it after the
        fact, so a later write that does not know it must not erase it."""
        await repo.create(_ui("u", "gmail", status="created"))

        await repo.set_status("u", "gmail", status="connected", connected_account_id="ca_1")
        assert (await repo.get_for_user("u", "gmail")).connected_account_id == "ca_1"

        await repo.set_status("u", "gmail", status="expired", expired_reason="revoked")
        assert (await repo.get_for_user("u", "gmail")).connected_account_id == "ca_1"

    async def test_it_is_scoped_to_the_owning_user(self, repo):
        await repo.create(_ui("owner", "gmail", status="connected"))
        await repo.create(_ui("stranger", "gmail", status="connected"))

        await repo.set_status("owner", "gmail", status="expired", expired_reason="revoked")

        assert (await repo.get_for_user("stranger", "gmail")).status == "connected"
