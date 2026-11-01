"""Contract tests for UserIntegrationsRepository (user-scoped, per-integration)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
import uuid

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.agents.tools.integration_account_tools import rename_integration_account
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
            IntegrationAccount(id="ca_1", connected_account_id="ca_1", label="work@acme.com"),
            IntegrationAccount(
                id="ca_2",
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
            accounts=[IntegrationAccount(id="ca_1", connected_account_id="ca_1", label="a")],
            primary_account_id="ca_1",
            status="connected",
        )

        assert saved.created_at is not None
        assert (await repo.get_for_user("u", "gmail")) is not None

    async def test_every_account_dead_stamps_the_expiry_and_a_revival_clears_it(self, repo):
        dead = IntegrationAccount(
            id="ca_1", connected_account_id="ca_1", label="a", status="expired"
        )
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
            accounts=[IntegrationAccount(id="ca_1", connected_account_id="ca_1", label="a")],
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


# The rename tool reports analytics, whose user id must be a Mongo ObjectId.
OWNER_ID = "6812f0b3c9a14e2b7d5a91cc"


class TestConcurrentAccountWrites:
    async def test_two_accounts_renamed_at_once_both_keep_their_names(self, repo):
        """Seen live: the agent renamed two accounts in parallel, both calls reported success, and one name was lost."""
        await repo.save_accounts(
            OWNER_ID,
            "gmail",
            accounts=[
                IntegrationAccount(id="ca_1", connected_account_id="ca_1", label="work@acme.com"),
                IntegrationAccount(id="ca_2", connected_account_id="ca_2", label="me@gmail.com"),
            ],
            primary_account_id="ca_2",
            status="connected",
        )
        config = {"metadata": {"user_id": OWNER_ID}}

        results = await asyncio.gather(
            rename_integration_account.ainvoke(
                {"integration_id": "gmail", "account": "work@acme.com", "name": "Work"},
                config=config,
            ),
            rename_integration_account.ainvoke(
                {"integration_id": "gmail", "account": "me@gmail.com", "name": "Personal"},
                config=config,
            ),
        )

        assert results == ["Renamed work@acme.com to Work.", "Renamed me@gmail.com to Personal."]
        stored = await repo.get_for_user(OWNER_ID, "gmail")
        assert [(a.connected_account_id, a.nickname) for a in stored.accounts] == [
            ("ca_1", "Work"),
            ("ca_2", "Personal"),
        ]
        assert stored.primary_account_id == "ca_2"

    async def test_naming_an_account_touches_only_that_account(self, repo):
        await repo.save_accounts(
            OWNER_ID,
            "gmail",
            accounts=[
                IntegrationAccount(
                    id="ca_1", connected_account_id="ca_1", label="a", nickname="Old"
                ),
                IntegrationAccount(
                    id="ca_2", connected_account_id="ca_2", label="b", status="expired"
                ),
            ],
            primary_account_id="ca_1",
            status="connected",
        )

        named = await repo.set_account_nickname(OWNER_ID, "gmail", "ca_2", "Side")

        assert named is not None
        assert [(a.nickname, a.status) for a in named.accounts] == [
            ("Old", "connected"),
            ("Side", "expired"),
        ]
        assert named == await repo.get_for_user(OWNER_ID, "gmail")

    async def test_naming_an_account_the_record_lacks_changes_nothing(self, repo):
        await repo.save_accounts(
            OWNER_ID,
            "gmail",
            accounts=[IntegrationAccount(id="ca_1", connected_account_id="ca_1", label="a")],
            primary_account_id="ca_1",
            status="connected",
        )

        assert await repo.set_account_nickname(OWNER_ID, "gmail", "ca_gone", "X") is None
        assert await repo.set_account_nickname("stranger", "gmail", "ca_1", "X") is None
        assert (await repo.get_for_user(OWNER_ID, "gmail")).accounts[0].nickname is None


class TestTheReadCache:
    """A read after any write sees the write, never the record cached before it.

    Account records are read on every tool call and trigger event, so they live in Redis.
    """

    @pytest.fixture
    def repo(self, raw_collection, redis) -> UserIntegrationsRepository:
        return UserIntegrationsRepository()

    @staticmethod
    def _account(account_id: str, **fields: object) -> IntegrationAccount:
        return IntegrationAccount(
            id=account_id,
            connected_account_id=f"composio_{account_id}",
            label=f"{account_id}@acme.com",
            **fields,
        )

    async def test_a_read_is_served_from_redis_once_cached(self, repo, raw_collection):
        await repo.save_accounts(
            "u",
            "gmail",
            accounts=[self._account("acct_1")],
            primary_account_id="acct_1",
            status="connected",
        )
        first = await repo.get_for_user("u", "gmail")
        # Written behind the repository's back: only a cached read still sees the old record.
        await raw_collection.update_one({"user_id": "u"}, {"$set": {"status": "expired"}})

        assert (await repo.get_for_user("u", "gmail")) == first

    async def test_saving_accounts_is_seen_by_the_next_read(self, repo):
        await repo.save_accounts(
            "u",
            "gmail",
            accounts=[self._account("acct_1")],
            primary_account_id="acct_1",
            status="connected",
        )
        await repo.get_for_user("u", "gmail")
        await repo.list_for_user("u")

        await repo.save_accounts(
            "u",
            "gmail",
            accounts=[self._account("acct_1"), self._account("acct_2")],
            primary_account_id="acct_2",
            status="connected",
        )

        stored = await repo.get_for_user("u", "gmail")
        assert [a.id for a in stored.accounts] == ["acct_1", "acct_2"]
        assert stored.primary_account_id == "acct_2"
        [listed] = await repo.list_for_user("u")
        assert listed.primary_account_id == "acct_2"

    async def test_a_page_of_the_list_is_cached_apart_from_the_whole_list(self, repo):
        for integration_id in ("github", "gmail", "notion"):
            await repo.save_accounts(
                "u",
                integration_id,
                accounts=[self._account(f"acct_{integration_id}")],
                primary_account_id=f"acct_{integration_id}",
                status="connected",
            )
        by_name = [("integration_id", 1)]

        first_two = await repo.list_for_user("u", sort=by_name, limit=2)
        after_first = await repo.list_for_user("u", sort=by_name, skip=1)
        everything = await repo.list_for_user("u", sort=by_name)

        assert [d.integration_id for d in first_two] == ["github", "gmail"]
        assert [d.integration_id for d in after_first] == ["gmail", "notion"]
        assert [d.integration_id for d in everything] == ["github", "gmail", "notion"]

    async def test_naming_an_account_is_seen_by_the_next_read(self, repo):
        await repo.save_accounts(
            "u",
            "gmail",
            accounts=[self._account("acct_1")],
            primary_account_id="acct_1",
            status="connected",
        )
        await repo.get_for_user("u", "gmail")

        await repo.set_account_nickname("u", "gmail", "acct_1", "Work")

        assert (await repo.get_for_user("u", "gmail")).accounts[0].nickname == "Work"

    async def test_removing_the_record_is_seen_by_the_next_read(self, repo):
        await repo.save_accounts(
            "u",
            "gmail",
            accounts=[self._account("acct_1")],
            primary_account_id="acct_1",
            status="connected",
        )
        await repo.get_for_user("u", "gmail")

        await repo.delete_for_user("u", "gmail")

        assert await repo.get_for_user("u", "gmail") is None

    async def test_one_users_write_leaves_anothers_cached_record_alone(self, repo):
        for user in ("u", "v"):
            await repo.save_accounts(
                user,
                "gmail",
                accounts=[self._account("acct_1")],
                primary_account_id="acct_1",
                status="connected",
            )
            await repo.get_for_user(user, "gmail")

        await repo.set_account_nickname("u", "gmail", "acct_1", "Work")

        assert (await repo.get_for_user("v", "gmail")).accounts[0].nickname is None


SeedIntegration = Callable[..., Awaitable[None]]


@pytest.fixture
async def seed_integration(raw_collection) -> AsyncIterator[SeedIntegration]:
    """Seed the real gaia_test.integrations: a $lookup binds by collection name, not through the patched accessor."""
    coll: AsyncIOMotorCollection = raw_collection.database["integrations"]
    seeded: list[str] = []

    async def _seed(integration_id: str, **fields: object) -> None:
        await coll.insert_one({"integration_id": integration_id, **fields})
        seeded.append(integration_id)

    yield _seed
    await coll.delete_many({"integration_id": {"$in": seeded}})


class TestToolsForConnected:
    """The stored tool list is the server's; this is the read that scopes it to one user."""

    async def test_only_the_users_connected_integrations_are_returned(self, repo, seed_integration):
        posthog, context7, linear = (f"{name}-{uuid.uuid4().hex}" for name in ("ph", "c7", "ln"))
        await seed_integration(posthog, name="PostHog", tools=[{"name": "search"}])
        await seed_integration(context7, name="Context7", tools=[{"name": "resolve"}])
        await seed_integration(linear, name="Linear", tools=[{"name": "issues"}])
        await repo.create(_ui("a", posthog, status="connected"))
        await repo.create(_ui("a", context7, status="created"))
        await repo.create(_ui("b", linear, status="connected"))

        [record] = await repo.tools_for_connected("a")

        assert record.integration_id == posthog
        assert record.name == "PostHog"
        assert [tool.name for tool in record.tools] == ["search"]

    async def test_a_connected_integration_without_stored_tools_is_skipped(
        self, repo, seed_integration
    ):
        bare, empty = f"bare-{uuid.uuid4().hex}", f"empty-{uuid.uuid4().hex}"
        await seed_integration(bare, name="Bare")
        await seed_integration(empty, name="Empty", tools=[])
        await repo.create(_ui("a", bare, status="connected"))
        await repo.create(_ui("a", empty, status="connected"))

        assert await repo.tools_for_connected("a") == []

    async def test_one_users_disconnect_leaves_anothers_tools(self, repo, seed_integration):
        posthog = f"ph-{uuid.uuid4().hex}"
        await seed_integration(posthog, name="PostHog", tools=[{"name": "search"}])
        await repo.create(_ui("a", posthog, status="connected"))
        await repo.create(_ui("b", posthog, status="connected"))

        await repo.set_status("a", posthog, status="created")

        assert await repo.tools_for_connected("a") == []
        assert [r.integration_id for r in await repo.tools_for_connected("b")] == [posthog]
