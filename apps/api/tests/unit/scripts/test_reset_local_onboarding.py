"""Unit tests for the local onboarding reset tool.

Two things make it safe to keep in the repo: it refuses anything that is not a
loopback dev stack, and ``--dry-run`` (the default) never writes.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from scripts.reset_local_onboarding import (
    NotALocalStackError,
    assert_local_stack,
    is_local_url,
    run_reset,
    unlink_every_platform,
)

MODULE = "scripts.reset_local_onboarding"
LOCAL_MONGO = "mongodb://localhost:27017/gaia"
LOCAL_REDIS = "redis://localhost:6379"


@pytest.mark.parametrize(
    "url",
    [
        LOCAL_MONGO,
        "mongodb://user:pw@127.0.0.1:27017/gaia?authSource=admin",
        "mongodb://localhost:27017,127.0.0.1:27018/gaia",
        "redis://[::1]:6379/0",
    ],
)
def test_loopback_urls_are_local(url: str) -> None:
    assert is_local_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "mongodb+srv://user:pw@cluster0.example.mongodb.net/gaia",
        "mongodb://user:pw@mongo.internal:27017/gaia",
        "mongodb://localhost:27017,mongo.internal:27017/gaia",
        "redis://redis:6379",
        "",
    ],
)
def test_remote_urls_are_not_local(url: str) -> None:
    assert not is_local_url(url)


class TestAssertLocalStack:
    def test_accepts_a_dev_loopback_stack(self) -> None:
        assert_local_stack("development", LOCAL_MONGO, LOCAL_REDIS)

    @pytest.mark.parametrize(
        ("env", "mongo", "redis"),
        [
            ("production", LOCAL_MONGO, LOCAL_REDIS),
            ("development", "mongodb://user:pw@mongo.internal:27017/gaia", LOCAL_REDIS),
            ("development", LOCAL_MONGO, "redis://redis:6379"),
        ],
    )
    def test_refuses_anything_that_is_not_local(self, env: str, mongo: str, redis: str) -> None:
        with pytest.raises(NotALocalStackError):
            assert_local_stack(env, mongo, redis)


def _dev_settings() -> MagicMock:
    s = MagicMock()
    s.ENV = "development"
    s.MONGO_DB = LOCAL_MONGO
    s.REDIS_URL = LOCAL_REDIS
    return s


class TestRunReset:
    async def test_dry_run_lists_users_and_writes_nothing(self) -> None:
        repo = MagicMock()
        repo.list_all_ids = AsyncMock(return_value=["u1", "u2"])
        reset = AsyncMock()
        flush = AsyncMock()
        subscriptions = MagicMock()
        subscriptions.delete_all_for_user = AsyncMock()
        unlink = AsyncMock()
        with (
            patch(f"{MODULE}.settings", _dev_settings()),
            patch(f"{MODULE}.user_repository", repo),
            patch(f"{MODULE}.subscription_repository", subscriptions),
            patch(f"{MODULE}.reset_onboarding", reset),
            patch(f"{MODULE}.unlink_every_platform", unlink),
            patch(f"{MODULE}.flush_local_redis", flush),
        ):
            result = await run_reset(dry_run=True)

        assert result.user_ids == ["u1", "u2"]
        assert result.users_reset == 0
        reset.assert_not_awaited()
        subscriptions.delete_all_for_user.assert_not_awaited()
        unlink.assert_not_awaited()
        flush.assert_not_awaited()

    async def test_execute_resets_every_user_keeping_connections_then_flushes_redis(self) -> None:
        repo = MagicMock()
        repo.list_all_ids = AsyncMock(return_value=["u1", "u2"])
        reset = AsyncMock()
        flush = AsyncMock(return_value=7)
        subscriptions = MagicMock()
        subscriptions.delete_all_for_user = AsyncMock(side_effect=[2, 0])
        unlink = AsyncMock(side_effect=[1, 0])
        with (
            patch(f"{MODULE}.settings", _dev_settings()),
            patch(f"{MODULE}.user_repository", repo),
            patch(f"{MODULE}.subscription_repository", subscriptions),
            patch(f"{MODULE}.reset_onboarding", reset),
            patch(f"{MODULE}.unlink_every_platform", unlink),
            patch(f"{MODULE}.flush_local_redis", flush),
        ):
            result = await run_reset(dry_run=False)

        assert [c.args for c in reset.await_args_list] == [("u1",), ("u2",)]
        assert all(c.kwargs == {"keep_connections": True} for c in reset.await_args_list)
        assert [c.args for c in subscriptions.delete_all_for_user.await_args_list] == [
            ("u1",),
            ("u2",),
        ]
        assert result.users_reset == 2
        assert result.subscriptions_deleted == 2
        assert [c.args for c in unlink.await_args_list] == [("u1",), ("u2",)]
        assert result.platforms_unlinked == 1
        assert result.redis_keys_deleted == 7
        flush.assert_awaited_once()

    async def test_refuses_a_remote_stack_before_reading_any_user(self) -> None:
        prod = _dev_settings()
        prod.MONGO_DB = "mongodb+srv://user:pw@cluster0.example.mongodb.net/gaia"
        repo = MagicMock()
        repo.list_all_ids = AsyncMock(return_value=["u1"])
        with (
            patch(f"{MODULE}.settings", prod),
            patch(f"{MODULE}.user_repository", repo),
            pytest.raises(NotALocalStackError),
        ):
            await run_reset(dry_run=False)
        repo.list_all_ids.assert_not_awaited()


class TestUnlinkEveryPlatform:
    async def test_unlinks_each_linked_platform_of_that_user(self) -> None:
        repo = MagicMock()
        repo.get = AsyncMock(return_value=MagicMock())
        repo.unlink_platform = AsyncMock()
        with (
            patch(f"{MODULE}.user_repository", repo),
            patch(f"{MODULE}.linked_platforms_of", return_value={"telegram": {}, "whatsapp": {}}),
        ):
            unlinked = await unlink_every_platform("u1")

        assert unlinked == 2
        assert [c.args for c in repo.unlink_platform.await_args_list] == [
            ("u1", "telegram"),
            ("u1", "whatsapp"),
        ]

    async def test_a_missing_user_unlinks_nothing(self) -> None:
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        repo.unlink_platform = AsyncMock()
        with patch(f"{MODULE}.user_repository", repo):
            assert await unlink_every_platform("gone") == 0
        repo.unlink_platform.assert_not_awaited()
