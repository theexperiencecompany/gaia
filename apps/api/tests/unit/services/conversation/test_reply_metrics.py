"""reply_analytics: the Prometheus chat-turn series a settled reply feeds, once per turn on every surface."""

from datetime import timedelta

from prometheus_client import REGISTRY
import pytest

from app.constants.chat import ConversationSource
from app.models.conversation_log_models import LoggedEntry, StepClaim, UserMessage
from app.services.conversation.reply_analytics import capture_reply_ended
from app.services.latency_metrics import ChatTurnStatus
from shared.py.conversation_wire import ReplyOutcome
from tests.unit.services.conversation.log_helpers import T0, opened, settled
from tests.unit.services.conversation.runtime_doubles import CONVERSATION, USER, RecordingAnalytics

CLAIM = StepClaim(conversation_id=CONVERSATION, user_id=USER, epoch=1)


def _at(seq: int, entry: object, millis: float) -> LoggedEntry:
    return LoggedEntry.model_validate(
        {"seq": seq, "at": T0 + timedelta(milliseconds=millis), "entry": entry}
    )


def _said(surface: ConversationSource) -> LoggedEntry:
    return _at(1, UserMessage(id="u1", text="hi", surface=surface), 0)


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _end(outcome: ReplyOutcome, surface: ConversationSource, *, shown: bool = True) -> None:
    end = settled("s3", ["u1"], 1, reply_id="r1", outcome=outcome)
    since = [_at(2, opened("o2", "r1"), 400)] if shown else []
    capture_reply_ended(
        RecordingAnalytics(), CLAIM, [_said(surface)], end, T0 + timedelta(seconds=2), since
    )


@pytest.mark.parametrize(
    ("outcome", "surface", "status"),
    [
        (ReplyOutcome.ANSWERED, ConversationSource.WEB, ChatTurnStatus.OK),
        (ReplyOutcome.TRUNCATED, ConversationSource.VOICE, ChatTurnStatus.OK),
        (ReplyOutcome.FAILED, ConversationSource.TELEGRAM, ChatTurnStatus.ERROR),
        (ReplyOutcome.STOPPED, ConversationSource.DISCORD, ChatTurnStatus.CANCELLED),
    ],
)
def test_a_settled_turn_counts_once_under_its_surface_and_status(
    outcome: ReplyOutcome, surface: ConversationSource, status: ChatTurnStatus
) -> None:
    labels = {"source": surface.value, "status": status.value}
    before = _sample("chat_turn_total", **labels)

    _end(outcome, surface)

    assert _sample("chat_turn_total", **labels) == before + 1


def test_a_turn_records_its_first_text_and_its_settle_time_under_the_same_labels() -> None:
    labels = {"source": "slack", "status": "ok"}
    ttft = _sample("chat_ttft_seconds_sum", **labels)
    ack = _sample("chat_e2e_ack_seconds_sum", **labels)

    _end(ReplyOutcome.ANSWERED, ConversationSource.SLACK)

    assert _sample("chat_ttft_seconds_sum", **labels) == pytest.approx(ttft + 0.4)
    assert _sample("chat_e2e_ack_seconds_sum", **labels) == pytest.approx(ack + 2.0)


def test_a_turn_whose_reply_never_showed_records_no_first_text() -> None:
    labels = {"source": "whatsapp", "status": "error"}
    before = _sample("chat_ttft_seconds_count", **labels)

    _end(ReplyOutcome.FAILED, ConversationSource.WHATSAPP, shown=False)

    assert _sample("chat_ttft_seconds_count", **labels) == before
    assert _sample("chat_turn_total", **labels) >= 1


def test_a_settle_that_answers_no_user_message_counts_no_turn() -> None:
    before = sum(
        _sample("chat_turn_total", source=source.value, status=status.value)
        for source in ConversationSource
        for status in ChatTurnStatus
    )

    end = settled("s2", [], 1, outcome=ReplyOutcome.INTERIM)
    capture_reply_ended(RecordingAnalytics(), CLAIM, [], end, T0 + timedelta(seconds=1), [])

    after = sum(
        _sample("chat_turn_total", source=source.value, status=status.value)
        for source in ConversationSource
        for status in ChatTurnStatus
    )
    assert after == before
