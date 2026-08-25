"""Unit tests for the memory-store repair script.

Two halves. The selection logic (which rows the script proposes to retire, and
why) is pure and tested directly. The driver is tested against a mocked store:
what it PRINTS is the whole product of a dry run — an operator reads that plan
and decides whether to re-run with ``--apply`` — so the printed plan and the
retire reasons it writes are asserted verbatim.
"""

import argparse
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from app.constants.memory import (
    STATE_FACT_TTL_DAYS,
    MemoryDocType,
    MemoryKind,
    MemoryShelfLife,
    MemorySourceType,
)
from app.models.memory_db_models import MemoryRecord
from app.scripts import repair_memory_store
from app.scripts.repair_memory_store import (
    _repair_user,
    _run,
    covers,
    extends_parents_to_retire,
    looks_like_state,
    main,
    state_rows_to_forget,
)

NOW = datetime(2026, 8, 24, tzinfo=UTC)


def make_row(
    *,
    content: str = "sam works at acme",
    row_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
    relation_type: str | None = None,
    shelf_life: MemoryShelfLife = MemoryShelfLife.DURABLE,
    age_days: int = 0,
) -> MemoryRecord:
    row = MemoryRecord(
        user_id="u1",
        kind=MemoryKind.FACT.value,
        shelf_life=shelf_life.value,
        content=content,
        category_path="work",
        source_type=MemorySourceType.CONVERSATION.value,
        importance=0.5,
    )
    row.id = row_id or uuid.uuid4()
    row.parent_id = parent_id
    row.relation_type = relation_type
    row.created_at = NOW - timedelta(days=age_days)
    return row


@pytest.mark.unit
class TestExtendsParentsToRetire:
    def test_a_live_parent_of_a_live_extends_child_is_retired(self) -> None:
        parent = make_row(content="sam works at acme")
        child = make_row(
            content="sam works at acme as a staff engineer",
            parent_id=parent.id,
            relation_type="extends",
        )

        assert extends_parents_to_retire([parent, child]) == [(parent, child)]

    def test_a_parent_that_is_no_longer_live_is_left_alone(self) -> None:
        child = make_row(parent_id=uuid.uuid4(), relation_type="extends")

        assert extends_parents_to_retire([child]) == []

    def test_an_updates_child_is_not_touched(self) -> None:
        # UPDATES already superseded its parent; only the EXTENDS pairs that
        # were written to coexist need repairing.
        parent = make_row()
        child = make_row(parent_id=parent.id, relation_type="updates")

        assert extends_parents_to_retire([parent, child]) == []

    def test_a_parent_with_several_extends_children_is_retired_once(self) -> None:
        parent = make_row()
        first = make_row(parent_id=parent.id, relation_type="extends", age_days=2)
        second = make_row(parent_id=parent.id, relation_type="extends", age_days=1)

        retired = extends_parents_to_retire([parent, first, second])

        assert [pair[0] for pair in retired] == [parent]
        # The newest child is the one that survives, so it is the one cited.
        assert retired[0][1] is second

    def test_the_newest_child_wins_even_when_it_is_scanned_first(self) -> None:
        # Row order is the DB's, not the caller's: whichever child is scanned
        # first, the one cited must be the newest.
        parent = make_row()
        newest = make_row(parent_id=parent.id, relation_type="extends", age_days=1)
        older = make_row(parent_id=parent.id, relation_type="extends", age_days=5)

        retired = extends_parents_to_retire([parent, newest, older])

        assert retired[0][1] is newest

    def test_children_sharing_a_timestamp_keep_the_first_one_scanned(self) -> None:
        parent = make_row()
        first = make_row(parent_id=parent.id, relation_type="extends", age_days=3)
        tied = make_row(parent_id=parent.id, relation_type="extends", age_days=3)

        retired = extends_parents_to_retire([parent, first, tied])

        assert retired[0][1] is first

    def test_an_orphan_child_does_not_stop_the_scan(self) -> None:
        # A child whose parent is already retired sits in the same result set
        # as the pairs that still need repairing; skipping it must not abandon
        # the rows after it.
        orphan = make_row(parent_id=uuid.uuid4(), relation_type="extends")
        parent = make_row()
        child = make_row(parent_id=parent.id, relation_type="extends")

        assert extends_parents_to_retire([orphan, parent, child]) == [(parent, child)]

    def test_a_child_without_a_parent_id_does_not_stop_the_scan(self) -> None:
        rootless = make_row(relation_type="extends")
        parent = make_row()
        child = make_row(parent_id=parent.id, relation_type="extends")

        assert extends_parents_to_retire([rootless, parent, child]) == [(parent, child)]


@pytest.mark.unit
class TestLooksLikeState:
    @pytest.mark.parametrize(
        "content",
        [
            "As of August 2026 Sam has 18 active workflows",
            "Sam currently has Gmail disconnected",
            "The billing migration is failing in production",
            "Sam's Slack integration is disconnected",
            "Sam's Pro upgrade is pending",
        ],
    )
    def test_a_snapshot_phrase_is_state(self, content: str) -> None:
        assert looks_like_state(content) is True

    @pytest.mark.parametrize(
        "content",
        [
            "Sam's anniversary is October 19",
            "Sam is vegetarian",
            "Sam's partner is Khyati Sheth",
            "Sam prefers concise replies with no em dashes",
        ],
    )
    def test_a_durable_fact_is_not_state(self, content: str) -> None:
        assert looks_like_state(content) is False

    def test_the_match_is_not_fooled_by_a_word_that_merely_contains_a_keyword(self) -> None:
        assert looks_like_state("Sam works on concurrency at Acme") is False


@pytest.mark.unit
class TestStateRowsToForget:
    def test_a_backfilled_state_row_past_the_window_is_forgotten(self) -> None:
        row = make_row(shelf_life=MemoryShelfLife.STATE, age_days=90)

        assert state_rows_to_forget([row], now=NOW) == [row]

    def test_a_backfilled_state_row_inside_the_window_is_kept(self) -> None:
        row = make_row(shelf_life=MemoryShelfLife.STATE, age_days=10)

        assert state_rows_to_forget([row], now=NOW) == []

    def test_a_legacy_durable_row_falls_back_to_the_phrase_heuristic(self) -> None:
        # Rows written before shelf_life existed all read as 'durable'.
        stale = make_row(content="Gmail is currently disconnected", age_days=120)
        real = make_row(content="Sam's anniversary is October 19", age_days=120)

        assert state_rows_to_forget([stale, real], now=NOW) == [stale]

    def test_the_heuristic_never_reaches_a_recent_row(self) -> None:
        row = make_row(content="Gmail is currently disconnected", age_days=3)

        assert state_rows_to_forget([row], now=NOW) == []

    def test_a_row_created_exactly_on_the_cutoff_is_already_stale(self) -> None:
        # The window is "older than N days"; a row sitting exactly on the
        # boundary has served its full life and goes.
        row = make_row(shelf_life=MemoryShelfLife.STATE, age_days=STATE_FACT_TTL_DAYS)

        assert state_rows_to_forget([row], now=NOW) == [row]

    def test_a_row_one_day_inside_the_cutoff_is_kept(self) -> None:
        row = make_row(shelf_life=MemoryShelfLife.STATE, age_days=STATE_FACT_TTL_DAYS - 1)

        assert state_rows_to_forget([row], now=NOW) == []

    def test_a_recent_row_does_not_stop_the_scan(self) -> None:
        recent = make_row(shelf_life=MemoryShelfLife.STATE, age_days=1)
        stale = make_row(shelf_life=MemoryShelfLife.STATE, age_days=90)

        assert state_rows_to_forget([recent, stale], now=NOW) == [stale]

    def test_the_window_is_caller_overridable(self) -> None:
        row = make_row(shelf_life=MemoryShelfLife.STATE, age_days=20)

        assert state_rows_to_forget([row], now=NOW, age_days=10) == [row]
        assert state_rows_to_forget([row], now=NOW, age_days=30) == []


RULE = "=" * 78
EXTENDS_REASON = "superseded by its EXTENDS child (memory-store repair)"
STATE_REASON = "stale state snapshot (memory-store repair)"
MANUAL_REASON = "retired by hand (memory-store repair)"


def make_args(
    *,
    apply: bool = False,
    retire_ids: list[str] | None = None,
    state_age_days: int | None = None,
    extends_containment: float = 0.8,
) -> argparse.Namespace:
    return argparse.Namespace(
        apply=apply,
        retire_ids=retire_ids,
        state_age_days=STATE_FACT_TTL_DAYS if state_age_days is None else state_age_days,
        extends_containment=extends_containment,
    )


@pytest.fixture
def store() -> Iterator[SimpleNamespace]:
    """Every edge the driver touches, so only its own plan and order are real."""
    mocks = SimpleNamespace(
        get_all_live_memories=AsyncMock(return_value=[]),
        forget_memory=AsyncMock(return_value=True),
        render_agenda_document=AsyncMock(return_value=None),
        consolidate=AsyncMock(return_value=[]),
    )
    with (
        patch.object(
            repair_memory_store.pg_store, "get_all_live_memories", mocks.get_all_live_memories
        ),
        patch.object(repair_memory_store, "forget_memory", mocks.forget_memory),
        patch.object(repair_memory_store, "render_agenda_document", mocks.render_agenda_document),
        patch.object(repair_memory_store, "consolidate", mocks.consolidate),
    ):
        yield mocks


@pytest.mark.unit
class TestRepairUserPlan:
    async def test_the_containment_flag_is_what_decides_the_extends_plan(
        self, store: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parent = make_row(content="avoid corporate jargon and em dashes")
        child = make_row(
            content="avoid fluff in marketing copy",
            parent_id=parent.id,
            relation_type="extends",
        )
        store.get_all_live_memories.return_value = [parent, child]

        await _repair_user("u1", make_args(extends_containment=1.0))
        strict = capsys.readouterr().out
        await _repair_user("u1", make_args(extends_containment=0.0))
        lax = capsys.readouterr().out

        assert "EXTENDS parents still live alongside their child: 0" in strict
        assert "EXTENDS parents still live alongside their child: 1" in lax

    async def test_the_dry_run_prints_the_whole_plan_and_writes_nothing(
        self, store: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parent = make_row(content="sam works at acme")
        child = make_row(
            content="sam works at acme as a staff engineer",
            parent_id=parent.id,
            relation_type="extends",
        )
        stale = make_row(
            content="Gmail is currently disconnected",
            shelf_life=MemoryShelfLife.STATE,
            age_days=90,
        )
        store.get_all_live_memories.return_value = [parent, child, stale]

        assert await _repair_user("u1", make_args()) == 0

        assert capsys.readouterr().out == (
            f"\n{RULE}\nUser u1: 3 live memories\n{RULE}\n"
            "\nEXTENDS parents still live alongside their child: 1\n"
            f"  - retire {parent.id}: 'sam works at acme'\n"
            f"      kept  {child.id}: 'sam works at acme as a staff engineer'\n"
            f"\nStale state snapshots older than {STATE_FACT_TTL_DAYS}d: 1\n"
            f"  - forget {stale.id} ({stale.created_at:%Y-%m-%d}): "
            "'Gmail is currently disconnected'\n"
            "\nSummary: 1 EXTENDS parent(s), 1 stale snapshot(s), 0 explicit — then "
            "user.md/people.md rebuilt and agenda.md re-rendered.\n"
            "\nDry run only. Re-run with --apply to commit.\n"
        )
        store.forget_memory.assert_not_awaited()
        store.render_agenda_document.assert_not_awaited()
        store.consolidate.assert_not_awaited()

    async def test_the_plan_is_read_from_the_named_user_at_the_configured_window(
        self, store: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store.get_all_live_memories.return_value = [
            make_row(content="Gmail is currently disconnected", age_days=15)
        ]

        await _repair_user("u7", make_args(state_age_days=10))

        assert store.get_all_live_memories.await_args.args == ("u7",)
        assert "\nStale state snapshots older than 10d: 1\n" in capsys.readouterr().out

    async def test_ids_named_by_hand_are_listed_separately(
        self, store: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        wanted = make_row(content="a fact a human judged wrong")
        other = make_row(content="a fact nobody complained about")
        store.get_all_live_memories.return_value = [wanted, other]

        await _repair_user("u1", make_args(retire_ids=[str(wanted.id)]))

        out = capsys.readouterr().out
        assert "\nExplicitly retired by --retire-ids: 1\n" in out
        assert f"  - forget {wanted.id}: 'a fact a human judged wrong'\n" in out
        assert str(other.id) not in out
        assert "1 explicit" in out

    async def test_nothing_named_by_hand_prints_no_section(
        self, store: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store.get_all_live_memories.return_value = [make_row()]

        await _repair_user("u1", make_args())

        assert "--retire-ids" not in capsys.readouterr().out


@pytest.mark.unit
class TestRepairUserApply:
    async def test_each_retirement_carries_the_reason_it_was_retired(
        self, store: SimpleNamespace
    ) -> None:
        # The reason is the audit trail on the row: months later it is the only
        # record of why a fact left the live set.
        parent = make_row()
        child = make_row(parent_id=parent.id, relation_type="extends")
        stale = make_row(shelf_life=MemoryShelfLife.STATE, age_days=90)
        manual = make_row(content="a fact a human judged wrong")
        store.get_all_live_memories.return_value = [parent, child, stale, manual]

        assert await _repair_user("u1", make_args(apply=True, retire_ids=[str(manual.id)])) == 0

        assert [call.args for call in store.forget_memory.await_args_list] == [
            ("u1", str(parent.id), EXTENDS_REASON),
            ("u1", str(stale.id), STATE_REASON),
            ("u1", str(manual.id), MANUAL_REASON),
        ]

    async def test_the_documents_are_rebuilt_after_the_retirements(
        self, store: SimpleNamespace
    ) -> None:
        # Rebuilding first would derive the documents from the corpus that
        # corrupted them.
        order: list[str] = []

        def record(step: str, result: object) -> Callable[..., object]:
            def note(*_args: object) -> object:
                order.append(step)
                return result

            return note

        store.forget_memory.side_effect = record("forget", True)
        store.render_agenda_document.side_effect = record("agenda", None)
        store.consolidate.side_effect = record("consolidate", [])
        stale = make_row(shelf_life=MemoryShelfLife.STATE, age_days=90)
        store.get_all_live_memories.return_value = [stale]

        await _repair_user("u1", make_args(apply=True))

        assert order == ["forget", "agenda", "consolidate"]
        assert store.render_agenda_document.await_args.args == ("u1",)
        assert store.consolidate.await_args.args == ("u1",)

    async def test_the_rebuilt_documents_are_named_in_the_closing_line(
        self, store: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store.consolidate.return_value = [MemoryDocType.USER_MD, MemoryDocType.PEOPLE_MD]

        await _repair_user("u1", make_args(apply=True))

        assert capsys.readouterr().out.endswith("\nApplied. Rewrote: user_md, people_md\n")

    async def test_a_run_that_rewrote_nothing_says_so(
        self, store: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store.consolidate.return_value = []

        await _repair_user("u1", make_args(apply=True))

        assert capsys.readouterr().out.endswith("\nApplied. Rewrote: (nothing)\n")


@pytest.mark.unit
class TestRunAllUsers:
    async def test_every_named_user_is_repaired_in_order(self) -> None:
        args = make_args()
        args.user = ["u1", "u2"]

        with patch.object(repair_memory_store, "_repair_user", AsyncMock(return_value=0)) as repair:
            assert await _run(args) == 0

        assert [call.args for call in repair.await_args_list] == [("u1", args), ("u2", args)]


@pytest.mark.unit
class TestOnlyARestatementRetiresItsParent:
    """The links being read here were written by the OLD reconciler, whose rule
    was "more detail about a related claim". So an EXTENDS link means the two
    rows are topically adjacent, not that the child replaces the parent. On the
    production store, retiring every linked parent would have deleted "avoid em
    dashes" in favour of "fluff-free marketing copy"."""

    @staticmethod
    def _pair(parent_content: str, child_content: str) -> list[MemoryRecord]:
        parent = make_row(content=parent_content)
        child = make_row(
            content=child_content,
            relation_type="extends",
            parent_id=parent.id,
        )
        return [parent, child]

    def test_a_child_that_restates_the_parent_retires_it(self) -> None:
        rows = self._pair(
            "Aryan's startup is not venture-backed.",
            "Aryan's startup is bootstrapped and not venture-backed.",
        )

        assert [parent.id for parent, _ in extends_parents_to_retire(rows)] == [rows[0].id]

    def test_a_child_that_only_shares_a_topic_leaves_the_parent_alone(self) -> None:
        rows = self._pair(
            "Aryan prefers direct, human-sounding communication, avoiding corporate jargon "
            "and em dashes.",
            "Aryan prefers direct, concise, fluff-free communication for marketing copy.",
        )

        assert extends_parents_to_retire(rows) == []

    def test_the_bar_is_the_callers_containment(self) -> None:
        rows = self._pair(
            "Aryan uses PostHog for analytics.",
            "Aryan uses PostHog for tracking user acquisition and metrics.",
        )

        assert extends_parents_to_retire(rows, containment=0.9) == []
        assert len(extends_parents_to_retire(rows, containment=0.5)) == 1


@pytest.mark.unit
class TestALongProfileIsNotASnapshot:
    """The phrase heuristic reads a snapshot's SHAPE: short, one clock-bound
    claim. user.md is rebuilt from live rows, so retiring a 600-character
    biography because it says "currently pursuing" would impoverish the rebuild
    it is meant to repair."""

    def test_a_short_snapshot_is_still_retired(self) -> None:
        row = make_row(content="Aryan is currently unable to take screenshots.", age_days=90)

        assert state_rows_to_forget([row], now=NOW) == [row]

    def test_a_long_biography_carrying_the_word_is_kept(self) -> None:
        biography = (
            "Aryan Randeriya is a software developer, designer and entrepreneur based in "
            "India, the founder of The Experience Company, and is currently pursuing a "
            "B.Tech in Computer Science. " + "He has shipped several products. " * 8
        )
        assert len(biography) > 300
        row = make_row(content=biography, age_days=90)

        assert state_rows_to_forget([row], now=NOW) == []

    def test_a_row_the_extractor_itself_called_state_is_retired_at_any_length(self) -> None:
        row = make_row(
            content="Aryan's signup count stands at 2,000. " * 12,
            age_days=90,
            shelf_life=MemoryShelfLife.STATE,
        )
        assert len(row.content) > 300

        assert state_rows_to_forget([row], now=NOW) == [row]


@pytest.mark.unit
class TestRunBootstrapsWhatAScriptHasNoLifespanFor:
    """Outside the API process nobody has registered the lazy providers, so the
    memory store's Postgres engine has nobody to build it and every query raises
    ``Provider 'postgresql_engine' not found in registry``. That is exactly how
    the first production dry run of this script failed."""

    async def test_providers_are_registered_before_the_first_repair(self) -> None:
        args = make_args()
        args.user = ["u1"]
        order: list[str] = []

        async def repair(user_id: str, _args: argparse.Namespace) -> None:
            order.append(f"repair:{user_id}")

        async def close() -> None:
            order.append("close")

        with (
            patch.object(
                repair_memory_store,
                "register_lazy_providers",
                lambda context: order.append(f"register:{context}"),
            ),
            patch.object(repair_memory_store, "_repair_user", repair),
            patch.object(repair_memory_store, "close_postgresql_db", close),
        ):
            assert await _run(args) == 0

        assert order == ["register:main_app", "repair:u1", "close"]

    async def test_the_engine_is_disposed_even_when_a_repair_fails(self) -> None:
        args = make_args()
        args.user = ["u1"]
        closed = AsyncMock(return_value=None)

        with (
            patch.object(repair_memory_store, "register_lazy_providers", lambda context: None),
            patch.object(
                repair_memory_store, "_repair_user", AsyncMock(side_effect=RuntimeError("pg down"))
            ),
            patch.object(repair_memory_store, "close_postgresql_db", closed),
        ):
            with pytest.raises(RuntimeError, match="pg down"):
                await _run(args)

        closed.assert_awaited_once()


@pytest.mark.unit
class TestWhatCountsAsCoverage:
    def test_the_share_is_measured_against_the_parents_words_only(self) -> None:
        # parent: startup, bootstrapped, venture, backed, india (5); child repeats 4.
        parent = "startup bootstrapped venture backed india"
        child = "startup bootstrapped venture backed berlin and a great deal more"

        assert covers(parent, child, 0.8) is True
        assert covers(parent, child, 0.81) is False

    def test_a_parent_made_only_of_filler_is_never_covered(self) -> None:
        assert covers("it is as it was", "it is as it was", 0.0) is False

    def test_case_and_filler_do_not_count_toward_coverage(self) -> None:
        assert covers("PostHog Analytics", "posthog analytics", 1.0) is True
        assert covers("the a an of to", "the a an of to", 0.0) is False
        assert covers("AI is useful", "useful", 1.0) is True

    def test_two_letter_words_are_filler_and_three_letter_words_are_subject(self) -> None:
        assert covers("uses AI", "uses", 1.0) is True
        assert covers("uses zsh", "uses", 1.0) is False

    def test_a_child_that_flips_the_parents_meaning_does_not_cover_it(self) -> None:
        # "not" is the whole difference between these two claims.
        assert covers("startup is not venture-backed", "startup is venture-backed", 0.8) is False
        assert covers("startup is not venture-backed", "startup is not venture-backed", 1.0) is True

    def test_an_apostrophe_keeps_a_contraction_as_one_word(self) -> None:
        assert covers("doesn't drink", "does not drink", 1.0) is False
        assert covers("doesn't drink", "doesn't drink", 1.0) is True


@pytest.mark.unit
class TestTheSnapshotLengthBound:
    def test_the_bound_is_inclusive(self) -> None:
        exactly = "currently " + "x" * 290
        assert len(exactly) == 300
        assert looks_like_state(exactly) is True
        assert looks_like_state(exactly + "x") is False


@pytest.mark.unit
class TestCommandLine:
    @staticmethod
    def _run_main(argv: list[str]) -> tuple[list[argparse.Namespace], int | str | None]:
        captured: list[argparse.Namespace] = []

        async def fake_run(args: argparse.Namespace) -> int:
            captured.append(args)
            return 0

        with (
            patch("sys.argv", ["repair_memory_store", *argv]),
            patch.object(repair_memory_store, "_run", fake_run),
            pytest.raises(SystemExit) as raised,
        ):
            main()
        return captured, raised.value.code

    def test_the_flags_parse_into_the_repair_arguments(self) -> None:
        captured, code = self._run_main(
            [
                "--user",
                "u1",
                "--user",
                "u2",
                "--apply",
                "--retire-ids",
                "mem-1",
                "--retire-ids",
                "mem-2",
                "--state-age-days",
                "30",
                "--extends-containment",
                "0.5",
            ]
        )

        assert code == 0
        (args,) = captured
        assert args.user == ["u1", "u2"]
        assert args.apply is True
        assert args.retire_ids == ["mem-1", "mem-2"]
        assert args.state_age_days == 30
        assert args.extends_containment == 0.5

    def test_a_run_without_flags_is_a_dry_run_at_the_default_window(self) -> None:
        captured, _code = self._run_main(["--user", "u1"])

        (args,) = captured
        assert args.apply is False
        assert args.retire_ids is None
        assert args.state_age_days == STATE_FACT_TTL_DAYS
        assert args.extends_containment == 0.8

    @pytest.mark.parametrize("bad", ["-1", "1.5", "nan"])
    def test_a_containment_outside_zero_to_one_refuses_to_start(
        self, bad: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch(
                "sys.argv", ["repair_memory_store", "--user", "u1", "--extends-containment", bad]
            ),
            pytest.raises(SystemExit) as raised,
        ):
            main()

        assert raised.value.code == 2
        assert f"'{bad}' is not a share between 0.0 and 1.0" in capsys.readouterr().err

    def test_a_containment_that_is_not_a_number_refuses_to_start(self) -> None:
        with (
            patch(
                "sys.argv", ["repair_memory_store", "--user", "u1", "--extends-containment", "half"]
            ),
            pytest.raises(SystemExit) as raised,
        ):
            main()

        assert raised.value.code == 2

    @pytest.mark.parametrize("edge", ["0", "1"])
    def test_the_ends_of_the_share_are_allowed(self, edge: str) -> None:
        captured, code = self._run_main(["--user", "u1", "--extends-containment", edge])

        assert code == 0
        assert captured[0].extends_containment == float(edge)

    def test_a_run_with_no_user_refuses_to_start(self) -> None:
        with patch("sys.argv", ["repair_memory_store"]), pytest.raises(SystemExit) as raised:
            main()

        assert raised.value.code == 2

    def test_the_exit_code_is_the_repair_result(self) -> None:
        async def fake_run(_args: argparse.Namespace) -> int:
            return 3

        with (
            patch("sys.argv", ["repair_memory_store", "--user", "u1"]),
            patch.object(repair_memory_store, "_run", fake_run),
            pytest.raises(SystemExit) as raised,
        ):
            main()

        assert raised.value.code == 3

    def test_help_explains_every_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("sys.argv", ["repair_memory_store", "--help"]), pytest.raises(SystemExit):
            main()

        raw = capsys.readouterr().out
        help_text = " ".join(raw.split())
        assert (
            "Repair a user's memory store after the extraction/reconciliation fixes." in help_text
        )
        # Scoped to the block argparse RENDERS from add_argument, not the whole
        # page: the description above it is this module's docstring, and while
        # that docstring also listed the flags every assertion below passed
        # against the prose copy — the real help strings were unchecked, and a
        # mutation run walked straight through all five of them.
        assert "options:" in raw, raw
        options = " ".join(raw.split("options:", 1)[1].split())
        assert "--user USER User id to repair (repeatable)." in options
        assert "--apply Persist changes (otherwise dry run only)." in options
        assert "--retire-ids RETIRE_IDS Forget this memory id outright (repeatable)." in options
        assert (
            "--state-age-days STATE_AGE_DAYS Age past which a state-like row is retired." in options
        )
        assert (
            "--extends-containment EXTENDS_CONTAINMENT Share of a parent's words its child must "
            "repeat before the parent is retired." in options
        )
