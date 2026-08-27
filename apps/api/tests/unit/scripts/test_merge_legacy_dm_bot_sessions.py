"""Unit tests for the legacy ``:dm`` bot-session merge.

The script decides which of two forked sessions survives before it writes
anything, so the selection is pure and pinned here. The write path is asserted
against a fake repository — the seam the script actually talks to. What it must
never do is leave a ``:dm`` row behind or drop the newer conversation. The
repository's own filters and update documents are proven a tier down, in
``tests/unit/db/repositories/test_bot_sessions.py`` and against real Mongo in
``tests/contracts/test_bot_sessions_repository.py``.
"""

from typing import Any

from pymongo.errors import DuplicateKeyError
import pytest

from app.models.bot_models import BotSessionDocument
from app.scripts.merge_legacy_dm_bot_sessions import _apply_merges, canonical_key_for
from app.services.bot_session_merge import (
    MergeAction,
    apply_merge,
    dm_channel_of,
    last_used,
    plan_merge,
)

#: The prod user whose Telegram DM forked across the two key formats.
TELEGRAM_USER = "6222050155"
LEGACY_KEY = f"telegram:{TELEGRAM_USER}:dm"
CANONICAL_KEY = f"telegram:{TELEGRAM_USER}:{TELEGRAM_USER}"


def _session(
    session_key: str, conversation_id: str, updated_at: str | None = None, **extra: Any
) -> BotSessionDocument:
    return BotSessionDocument(
        session_key=session_key,
        conversation_id=conversation_id,
        platform="telegram",
        platform_user_id=TELEGRAM_USER,
        updated_at=updated_at,
        **extra,
    )


class _FakeRepository:
    """Records every call the script makes, and what it answered."""

    def __init__(self, *, renamed: bool = True, deleted: int = 1) -> None:
        self.renamed = renamed
        self.deleted = deleted
        self.repointed = True
        self.rename_raises: Exception | None = None
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def rename_session_key(self, **kwargs: Any) -> bool:
        self.calls.append(("rename_session_key", kwargs))
        if self.rename_raises is not None:
            raise self.rename_raises
        return self.renamed

    async def repoint_conversation(self, **kwargs: Any) -> bool:
        self.calls.append(("repoint_conversation", kwargs))
        return self.repointed

    async def delete_by_session_key(self, session_key: str) -> int:
        self.calls.append(("delete_by_session_key", {"session_key": session_key}))
        return self.deleted


@pytest.fixture
def repository(monkeypatch: pytest.MonkeyPatch) -> _FakeRepository:
    fake = _FakeRepository()
    monkeypatch.setattr("app.services.bot_session_merge.bot_session_repository", fake)
    return fake


class TestPlanMerge:
    def test_a_lone_legacy_row_is_renamed_onto_the_canonical_key(self) -> None:
        """Nothing to lose: the conversation moves to the key the code now reads."""
        merge = plan_merge(
            (legacy := _session(LEGACY_KEY, "conv-legacy", "2026-08-16T09:23:00+00:00")),
            None,
            canonical_key_for(legacy),
        )

        assert merge is not None
        assert merge.action is MergeAction.RENAME
        assert merge.canonical_key == CANONICAL_KEY
        assert merge.surviving_conversation_id == "conv-legacy"
        assert merge.orphaned_conversation_id is None
        # The reason is the operator's only record of WHY a row moved — the plan
        # prints it — so a wrong one sends whoever audits this migration looking
        # for a conflict that never existed.
        assert merge.reason == (
            "no session on the canonical key; the legacy row keeps its conversation"
        )

    def test_the_newer_legacy_conversation_wins_and_the_canonical_row_is_repointed(self) -> None:
        merge = plan_merge(
            (legacy := _session(LEGACY_KEY, "conv-legacy", "2026-08-17T10:00:00+00:00")),
            _session(CANONICAL_KEY, "conv-canonical", "2026-08-16T09:23:00+00:00"),
            canonical_key_for(legacy),
        )

        assert merge is not None
        assert merge.action is MergeAction.REPOINT
        assert merge.canonical_key == CANONICAL_KEY
        assert merge.surviving_conversation_id == "conv-legacy"
        assert merge.orphaned_conversation_id == "conv-canonical"
        assert merge.reason == "the legacy session was used more recently"

    def test_the_newer_canonical_conversation_wins_and_the_legacy_row_is_dropped(self) -> None:
        """The prod shape: the live chat kept writing the canonical key after the
        workflow delivery last touched the legacy one."""
        merge = plan_merge(
            _session(LEGACY_KEY, "conv-legacy", "2026-08-16T09:23:00+00:00"),
            _session(CANONICAL_KEY, "conv-canonical", "2026-08-16T18:00:00+00:00"),
            CANONICAL_KEY,
        )

        assert merge is not None
        assert merge.action is MergeAction.DROP
        assert merge.canonical_key == CANONICAL_KEY
        assert merge.surviving_conversation_id == "conv-canonical"
        assert merge.orphaned_conversation_id == "conv-legacy"
        assert merge.reason == "the canonical session was used more recently"

    def test_an_equal_timestamp_keeps_the_canonical_row(self) -> None:
        """A tie must not repoint — the canonical key is the one in use."""
        stamp = "2026-08-16T09:23:00+00:00"
        merge = plan_merge(
            _session(LEGACY_KEY, "conv-legacy", stamp),
            _session(CANONICAL_KEY, "conv-canonical", stamp),
            CANONICAL_KEY,
        )

        assert merge is not None
        assert merge.action is MergeAction.DROP

    @pytest.mark.parametrize(
        "missing", ["session_key", "platform", "platform_user_id", "conversation_id"]
    )
    def test_an_incomplete_row_is_not_actionable(self, missing: str) -> None:
        fields: dict[str, Any] = {
            "session_key": LEGACY_KEY,
            "conversation_id": "conv-legacy",
            "platform": "telegram",
            "platform_user_id": TELEGRAM_USER,
        }
        fields[missing] = ""

        row = BotSessionDocument(**fields)
        assert plan_merge(row, None, canonical_key_for(row)) is None

    def test_a_row_whose_canonical_key_is_itself_is_left_alone(self) -> None:
        """A user literally identified as ``dm`` would map onto its own key; renaming
        it onto itself is a no-op that must not be planned as work."""
        row = BotSessionDocument(
            session_key="telegram:dm:dm",
            conversation_id="conv",
            platform="telegram",
            platform_user_id="dm",
        )

        assert plan_merge(row, None, canonical_key_for(row)) is None


class TestLastUsed:
    def test_created_at_stands_in_when_the_row_was_never_updated(self) -> None:
        session = _session(LEGACY_KEY, "conv", created_at="2026-08-16T09:23:00+00:00")
        assert last_used(session) == "2026-08-16T09:23:00+00:00"

    def test_updated_at_wins_over_created_at(self) -> None:
        session = _session(
            LEGACY_KEY,
            "conv",
            updated_at="2026-08-16T09:23:00+00:00",
            created_at="2026-01-01T00:00:00+00:00",
        )
        assert last_used(session) == "2026-08-16T09:23:00+00:00"

    def test_an_unstamped_row_sorts_oldest(self) -> None:
        unstamped = _session(LEGACY_KEY, "conv")
        stamped = _session(LEGACY_KEY, "conv", created_at="2026-01-01T00:00:00+00:00")

        assert last_used(unstamped) == ""
        assert last_used(unstamped) < last_used(stamped)


def test_canonical_key_for_uses_the_live_key_derivation() -> None:
    """Not a format restated here: the script must resolve the same key the next
    lookup will."""
    assert canonical_key_for(_session(LEGACY_KEY, "conv")) == CANONICAL_KEY


def test_dm_channel_of_is_the_platform_user_id() -> None:
    assert dm_channel_of(CANONICAL_KEY) == TELEGRAM_USER


def test_dm_channel_of_takes_the_channel_segment_not_the_user() -> None:
    """On Telegram the user and the channel are the same string, so a DM key
    alone cannot tell "last segment" from "middle segment". A key where they
    differ can — and the last segment is what gets stamped onto the row."""
    assert dm_channel_of("discord:user-1:channel-9") == "channel-9"


class TestAWriteRacedByAnotherClaim:
    """Between plan and write another actor can move either row: a workflow
    delivery claiming the canonical key mid-RENAME (the unique index turns
    that into DuplicateKeyError), or the canonical row vanishing mid-REPOINT.
    Both must answer False with the legacy row left in place — never a failed
    user request, never a stranded conversation — so the next flagged message
    replans against the world as it is then."""

    async def test_a_rename_losing_the_canonical_key_race_is_a_no_op(
        self, repository: _FakeRepository
    ) -> None:
        merge = plan_merge(
            (legacy := _session(LEGACY_KEY, "conv-history", "2026-08-16T09:23:00+00:00")),
            None,
            canonical_key_for(legacy),
        )
        assert merge is not None
        repository.rename_raises = DuplicateKeyError("E11000 duplicate key")

        assert await apply_merge(merge) is False
        assert not any(name == "delete_by_session_key" for name, _ in repository.calls)

    async def test_a_repoint_that_matched_nothing_does_not_delete_the_legacy_row(
        self, repository: _FakeRepository
    ) -> None:
        merge = plan_merge(
            (legacy := _session(LEGACY_KEY, "conv-newer", "2026-08-17T10:00:00+00:00")),
            _session(CANONICAL_KEY, "conv-older", "2026-08-16T09:23:00+00:00"),
            canonical_key_for(legacy),
        )
        assert merge is not None
        assert merge.action is MergeAction.REPOINT
        repository.repointed = False  # the canonical row vanished after planning

        assert await apply_merge(merge) is False
        # Deleting now would strand conv-newer with no session pointing at it.
        assert not any(name == "delete_by_session_key" for name, _ in repository.calls)


class TestApplyMerges:
    async def test_rename_moves_the_row_and_stamps_the_dm_channel(
        self, repository: _FakeRepository
    ) -> None:
        merge = plan_merge(
            (legacy := _session(LEGACY_KEY, "conv-legacy", "2026-08-16T09:23:00+00:00")),
            None,
            canonical_key_for(legacy),
        )
        assert merge is not None

        assert await _apply_merges([merge]) == 1
        assert repository.calls == [
            (
                "rename_session_key",
                {
                    "session_key": LEGACY_KEY,
                    "new_session_key": CANONICAL_KEY,
                    "channel_id": TELEGRAM_USER,
                },
            )
        ]

    async def test_repoint_moves_the_conversation_then_removes_the_legacy_row(
        self, repository: _FakeRepository
    ) -> None:
        """Order matters: dropping the legacy row before the canonical row owns its
        conversation would strand the surviving thread."""
        merge = plan_merge(
            (legacy := _session(LEGACY_KEY, "conv-legacy", "2026-08-17T10:00:00+00:00")),
            _session(CANONICAL_KEY, "conv-canonical", "2026-08-16T09:23:00+00:00"),
            canonical_key_for(legacy),
        )
        assert merge is not None

        await _apply_merges([merge])

        assert repository.calls == [
            (
                "repoint_conversation",
                {"session_key": CANONICAL_KEY, "conversation_id": "conv-legacy"},
            ),
            ("delete_by_session_key", {"session_key": LEGACY_KEY}),
        ]

    async def test_drop_removes_the_legacy_row_and_touches_nothing_else(
        self, repository: _FakeRepository
    ) -> None:
        merge = plan_merge(
            _session(LEGACY_KEY, "conv-legacy", "2026-08-16T09:23:00+00:00"),
            _session(CANONICAL_KEY, "conv-canonical", "2026-08-16T18:00:00+00:00"),
            CANONICAL_KEY,
        )
        assert merge is not None

        await _apply_merges([merge])

        assert repository.calls == [("delete_by_session_key", {"session_key": LEGACY_KEY})]

    async def test_a_write_that_matched_nothing_is_not_counted_as_applied(
        self, repository: _FakeRepository, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A silent miss would report success while leaving the fork in place."""
        repository.renamed = False
        merge = plan_merge(
            (legacy := _session(LEGACY_KEY, "conv-legacy", "2026-08-16T09:23:00+00:00")),
            None,
            canonical_key_for(legacy),
        )
        assert merge is not None

        assert await _apply_merges([merge]) == 0
        assert "matched nothing" in capsys.readouterr().out

    async def test_a_row_that_moved_under_us_does_not_abandon_the_rest(
        self, repository: _FakeRepository
    ) -> None:
        """One row someone else moved between the plan and the write must cost
        only itself. Stopping the loop there would leave every remaining fork in
        place, and the run would still report a clean partial count."""
        repository.renamed = False  # the RENAME below matches nothing
        first = plan_merge(
            _session(LEGACY_KEY, "conv-a", "2026-08-16T09:23:00+00:00"), None, CANONICAL_KEY
        )
        second = plan_merge(
            _session(LEGACY_KEY, "conv-b", "2026-08-16T09:23:00+00:00"),
            _session(CANONICAL_KEY, "conv-c", "2026-08-16T18:00:00+00:00"),
            CANONICAL_KEY,
        )
        assert first is not None and second is not None

        assert await _apply_merges([first, second]) == 1
        assert any(call[0] == "delete_by_session_key" for call in repository.calls)

    async def test_a_delete_that_matched_nothing_is_not_counted_as_applied(
        self, repository: _FakeRepository
    ) -> None:
        repository.deleted = 0
        merge = plan_merge(
            _session(LEGACY_KEY, "conv-legacy", "2026-08-16T09:23:00+00:00"),
            _session(CANONICAL_KEY, "conv-canonical", "2026-08-16T18:00:00+00:00"),
            CANONICAL_KEY,
        )
        assert merge is not None

        assert await _apply_merges([merge]) == 0

    async def test_every_action_leaves_no_legacy_key_behind(
        self, repository: _FakeRepository
    ) -> None:
        """What makes the migration idempotent: a second run finds nothing."""
        merges = [
            plan_merge(
                _session(LEGACY_KEY, "conv-a", "2026-08-16T09:23:00+00:00"), None, CANONICAL_KEY
            ),
            plan_merge(
                _session(LEGACY_KEY, "conv-b", "2026-08-17T10:00:00+00:00"),
                _session(CANONICAL_KEY, "conv-c", "2026-08-16T09:23:00+00:00"),
                CANONICAL_KEY,
            ),
            plan_merge(
                _session(LEGACY_KEY, "conv-d", "2026-08-16T09:23:00+00:00"),
                _session(CANONICAL_KEY, "conv-e", "2026-08-18T00:00:00+00:00"),
                CANONICAL_KEY,
            ),
        ]
        assert all(m is not None for m in merges)

        assert await _apply_merges([m for m in merges if m is not None]) == 3

        retired = [
            c for c in repository.calls if c[0] in ("rename_session_key", "delete_by_session_key")
        ]
        assert len(retired) == 3
