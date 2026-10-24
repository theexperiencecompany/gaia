"""Where the user is: their inbound stamps per surface, and what each run reads off them."""

from datetime import UTC, datetime

import fakeredis.aioredis

from app.constants.notifications import (
    PRESENCE_ACTIVE_WINDOW_SECONDS,
    PRESENCE_RETENTION_SECONDS,
)
from app.models.chat_models import ConversationSource
from app.models.presence_models import PresenceSnapshot
from app.services.delivery.presence import (
    active_bot_platform,
    previous_surface,
    read_presence,
    record_turn_presence,
    surfaces_by_recency,
)

USER_ID = "6acc0dac0cc0a00000000001"
KEY = f"user_presence:{USER_ID}"
NOW = 1_800_000_000
WINDOW = PRESENCE_ACTIVE_WINDOW_SECONDS


def _snapshot(**last_seen: int) -> PresenceSnapshot:
    return {"captured_at": NOW, "last_seen": dict(last_seen)}


def _epoch() -> int:
    return int(datetime.now(UTC).timestamp())


class TestRecordTurnPresence:
    async def test_returns_the_state_before_this_turn(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await fake_redis.hset(KEY, mapping={"web": str(NOW - 1500)})

        before = await record_turn_presence(USER_ID, ConversationSource.TELEGRAM)

        assert before["last_seen"] == {"web": NOW - 1500}

    async def test_stamps_this_turns_surface_at_now(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        start = _epoch()

        await record_turn_presence(USER_ID, ConversationSource.TELEGRAM)

        stored = await fake_redis.hgetall(KEY)
        assert stored.keys() == {"telegram"}
        assert start <= int(stored["telegram"]) <= _epoch()

    async def test_the_key_is_kept_for_the_retention_window_not_the_active_one(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await record_turn_presence(USER_ID, ConversationSource.WEB)

        ttl = await fake_redis.ttl(KEY)
        assert PRESENCE_RETENTION_SECONDS - 5 <= ttl <= PRESENCE_RETENTION_SECONDS

    async def test_a_second_turn_sees_the_first(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await record_turn_presence(USER_ID, ConversationSource.WEB)

        before = await record_turn_presence(USER_ID, ConversationSource.TELEGRAM)

        assert before["last_seen"].keys() == {"web"}

    async def test_junk_fields_are_dropped(self, fake_redis: fakeredis.aioredis.FakeRedis) -> None:
        await fake_redis.hset(
            KEY,
            mapping={"carrier_pigeon": str(NOW), "slack": "yesterday", "discord": str(NOW - 30)},
        )

        before = await record_turn_presence(USER_ID, ConversationSource.WEB)

        assert before["last_seen"] == {"discord": NOW - 30}


class TestReadPresence:
    async def test_reads_the_users_stamps(self, fake_redis: fakeredis.aioredis.FakeRedis) -> None:
        await fake_redis.hset(KEY, mapping={"whatsapp": str(NOW - 30), "web": str(NOW - 60)})

        snapshot = await read_presence(USER_ID)

        assert snapshot["last_seen"] == {"whatsapp": NOW - 30, "web": NOW - 60}

    async def test_an_unknown_user_reads_empty(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        assert (await read_presence(USER_ID))["last_seen"] == {}


class TestSurfacesByRecency:
    def test_newest_first(self) -> None:
        ranked = surfaces_by_recency(_snapshot(web=NOW - 600, telegram=NOW - 60, slack=NOW - 9000))

        assert ranked == [
            (ConversationSource.TELEGRAM, NOW - 60),
            (ConversationSource.WEB, NOW - 600),
            (ConversationSource.SLACK, NOW - 9000),
        ]

    def test_unknown_surfaces_are_skipped(self) -> None:
        assert surfaces_by_recency(_snapshot(carrier_pigeon=NOW)) == []


class TestPreviousSurface:
    def test_the_newest_other_surface_is_where_they_came_from(self) -> None:
        snapshot = _snapshot(web=NOW - 1500, whatsapp=NOW - 9000)

        assert previous_surface(snapshot, ConversationSource.TELEGRAM) is ConversationSource.WEB

    def test_staying_on_the_same_surface_is_no_switch(self) -> None:
        snapshot = _snapshot(telegram=NOW - 60, web=NOW - 1500)

        assert previous_surface(snapshot, ConversationSource.TELEGRAM) is None

    def test_nothing_seen_before_is_no_switch(self) -> None:
        assert previous_surface(_snapshot(), ConversationSource.TELEGRAM) is None


class TestActiveBotPlatform:
    def test_the_newest_platform_inside_the_window_wins(self) -> None:
        snapshot = _snapshot(whatsapp=NOW - 600, telegram=NOW - 60)

        assert active_bot_platform(snapshot, NOW) is ConversationSource.TELEGRAM

    def test_a_platform_last_used_outside_the_window_is_ignored(self) -> None:
        snapshot = _snapshot(telegram=NOW - WINDOW - 1, slack=NOW - WINDOW)

        assert active_bot_platform(snapshot, NOW) is ConversationSource.SLACK

    def test_everything_stale_is_none(self) -> None:
        assert active_bot_platform(_snapshot(telegram=NOW - WINDOW - 1), NOW) is None

    def test_web_only_activity_names_no_bot_platform(self) -> None:
        assert active_bot_platform(_snapshot(web=NOW, desktop=NOW), NOW) is None

    def test_a_newer_web_turn_does_not_hide_the_bot_platform(self) -> None:
        snapshot = _snapshot(web=NOW, whatsapp=NOW - 120)

        assert active_bot_platform(snapshot, NOW) is ConversationSource.WHATSAPP

    def test_unknown_field_names_are_ignored(self) -> None:
        snapshot = _snapshot(carrier_pigeon=NOW, background=NOW, discord=NOW - 30)

        assert active_bot_platform(snapshot, NOW) is ConversationSource.DISCORD

    def test_no_entries_is_none(self) -> None:
        assert active_bot_platform(_snapshot(), NOW) is None
