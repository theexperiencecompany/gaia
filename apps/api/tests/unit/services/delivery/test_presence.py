"""Where the user is: their inbound stamps per surface, and what each run reads off them."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import fakeredis.aioredis

from app.constants.notifications import (
    PRESENCE_ACTIVE_WINDOW_SECONDS,
    PRESENCE_RETENTION_SECONDS,
)
from app.models.chat_models import ConversationSource
from app.models.presence_models import PresenceSnapshot
from app.services.delivery import presence as presence_module
from app.services.delivery.presence import (
    active_surface,
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


class TestRecordTurnPresenceStorage:
    async def test_the_reads_and_writes_run_in_one_transaction(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        with patch.object(fake_redis, "pipeline", wraps=fake_redis.pipeline) as pipeline:
            await record_turn_presence(USER_ID, ConversationSource.TELEGRAM)

        pipeline.assert_called_once_with(transaction=True)

    async def test_the_snapshot_is_captured_at_the_stamped_now(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        with patch.object(presence_module, "_now_epoch", return_value=NOW):
            before = await record_turn_presence(USER_ID, ConversationSource.TELEGRAM)

        assert before["captured_at"] == NOW
        assert await fake_redis.hgetall(KEY) == {"telegram": str(NOW)}

    async def test_the_key_is_kept_for_exactly_thirty_days(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await record_turn_presence(USER_ID, ConversationSource.WEB)

        assert 2_592_000 - 5 <= await fake_redis.ttl(KEY) <= 2_592_000

    async def test_the_active_window_is_exactly_three_hours(self) -> None:
        assert WINDOW == 10_800


class TestNow:
    def test_now_is_read_in_utc(self) -> None:
        clock = MagicMock()
        clock.now.return_value = datetime(2026, 10, 24, 17, 2, tzinfo=UTC)

        with patch.object(presence_module, "datetime", clock):
            assert presence_module._now_epoch() == _epoch_of(2026, 10, 24, 17, 2)

        clock.now.assert_called_once_with(UTC)


def _epoch_of(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp())


class TestReadPresence:
    async def test_reads_the_users_stamps(self, fake_redis: fakeredis.aioredis.FakeRedis) -> None:
        await fake_redis.hset(KEY, mapping={"whatsapp": str(NOW - 30), "web": str(NOW - 60)})

        snapshot = await read_presence(USER_ID)

        assert snapshot["last_seen"] == {"whatsapp": NOW - 30, "web": NOW - 60}

    async def test_the_snapshot_is_captured_at_now(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        with patch.object(presence_module, "_now_epoch", return_value=NOW):
            snapshot = await read_presence(USER_ID)

        assert snapshot["captured_at"] == NOW

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


class TestActiveSurface:
    def test_the_newest_surface_inside_the_window_wins(self) -> None:
        snapshot = _snapshot(whatsapp=NOW - 600, telegram=NOW - 60)

        assert active_surface(snapshot, NOW) is ConversationSource.TELEGRAM

    def test_a_web_turn_newer_than_a_chat_app_turn_is_where_they_are(self) -> None:
        snapshot = _snapshot(web=NOW - 30, telegram=NOW - 120)

        assert active_surface(snapshot, NOW) is ConversationSource.WEB

    def test_a_surface_at_the_window_edge_is_still_active(self) -> None:
        assert active_surface(_snapshot(slack=NOW - WINDOW), NOW) is ConversationSource.SLACK

    def test_everything_outside_the_window_is_none(self) -> None:
        snapshot = _snapshot(telegram=NOW - WINDOW - 1, web=NOW - WINDOW - 60)

        assert active_surface(snapshot, NOW) is None

    def test_background_stamps_are_not_a_surface_the_user_is_on(self) -> None:
        snapshot = _snapshot(carrier_pigeon=NOW, background=NOW, discord=NOW - 30)

        assert active_surface(snapshot, NOW) is ConversationSource.DISCORD

    def test_no_entries_is_none(self) -> None:
        assert active_surface(_snapshot(), NOW) is None
