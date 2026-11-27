"""Gathering every producer into one pool: one item per outside thing, whichever sources found it.

Faked seams: the repository reads the reading producers make.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from tests.factories import make_user_id
from tests.helpers import captured_wide_event

from app.constants.briefing import BRIEF_POOL_PER_SOURCE, BriefAction, BriefItemSource
from app.constants.todos import GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL, WaitingOn
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.reminders import reminder_repository
from app.db.repositories.signal_memory import signal_memory_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_candidate_models import (
    BriefCandidate,
    CandidateOrigin,
    GaiaRef,
    GaiaRefKind,
    HeldResult,
    OutsideRef,
)
from app.models.brief_item_models import ItemState
from app.models.brief_models import PendingBriefItemDocument
from app.models.brief_payload_models import BriefingEvent, UnreadSource
from app.models.hil_models import ApprovalLedgerDocument
from app.models.scout_models import (
    RememberedSignal,
    ScoutOutcome,
    ScoutResult,
    ScoutSkipReason,
    Sighting,
    Signal,
    SignalImportance,
    SignalMemoryDocument,
)
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.services.briefing.candidates import pool as candidates_pool
from app.services.briefing.candidates.memory import sighting
from app.services.briefing.candidates.pool import (
    CandidateSources,
    GatheredCandidates,
    _one_per_thing,
    gather_candidates,
)
from app.services.briefing.clock import UserClock
from app.services.briefing.fact_pool.render import stands_part
from app.services.briefing.scouts.service import ScoutSignals
from app.services.briefing.work import TrackedWork
from app.services.todos.inbox_desk import INBOX_DESK_REF

USER_ID = make_user_id()
NOW = datetime(2026, 11, 11, 2, 30, tzinfo=UTC)
#: When the last stored brief was made, before which the passed-over rows were first read.
LAST_BRIEF = NOW - timedelta(hours=20)
TZ = ZoneInfo("Asia/Kolkata")
CLOCK = UserClock(tz=TZ, now_local=NOW.astimezone(TZ), date_str="2026-11-11", day_of_year=315)


@pytest.fixture(autouse=True)
def memory(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    """Signal memory as Mongo holds it: nothing seen before unless a test says so."""
    seams = {"find_for": AsyncMock(return_value=[]), "record_seen": AsyncMock()}
    for name, mock in seams.items():
        monkeypatch.setattr(signal_memory_repository, name, mock)
    return seams


@pytest.fixture(autouse=True)
def quiet_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    for owner, name in (
        (approval_ledger_repository, "list_pending_for_user"),
        (reminder_repository, "find_scheduled_between"),
        (workflow_executions_repository, "list_since"),
        (workflow_repository, "find_system_workflows"),
    ):
        monkeypatch.setattr(owner, name, AsyncMock(return_value=[]))
    monkeypatch.setattr(
        todo_repository, "find_latest_by_external_ref", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        candidates_pool, "get_connected_integration_ids", AsyncMock(return_value=[])
    )


def _thread_todo(thread_id: str, title: str) -> TodoDocument:
    return TodoDocument(
        id=f"todo-{thread_id}",
        user_id=USER_ID,
        title=title,
        description="Maya asked for sign-off on the revised preference",
        labels=[GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL],
        external_ref=ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id=thread_id),
    )


def _gmail_signal(external_id: str, title: str) -> RememberedSignal:
    return RememberedSignal(
        signal=Signal(
            integration_id="gmail",
            app="Gmail",
            external_id=external_id,
            kind="email waiting on your reply",
            title=title,
            people=["Maya Chen"],
            importance=SignalImportance.HIGH,
            url="https://mail.google.com/mail/u/0/#inbox/t-maya",
            text="Can you confirm the preference by Friday? Our partners meet Monday.",
        )
    )


def _scouts(*remembered: RememberedSignal) -> ScoutSignals:
    return ScoutSignals(
        results=[ScoutResult(integration_id="gmail", app="Gmail", outcome=ScoutOutcome.REPLAYED)],
        remembered=list(remembered),
        criteria={},
    )


async def _gathered(
    work: TrackedWork, scouts: ScoutSignals, open_own: list[TodoDocument] | None = None
) -> GatheredCandidates:
    sources = CandidateSources(
        work, scouts, [], CLOCK.day_start(days_ago=-1), open_own or [], last_brief_at=LAST_BRIEF
    )
    return await gather_candidates(USER_ID, CLOCK, NOW, NOW, sources)


def _found(
    title: str,
    *,
    detail: str | None = None,
    due_at: datetime | None = None,
    todo_id: str | None = None,
) -> BriefCandidate:
    return BriefCandidate(
        origin=CandidateOrigin.APP_SIGNAL,
        source="gmail",
        app="Gmail",
        state=ItemState.YOU,
        title=title,
        ref=OutsideRef(integration_id="gmail", external_id="t1"),
        detail=detail,
        due_at=due_at,
        todo_id=todo_id,
    )


class TestFoldingTwoFindsOfOneThing:
    def test_what_only_the_second_find_knew_is_kept(self) -> None:
        first = _found("Reply to Maya")
        again = _found(
            "Re: term sheet",
            detail="needs sign-off",
            due_at=NOW,
            todo_id="todo-1",
        )

        [merged] = _one_per_thing([first, again])

        assert (merged.title, merged.detail, merged.due_at, merged.todo_id) == (
            "Reply to Maya",
            "needs sign-off",
            NOW,
            "todo-1",
        )

    def test_what_the_first_find_knew_wins_over_the_second(self) -> None:
        first = _found("Reply to Maya", detail="first", due_at=NOW, todo_id="todo-1")
        again = _found(
            "Re: term sheet",
            detail="second",
            due_at=datetime(2026, 11, 20, tzinfo=UTC),
            todo_id="todo-2",
        )

        [merged] = _one_per_thing([first, again])

        assert (merged.detail, merged.due_at, merged.todo_id) == ("first", NOW, "todo-1")

    def test_a_repeat_does_not_end_the_folding_of_what_follows(self) -> None:
        other = BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gmail",
            app="Gmail",
            state=ItemState.YOU,
            title="Offsite",
        )

        kept = _one_per_thing([_found("a"), _found("b"), other])

        assert [c.title for c in kept] == ["a", "Offsite"]


class TestTheCalendarJoinsThePool:
    async def test_todays_events_are_timed_in_the_users_own_clock(self) -> None:
        events = [BriefingEvent(date="2026-11-11", start="15:00", title="Board call")]
        sources = CandidateSources(
            TrackedWork(),
            _scouts(),
            events,
            CLOCK.day_start(days_ago=-1),
            [],
            last_brief_at=LAST_BRIEF,
        )

        gathered = await gather_candidates(USER_ID, CLOCK, NOW, NOW, sources)

        [event] = gathered.pool.values()
        assert (event.title, event.is_event, event.time) == ("Board call", True, "3:00 PM")


class TestOwnTodosJoinThePool:
    async def test_the_users_own_todos_due_by_their_next_local_midnight_wait_on_them(
        self,
    ) -> None:
        midnight = datetime(2026, 11, 11, 18, 30, tzinfo=UTC)
        own = TodoDocument(id="own-1", user_id=USER_ID, title="File the VAT return", due_date=NOW)
        tomorrow = TodoDocument(id="own-3", user_id=USER_ID, title="Pay rent", due_date=midnight)

        gathered = await _gathered(TrackedWork(), _scouts(), [own, tomorrow])

        [item] = gathered.pool.values()
        assert (item.title, item.todo_id, item.state, item.action) == (
            "File the VAT return",
            "own-1",
            "you",
            BriefAction.ATTEND,
        )

    async def test_an_undated_own_todo_is_offered_with_no_due_date(self) -> None:
        undated = TodoDocument(id="own-2", user_id=USER_ID, title="Sort the garage")

        gathered = await _gathered(TrackedWork(), _scouts(), [undated])

        [item] = gathered.pool.values()
        assert (item.todo_id, item.due_at, item.state, item.action) == (
            "own-2",
            None,
            "you",
            BriefAction.ATTEND,
        )


def _tracked(todo_id: str, title: str, label: str) -> TodoDocument:
    return TodoDocument(
        id=todo_id, user_id=USER_ID, title=title, labels=[GAIA_TRACKED_LABEL, label]
    )


def _shown(external_id: str, state: str, times: int) -> SignalMemoryDocument:
    return SignalMemoryDocument(
        user_id=USER_ID,
        integration_id="gaia",
        external_id=external_id,
        first_seen=datetime(2026, 11, 8, 2, 30, tzinfo=UTC),
        times_shown=times,
        last_shown=datetime(2026, 11, 10, 2, 30, tzinfo=UTC),
        last_state=state,
    )


class TestHowMemoryKeysACandidate:
    def test_gaias_own_thing_is_kept_under_its_gaia_ref_and_state(self) -> None:
        approval = BriefCandidate(
            origin=CandidateOrigin.APPROVAL,
            source="gaia",
            app="GAIA",
            state=ItemState.YOU,
            title="Approve the refund",
            seen_as=GaiaRef(kind=GaiaRefKind.APPROVAL, id="ap_1"),
        )

        assert sighting(approval) == Sighting("gaia", "approval:ap_1", "you")

    def test_an_app_signal_is_kept_under_its_apps_own_id_and_state(self) -> None:
        signal = _gmail_signal("t-maya", "Term sheet").signal.model_copy(
            update={"state": "awaiting reply"}
        )
        candidate = BriefCandidate(
            origin=CandidateOrigin.APP_SIGNAL,
            source="gmail",
            app="Gmail",
            state=ItemState.YOU,
            title="Term sheet",
            signal=signal,
        )

        assert sighting(candidate) == Sighting("gmail", "t-maya", "awaiting reply")

    def test_a_held_result_or_an_event_is_new_each_time(self) -> None:
        held = BriefCandidate(
            origin=HeldResult(id="held-1"),
            source="gaia",
            app="GAIA",
            state=ItemState.NOTE,
            title="Digest",
        )

        assert sighting(held) is None


class TestWhatEarlierBriefsShowedIsNotNews:
    """Regression: the same stale approval and overdue todo came back every day as news."""

    async def test_a_thing_shown_before_as_it_stands_is_a_repeat_and_no_news(
        self, memory: dict[str, AsyncMock]
    ) -> None:
        approve = _tracked("t1", "Approve the MSA", NEEDS_REPLY_LABEL)
        memory["find_for"].return_value = [_shown("todo:t1", "you", times=2)]

        gathered = await _gathered(TrackedWork(blocked=[approve]), _scouts())

        (candidate,) = gathered.pool.values()
        assert candidate.is_repeat
        assert not gathered.has_news
        memory["find_for"].assert_awaited_once_with(USER_ID, [Sighting("gaia", "todo:t1", "you")])
        memory["record_seen"].assert_awaited_once_with(
            USER_ID, [Sighting("gaia", "todo:t1", "you")], NOW
        )

    async def test_a_thing_that_moved_since_is_news_again(
        self, memory: dict[str, AsyncMock]
    ) -> None:
        memory["find_for"].return_value = [_shown("todo:t1", "gaia", times=3)]

        gathered = await _gathered(
            TrackedWork(blocked=[_tracked("t1", "Approve", NEEDS_REPLY_LABEL)]), _scouts()
        )

        (candidate,) = gathered.pool.values()
        assert candidate.moved and not candidate.is_repeat
        assert gathered.has_news

    async def test_a_scout_row_the_last_brief_passed_over_stays_out_of_the_pool(self) -> None:
        """The run's look-back start decides passed over: rows first read before it, left out, drop."""
        memory = SignalMemoryDocument(
            user_id=USER_ID,
            integration_id="gmail",
            external_id="old",
            first_seen=NOW - timedelta(days=2),
            last_seen=NOW - timedelta(days=1),
        )
        passed = _gmail_signal("old", "Old thread").model_copy(update={"memory": memory})
        passed = passed.model_copy(
            update={
                "signal": passed.signal.model_copy(update={"importance": SignalImportance.NORMAL})
            }
        )

        gathered = await _gathered(
            TrackedWork(), _scouts(passed, _gmail_signal("new", "New thread"))
        )

        assert [c.title for c in gathered.pool.values()] == ["New thread"]

    async def test_an_undated_own_todo_alone_is_no_news(self) -> None:
        undated = TodoDocument(id="u1", user_id=USER_ID, title="Plan Q1")

        gathered = await _gathered(TrackedWork(), _scouts(), [undated])

        (candidate,) = gathered.pool.values()
        assert candidate.backlog
        assert not gathered.has_news


class TestWhereGaiaCanAct:
    async def test_gaia_acts_in_its_own_work_its_connected_built_ins_and_apps_it_can_write_to(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connected = AsyncMock(return_value=["gmail", "notion"])
        monkeypatch.setattr(candidates_pool, "get_connected_integration_ids", connected)
        notion = _gmail_signal("n-1", "Roadmap page shared").signal.model_copy(
            update={"integration_id": "notion", "app": "Notion"}
        )
        linear = _gmail_signal("l-1", "Fix the login redirect").signal.model_copy(
            update={"integration_id": "linear", "app": "Linear"}
        )
        scouts = ScoutSignals(
            results=[
                ScoutResult(integration_id="notion", app="Notion", outcome=ScoutOutcome.REPLAYED),
                ScoutResult(
                    integration_id="linear",
                    app="Linear",
                    outcome=ScoutOutcome.REPLAYED,
                    can_write=True,
                ),
            ],
            remembered=[RememberedSignal(signal=notion), RememberedSignal(signal=linear)],
            criteria={},
        )
        work = TrackedWork(
            blocked=[
                _thread_todo("t-maya", "Reply to Maya on the term sheet"),
                _tracked("t1", "Approve the MSA", NEEDS_REPLY_LABEL),
            ]
        )
        events = [BriefingEvent(date="2026-11-11", start="15:00", title="Board call")]

        gathered = await gather_candidates(
            USER_ID,
            CLOCK,
            NOW,
            NOW,
            CandidateSources(
                work, scouts, events, CLOCK.day_start(days_ago=-1), [], last_brief_at=LAST_BRIEF
            ),
        )

        assert [(c.source, c.gaia_acts) for c in gathered.pool.values()] == [
            ("gmail", True),
            ("gaia", True),
            ("notion", False),
            ("linear", True),
            ("googlecalendar", False),
        ]
        connected.assert_awaited_once_with(USER_ID)


class TestGaiasOpenWorkJoinsThePool:
    async def test_when_gaia_looks_again_is_said_on_the_users_own_day(self) -> None:
        later = TodoDocument(
            id="r1",
            user_id=USER_ID,
            title="Chase the venue",
            labels=[GAIA_TRACKED_LABEL],
            waiting_on=WaitingOn.TIME,
            scheduled_at=datetime(2026, 11, 11, 20, 0, tzinfo=UTC),
        )

        gathered = await _gathered(TrackedWork(running=[later]), _scouts())

        [item] = gathered.pool.values()
        assert stands_part(1, item, CLOCK) == "stands: GAIA looks at it again Thu Nov 12"


class TestOneItemPerThing:
    async def test_a_tracked_thread_and_the_scouts_signal_on_it_are_one_item_noting_both(
        self,
    ) -> None:
        """Live brief: Maya's term sheet was placed twice, once from GAIA's tracking, once from Gmail."""
        work = TrackedWork(blocked=[_thread_todo("t-maya", "Reply to Maya on the term sheet")])
        scouts = _scouts(_gmail_signal("t-maya", "Re: Series A term sheet"))

        gathered = await _gathered(work, scouts)

        [item] = gathered.pool.values()
        assert (item.title, item.todo_id, item.action) == (
            "Reply to Maya on the term sheet",
            "todo-t-maya",
            BriefAction.REPLY,
        )
        assert item.signal is not None and item.signal.external_id == "t-maya"
        assert (item.people, item.importance, item.url) == (
            ["Maya Chen"],
            SignalImportance.HIGH,
            "https://mail.google.com/mail/u/0/#inbox/t-maya",
        )
        assert item.also_in == ["the Gmail scout"]

    async def test_things_with_different_ids_stay_apart(self) -> None:
        work = TrackedWork(blocked=[_thread_todo("t-maya", "Reply to Maya on the term sheet")])
        scouts = _scouts(_gmail_signal("t-priya", "Offsite venues"))

        gathered = await _gathered(work, scouts)

        assert [c.title for c in gathered.pool.values()] == [
            "Reply to Maya on the term sheet",
            "Offsite venues",
        ]
        assert all(c.also_in == [] for c in gathered.pool.values())

    async def test_the_same_id_in_another_app_is_another_thing(self) -> None:
        work = TrackedWork(blocked=[_thread_todo("42", "Reply to Maya on the term sheet")])
        slack = _gmail_signal("42", "Standup notes")
        slack.signal = slack.signal.model_copy(update={"integration_id": "slack", "app": "Slack"})

        gathered = await _gathered(work, _scouts(slack))

        assert len(gathered.pool) == 2


def _app_signal(
    n: int,
    importance: SignalImportance = SignalImportance.NORMAL,
    *,
    app: str = "Gmail",
    shown: bool = False,
) -> RememberedSignal:
    found = _gmail_signal(f"t{n}", f"{app} {n}")
    signal = found.signal.model_copy(
        update={"importance": importance, "integration_id": app.lower(), "app": app}
    )
    memory = _shown(f"t{n}", signal.state or "", 1) if shown else None
    return RememberedSignal(signal=signal, memory=memory)


async def _gathered_signals(*remembered: RememberedSignal) -> GatheredCandidates:
    events = [BriefingEvent(date="2026-11-11", start="15:00", title="Board call")]
    sources = CandidateSources(
        TrackedWork(),
        _scouts(*remembered),
        events,
        CLOCK.day_start(days_ago=-1),
        [],
        last_brief_at=LAST_BRIEF,
    )
    return await gather_candidates(USER_ID, CLOCK, NOW, NOW, sources)


def _titles(gathered: GatheredCandidates, source: str) -> list[str]:
    return [c.title for c in gathered.pool.values() if c.source == source]


class TestEachSourceIsCappedByRank:
    async def test_a_flooded_source_keeps_its_most_important_finds_and_others_keep_theirs(
        self,
    ) -> None:
        normal = [_app_signal(n) for n in range(BRIEF_POOL_PER_SOURCE)]
        high = [_app_signal(n, SignalImportance.HIGH) for n in range(100, 102)]
        linear = [_app_signal(n, app="Linear") for n in range(200, 202)]

        async with captured_wide_event() as event:
            gathered = await _gathered_signals(*normal, *high, *linear)

        assert list(gathered.pool) == list(range(1, BRIEF_POOL_PER_SOURCE + 4))
        assert _titles(gathered, "gmail") == [
            "Gmail 100",
            "Gmail 101",
            *(f"Gmail {n}" for n in range(BRIEF_POOL_PER_SOURCE - 2)),
        ]
        assert _titles(gathered, "linear") == ["Linear 200", "Linear 201"]
        assert [c.title for c in gathered.pool.values() if c.is_event] == ["Board call"]
        assert event["briefing"]["pool_capped"] == 2

    async def test_what_waits_on_the_user_outranks_what_gaia_finished(self) -> None:
        done = [
            _tracked(f"d{n}", f"Done {n}", NEEDS_REPLY_LABEL) for n in range(BRIEF_POOL_PER_SOURCE)
        ]
        work = TrackedWork(
            blocked=[_tracked("w1", "Approve the MSA", NEEDS_REPLY_LABEL)], completed=done
        )

        gathered = await _gathered(work, _scouts())

        titles = _titles(gathered, "gaia")
        assert (len(titles), titles[0], titles[-1]) == (
            BRIEF_POOL_PER_SOURCE,
            "Approve the MSA",
            f"Done {BRIEF_POOL_PER_SOURCE - 2}",
        )

    async def test_news_outranks_what_an_earlier_brief_already_showed(self) -> None:
        shown = [_app_signal(n, shown=True) for n in range(BRIEF_POOL_PER_SOURCE)]
        news = [_app_signal(n) for n in range(100, 102)]

        gathered = await _gathered_signals(*shown, *news)

        assert _titles(gathered, "gmail")[-3:] == [
            f"Gmail {BRIEF_POOL_PER_SOURCE - 3}",
            "Gmail 100",
            "Gmail 101",
        ]

    async def test_a_pool_within_its_caps_drops_nothing_and_says_nothing(self) -> None:
        async with captured_wide_event() as event:
            gathered = await _gathered_signals(_app_signal(1))

        assert _titles(gathered, "gmail") == ["Gmail 1"]
        assert "pool_capped" not in event.get("briefing", {})

    async def test_every_calendar_event_stays_for_the_calendar_is_listed_whole(self) -> None:
        events = [
            BriefingEvent(
                date="2026-11-11", start=f"{8 + n // 4:02d}:{15 * (n % 4):02d}", title=f"Call {n}"
            )
            for n in range(BRIEF_POOL_PER_SOURCE + 3)
        ]
        sources = CandidateSources(
            TrackedWork(),
            _scouts(),
            events,
            CLOCK.day_start(days_ago=-1),
            [],
            last_brief_at=LAST_BRIEF,
        )

        gathered = await gather_candidates(USER_ID, CLOCK, NOW, NOW, sources)

        assert [c.title for c in gathered.pool.values()] == [e.title for e in events]


class TestAHeldResultSayingWhatAnotherSaysIsFolded:
    @staticmethod
    def _held(held_id: str, title: str, text: str) -> PendingBriefItemDocument:
        return PendingBriefItemDocument(
            id=held_id,
            user_id=USER_ID,
            source=BriefItemSource.WORKFLOW,
            source_id=f"wf-{held_id}",
            source_title=title,
            conversation_id=f"conv-{held_id}",
            text=text,
        )

    async def test_a_held_result_titled_like_another_candidate_or_an_earlier_held_one_is_folded(
        self,
    ) -> None:
        approve = _tracked("t1", "Approve  the MSA: signed", NEEDS_REPLY_LABEL)
        held = [
            self._held("h-msa", "approve the msa", "Signed"),
            self._held("h-digest", "Weekly digest", "Revenue up 4%"),
            self._held("h-digest-again", "WEEKLY digest", "revenue up 4%"),
            self._held("h-invoice", "Invoice", "Paid in full"),
        ]
        event = BriefingEvent(date="2026-11-11", start="09:00", title="Standup")
        sources = CandidateSources(
            TrackedWork(blocked=[approve]),
            _scouts(),
            [event],
            CLOCK.day_start(days_ago=-1),
            [],
            held=held,
            last_brief_at=LAST_BRIEF,
        )

        gathered = await gather_candidates(USER_ID, CLOCK, NOW, NOW, sources)

        assert [c.title for c in gathered.pool.values()] == [
            "Approve  the MSA: signed",
            "Weekly digest: Revenue up 4%",
            "Invoice: Paid in full",
            "Standup",
        ]
        assert gathered.duplicate_held_ids == ["h-msa", "h-digest-again"]


async def test_reminders_are_read_from_the_users_day_start_to_the_spans_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    find = AsyncMock(return_value=[])
    monkeypatch.setattr(reminder_repository, "find_scheduled_between", find)
    due_before = CLOCK.day_start(days_ago=-1)

    await gather_candidates(
        USER_ID,
        CLOCK,
        NOW,
        NOW,
        CandidateSources(TrackedWork(), _scouts(), [], due_before, [], last_brief_at=LAST_BRIEF),
    )

    find.assert_awaited_once_with(USER_ID, CLOCK.day_start(), due_before)


async def test_approvals_are_read_for_the_user_and_one_a_tracked_todo_parked_on_is_left_to_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def ledger(approval_id: str, owner_id: str) -> ApprovalLedgerDocument:
        return ApprovalLedgerDocument(
            approval_id=approval_id,
            conversation_id="conv-1",
            user_id=USER_ID,
            fingerprint=f"fp-{approval_id}",
            tool_name="GMAIL_SEND_EMAIL",
            summary=f"Send {approval_id}",
            owner_run_type="todo",
            owner_id=owner_id,
        )

    pending = AsyncMock(return_value=[ledger("ap_own", "t1"), ledger("ap_free", "t9")])
    monkeypatch.setattr(approval_ledger_repository, "list_pending_for_user", pending)
    approve = _tracked("t1", "Approve the MSA", NEEDS_REPLY_LABEL)

    gathered = await _gathered(TrackedWork(blocked=[approve]), _scouts())

    pending.assert_awaited_once_with(USER_ID)
    assert [c.title for c in gathered.pool.values()] == ["Approve the MSA", "Send ap_free"]


async def test_failed_runs_are_read_for_the_user_since_the_last_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    since = datetime(2026, 11, 10, 2, 30, tzinfo=UTC)
    system = AsyncMock(return_value=[])
    runs = AsyncMock(return_value=[])
    monkeypatch.setattr(workflow_repository, "find_system_workflows", system)
    monkeypatch.setattr(workflow_executions_repository, "list_since", runs)
    sources = CandidateSources(
        TrackedWork(), _scouts(), [], CLOCK.day_start(days_ago=-1), [], last_brief_at=LAST_BRIEF
    )

    await gather_candidates(USER_ID, CLOCK, since, NOW, sources)

    assert system.await_args.args[0] == USER_ID
    assert runs.await_args.args == (USER_ID, since)


async def test_held_results_look_up_the_users_own_inbox_desk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = AsyncMock(return_value=None)
    monkeypatch.setattr(todo_repository, "find_latest_by_external_ref", desk)
    held = PendingBriefItemDocument(
        id="h-1",
        user_id=USER_ID,
        source=BriefItemSource.WORKFLOW,
        source_id="wf-1",
        source_title="Digest",
        conversation_id="conv-h",
        text="Revenue up 4%",
    )
    sources = CandidateSources(
        TrackedWork(),
        _scouts(),
        [],
        CLOCK.day_start(days_ago=-1),
        [],
        held=[held],
        last_brief_at=LAST_BRIEF,
    )

    await gather_candidates(USER_ID, CLOCK, NOW, NOW, sources)

    desk.assert_awaited_once_with(USER_ID, INBOX_DESK_REF)


async def test_an_app_the_brief_could_not_read_is_named_with_why() -> None:
    scouts = ScoutSignals(
        results=[
            ScoutResult(integration_id="gmail", app="Gmail", outcome=ScoutOutcome.REPLAYED),
            ScoutResult(
                integration_id="slack",
                app="Slack",
                outcome=ScoutOutcome.SKIPPED,
                skip_reason=ScoutSkipReason.BUDGET,
            ),
        ],
        remembered=[],
        criteria={},
    )

    gathered = await _gathered(TrackedWork(), scouts)

    assert gathered.sources_unavailable == [
        UnreadSource(app="Slack", reason=ScoutSkipReason.BUDGET)
    ]
