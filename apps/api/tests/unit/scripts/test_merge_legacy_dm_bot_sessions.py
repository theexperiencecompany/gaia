"""Unit tests for the legacy ``:dm`` bot-session merge.

The script decides which of two forked sessions survives before it writes
anything, so the selection is pure and pinned here. The write path is asserted
against a fake collection — what it must never do is leave a ``:dm`` row behind
or drop the newer conversation.
"""

from typing import Any

import pytest

from app.scripts.merge_legacy_dm_bot_sessions import (
    MergeAction,
    _apply_merges,
    _dm_channel_of,
    last_used,
    plan_merge,
)

#: The prod user whose Telegram DM forked across the two key formats.
TELEGRAM_USER = "6222050155"
LEGACY_KEY = f"telegram:{TELEGRAM_USER}:dm"
CANONICAL_KEY = f"telegram:{TELEGRAM_USER}:{TELEGRAM_USER}"


def _row(session_key: str, conversation_id: str, updated_at: str, **extra: Any) -> dict[str, Any]:
    return {
        "session_key": session_key,
        "conversation_id": conversation_id,
        "platform": "telegram",
        "platform_user_id": TELEGRAM_USER,
        "channel_id": None,
        "updated_at": updated_at,
        **extra,
    }


class _FakeCollection:
    """Records every write so the test asserts the filter AND the update."""

    def __init__(self) -> None:
        self.updates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.deletes: list[dict[str, Any]] = []

    async def update_one(self, filt: dict[str, Any], update: dict[str, Any]) -> None:
        self.updates.append((filt, update))

    async def delete_one(self, filt: dict[str, Any]) -> None:
        self.deletes.append(filt)


class TestPlanMerge:
    def test_a_lone_legacy_row_is_renamed_onto_the_canonical_key(self) -> None:
        """Nothing to lose: the conversation moves to the key the code now reads."""
        merge = plan_merge(_row(LEGACY_KEY, "conv-legacy", "2026-08-16T09:23:00+00:00"), None)

        assert merge is not None
        assert merge.action is MergeAction.RENAME
        assert merge.canonical_key == CANONICAL_KEY
        assert merge.surviving_conversation_id == "conv-legacy"
        assert merge.orphaned_conversation_id is None

    def test_the_newer_legacy_conversation_wins_and_the_canonical_row_is_repointed(self) -> None:
        merge = plan_merge(
            _row(LEGACY_KEY, "conv-legacy", "2026-08-17T10:00:00+00:00"),
            _row(CANONICAL_KEY, "conv-canonical", "2026-08-16T09:23:00+00:00"),
        )

        assert merge is not None
        assert merge.action is MergeAction.REPOINT
        assert merge.surviving_conversation_id == "conv-legacy"
        assert merge.orphaned_conversation_id == "conv-canonical"

    def test_the_newer_canonical_conversation_wins_and_the_legacy_row_is_dropped(self) -> None:
        """The prod shape: the live chat kept writing the canonical key after the
        workflow delivery last touched the legacy one."""
        merge = plan_merge(
            _row(LEGACY_KEY, "conv-legacy", "2026-08-16T09:23:00+00:00"),
            _row(CANONICAL_KEY, "conv-canonical", "2026-08-16T18:00:00+00:00"),
        )

        assert merge is not None
        assert merge.action is MergeAction.DROP
        assert merge.surviving_conversation_id == "conv-canonical"
        assert merge.orphaned_conversation_id == "conv-legacy"

    def test_an_equal_timestamp_keeps_the_canonical_row(self) -> None:
        """A tie must not repoint — the canonical key is the one in use."""
        stamp = "2026-08-16T09:23:00+00:00"
        merge = plan_merge(
            _row(LEGACY_KEY, "conv-legacy", stamp), _row(CANONICAL_KEY, "conv-canonical", stamp)
        )

        assert merge is not None
        assert merge.action is MergeAction.DROP

    @pytest.mark.parametrize(
        "missing", ["session_key", "platform", "platform_user_id", "conversation_id"]
    )
    def test_an_incomplete_row_is_not_actionable(self, missing: str) -> None:
        row = _row(LEGACY_KEY, "conv-legacy", "2026-08-16T09:23:00+00:00")
        row[missing] = ""

        assert plan_merge(row, None) is None

    def test_a_row_whose_canonical_key_is_itself_is_left_alone(self) -> None:
        """A user literally identified as ``dm`` would map onto its own key; renaming
        it onto itself is a no-op that must not be planned as work."""
        row = _row("telegram:dm:dm", "conv", "2026-08-16T09:23:00+00:00", platform_user_id="dm")

        assert plan_merge(row, None) is None


class TestLastUsed:
    def test_created_at_stands_in_when_the_row_was_never_updated(self) -> None:
        assert last_used({"created_at": "2026-08-16T09:23:00+00:00"}) == "2026-08-16T09:23:00+00:00"

    def test_updated_at_wins_over_created_at(self) -> None:
        row = {"created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-08-16T09:23:00+00:00"}
        assert last_used(row) == "2026-08-16T09:23:00+00:00"

    def test_an_unstamped_row_sorts_oldest(self) -> None:
        assert last_used({}) == ""
        assert last_used({}) < last_used({"created_at": "2026-01-01T00:00:00+00:00"})


def test_dm_channel_of_is_the_platform_user_id() -> None:
    assert _dm_channel_of(CANONICAL_KEY) == TELEGRAM_USER


class TestApplyMerges:
    @pytest.fixture
    def collection(self, monkeypatch: pytest.MonkeyPatch) -> _FakeCollection:
        fake = _FakeCollection()
        monkeypatch.setattr(
            "app.scripts.merge_legacy_dm_bot_sessions.get_async_collection", lambda _name: fake
        )
        return fake

    async def test_rename_moves_the_row_and_stamps_the_dm_channel(
        self, collection: _FakeCollection
    ) -> None:
        """The renamed row must also carry the channel_id the live chat writes, or
        the next claim rewrites it and the row disagrees with its own key."""
        merge = plan_merge(_row(LEGACY_KEY, "conv-legacy", "2026-08-16T09:23:00+00:00"), None)
        assert merge is not None

        assert await _apply_merges([merge]) == 1
        assert collection.updates == [
            (
                {"session_key": LEGACY_KEY},
                {"$set": {"session_key": CANONICAL_KEY, "channel_id": TELEGRAM_USER}},
            )
        ]
        assert collection.deletes == []

    async def test_repoint_moves_the_conversation_then_removes_the_legacy_row(
        self, collection: _FakeCollection
    ) -> None:
        merge = plan_merge(
            _row(LEGACY_KEY, "conv-legacy", "2026-08-17T10:00:00+00:00"),
            _row(CANONICAL_KEY, "conv-canonical", "2026-08-16T09:23:00+00:00"),
        )
        assert merge is not None

        await _apply_merges([merge])

        assert collection.updates == [
            ({"session_key": CANONICAL_KEY}, {"$set": {"conversation_id": "conv-legacy"}})
        ]
        assert collection.deletes == [{"session_key": LEGACY_KEY}]

    async def test_drop_removes_the_legacy_row_and_touches_nothing_else(
        self, collection: _FakeCollection
    ) -> None:
        merge = plan_merge(
            _row(LEGACY_KEY, "conv-legacy", "2026-08-16T09:23:00+00:00"),
            _row(CANONICAL_KEY, "conv-canonical", "2026-08-16T18:00:00+00:00"),
        )
        assert merge is not None

        await _apply_merges([merge])

        assert collection.updates == []
        assert collection.deletes == [{"session_key": LEGACY_KEY}]

    async def test_every_action_leaves_no_legacy_key_behind(
        self, collection: _FakeCollection
    ) -> None:
        """What makes the migration idempotent: a second run finds nothing."""
        merges = [
            plan_merge(_row(LEGACY_KEY, "conv-a", "2026-08-16T09:23:00+00:00"), None),
            plan_merge(
                _row(LEGACY_KEY, "conv-b", "2026-08-17T10:00:00+00:00"),
                _row(CANONICAL_KEY, "conv-c", "2026-08-16T09:23:00+00:00"),
            ),
            plan_merge(
                _row(LEGACY_KEY, "conv-d", "2026-08-16T09:23:00+00:00"),
                _row(CANONICAL_KEY, "conv-e", "2026-08-18T00:00:00+00:00"),
            ),
        ]
        assert all(m is not None for m in merges)

        assert await _apply_merges([m for m in merges if m is not None]) == 3

        renamed_away = [u for u in collection.updates if "session_key" in u[1]["$set"]]
        assert len(renamed_away) + len(collection.deletes) == 3
