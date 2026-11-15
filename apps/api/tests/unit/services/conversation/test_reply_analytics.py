"""reply_analytics: the turn-end event a settled reply counts, with its timings, surface and dedupe."""

from datetime import timedelta

import pytest

from app.constants.chat import ConversationSource
from app.models.conversation_log_models import LoggedEntry, StepClaim, UserMessage
from app.services.conversation.reply_analytics import (
    UNPROMPTED,
    capture_reply_ended,
    spoken_context,
)
from shared.py.analytics import Dedupe
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.chat import ChatBackgroundUpdateResolved, ChatMessageCompleted
from shared.py.analytics.context import AnalyticsContext
from shared.py.conversation_wire import ReplyOutcome
from tests.unit.services.conversation.log_helpers import T0, finished, opened, settled, started
from tests.unit.services.conversation.runtime_doubles import CONVERSATION, USER, RecordingAnalytics

CLAIM = StepClaim(conversation_id=CONVERSATION, user_id=USER, epoch=1)


def _at(seq: int, entry: object, millis: float) -> LoggedEntry:
    return LoggedEntry.model_validate(
        {"seq": seq, "at": T0 + timedelta(milliseconds=millis), "entry": entry}
    )


def _said(surface: ConversationSource) -> UserMessage:
    return UserMessage(id="u1", text="hi", surface=surface, posthog_session_id="sess-1")


@pytest.mark.parametrize(
    ("surface", "expected"),
    [
        (ConversationSource.DESKTOP, EntrySurface.DESKTOP),
        (ConversationSource.WEB, EntrySurface.WEB),
        (ConversationSource.TELEGRAM, EntrySurface.BOT),
        (ConversationSource.VOICE, EntrySurface.VOICE),
    ],
)
def test_a_message_is_counted_on_the_surface_it_was_sent_from(
    surface: ConversationSource, expected: EntrySurface
) -> None:
    assert spoken_context(_said(surface)) == AnalyticsContext(
        attribution=Attribution(actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=expected),
        posthog_session_id="sess-1",
    )


def test_an_answered_reply_counts_its_first_text_and_full_turn_to_the_hundredth_ms() -> None:
    analytics = RecordingAnalytics()
    asked = _at(1, _said(ConversationSource.WEB), 0)
    shown = _at(2, opened("o2", "r1"), 1234.5678)
    end = settled("s3", ["u1"], 1, reply_id="r1")
    ended_at = T0 + timedelta(milliseconds=2500.004)

    capture_reply_ended(analytics, CLAIM, [asked], end, ended_at, [shown, _at(3, end, 2500)])

    [(user_id, event, context, dedupe)] = analytics.ended
    assert user_id == USER
    assert isinstance(event, ChatMessageCompleted)
    assert (event.ttft_ms, event.e2e_full_ms, event.source) == (1234.57, 2500.0, "web")
    assert context == spoken_context(_said(ConversationSource.WEB))
    assert dedupe == Dedupe(key="s3", occurred_at=ended_at)


def test_a_reply_that_never_showed_counts_no_first_text() -> None:
    analytics = RecordingAnalytics()
    asked = _at(1, _said(ConversationSource.WEB), 0)
    end = settled("s2", ["u1"], 1, reply_id="r1")

    capture_reply_ended(analytics, CLAIM, [asked], end, T0 + timedelta(seconds=1), [])

    [(_user, event, _context, _dedupe)] = analytics.ended
    assert isinstance(event, ChatMessageCompleted)
    assert event.ttft_ms is None
    assert event.e2e_full_ms == 1000.0


def test_the_event_says_what_the_turn_waited_on_and_what_it_started() -> None:
    analytics = RecordingAnalytics()
    asked = _at(1, _said(ConversationSource.WEB), 0)
    since = [
        _at(2, started("w2", "t1", 1), 10),
        _at(3, opened("o3", "r0"), 20),
        _at(4, settled("s4", ["u0"], 1, reply_id="r0"), 30),
        _at(5, opened("o5", "r1"), 500),
        _at(6, settled("s6", ["u1"], 1, reply_id="r1"), 900),
    ]
    end = settled("s6", ["u1"], 1, reply_id="r1")

    capture_reply_ended(analytics, CLAIM, [asked], end, T0 + timedelta(milliseconds=900), since)

    [(_user, event, _context, _dedupe)] = analytics.ended
    assert isinstance(event, ChatMessageCompleted)
    assert (event.is_new_conversation, event.delegated, event.queued) == (True, True, True)
    assert event.ttft_ms == 500.0
    assert event.stream_id == "u1"
    assert event.conversation_id == CONVERSATION


def test_a_later_turn_with_nothing_before_it_neither_waited_nor_delegated() -> None:
    analytics = RecordingAnalytics()
    asked = _at(3, _said(ConversationSource.WEB), 0)
    since = [
        _at(4, started("w4", "t1", 2), 10),
        _at(5, opened("o5", "r1"), 100),
        _at(6, settled("s6", ["u1"], 3, reply_id="r1"), 200),
    ]
    end = settled("s6", ["u1"], 3, reply_id="r1")

    capture_reply_ended(analytics, CLAIM, [asked], end, T0 + timedelta(milliseconds=200), since)

    [(_user, event, _context, _dedupe)] = analytics.ended
    assert isinstance(event, ChatMessageCompleted)
    assert (event.is_new_conversation, event.delegated, event.queued) == (False, False, False)


@pytest.mark.parametrize(
    ("outcome", "resolved"),
    [(ReplyOutcome.ANSWERED, "message"), (ReplyOutcome.SILENT, "silence")],
)
def test_finished_work_no_one_asked_about_is_counted_as_resolved_by_the_settle(
    outcome: ReplyOutcome, resolved: str
) -> None:
    analytics = RecordingAnalytics()
    work = _at(1, finished("w1", "t1"), 0)
    end = settled("s2", ["w1"], 1, outcome=outcome)
    ended_at = T0 + timedelta(seconds=1)

    capture_reply_ended(analytics, CLAIM, [work], end, ended_at, [])

    assert analytics.ended == [
        (
            USER,
            ChatBackgroundUpdateResolved(outcome=resolved),
            UNPROMPTED,
            Dedupe(key="s2", occurred_at=ended_at),
        )
    ]


def test_finished_work_answered_with_a_message_counts_both_under_the_users_context() -> None:
    analytics = RecordingAnalytics()
    covers = [_at(1, finished("w1", "t1"), 0), _at(2, _said(ConversationSource.WEB), 10)]
    end = settled("s3", ["w1", "u1"], 2)

    capture_reply_ended(analytics, CLAIM, covers, end, T0 + timedelta(seconds=1), [])

    events = [(type(event), context) for _user, event, context, _dedupe in analytics.ended]
    said = spoken_context(_said(ConversationSource.WEB))
    assert events == [(ChatMessageCompleted, said), (ChatBackgroundUpdateResolved, said)]


@pytest.mark.parametrize("outcome", [ReplyOutcome.FAILED, ReplyOutcome.INTERIM])
def test_a_settle_that_did_not_resolve_the_work_counts_nothing(outcome: ReplyOutcome) -> None:
    analytics = RecordingAnalytics()
    end = settled("s2", [], 1, outcome=outcome)

    capture_reply_ended(
        analytics, CLAIM, [_at(1, finished("w1", "t1"), 0)], end, T0 + timedelta(seconds=1), []
    )

    assert analytics.ended == []
