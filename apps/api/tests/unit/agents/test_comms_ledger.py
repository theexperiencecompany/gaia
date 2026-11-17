from collections.abc import Iterator

from langchain_core.runnables import RunnableConfig
import pytest

from app.agents.core.comms_ledger import (
    Closing,
    Closure,
    NotOpenError,
    answer_sole,
    close,
    close_ledger,
    drain,
    named,
    open_ledger,
    owe,
    still_open,
)

RUN = "comms-ledger-run"
NO_LEDGER: RunnableConfig = {"configurable": {}}


@pytest.fixture
def config() -> Iterator[RunnableConfig]:
    open_ledger(RUN, {1: "m1", 2: "m2"})
    yield {"configurable": {"comms_run": RUN}}
    close_ledger(RUN)


def test_closing_a_ledger_twice_is_harmless(config: RunnableConfig) -> None:
    close_ledger(RUN)
    close_ledger(RUN)
    assert named(config, [1]) is None


def test_messages_handed_mid_run_are_owed_too(config: RunnableConfig) -> None:
    owe(RUN, {3: "m3"})
    assert still_open(RUN) == {1: "m1", 2: "m2", 3: "m3"}


def test_the_sole_open_message_is_answered_by_the_run_ending_on_words(
    config: RunnableConfig,
) -> None:
    close(config, Closing.SILENT, [1])
    drain(RUN)
    assert answer_sole(RUN) is True
    assert drain(RUN) == [Closure(how=Closing.ANSWERED, seqs=(2,))]
    assert still_open(RUN) == {}


def test_words_answer_nothing_when_several_or_none_are_open(config: RunnableConfig) -> None:
    assert answer_sole(RUN) is False
    assert still_open(RUN) == {1: "m1", 2: "m2"}
    close(config, Closing.SILENT, [1, 2])
    drain(RUN)
    assert answer_sole(RUN) is False
    assert drain(RUN) == []


def test_named_returns_the_ids_of_open_messages_without_closing_them(
    config: RunnableConfig,
) -> None:
    assert named(config, [2, 1, 2]) == ("m2", "m1")
    assert still_open(RUN) == {1: "m1", 2: "m2"}
    assert drain(RUN) == []


def test_a_run_with_no_ledger_names_and_closes_nothing() -> None:
    assert named(NO_LEDGER, [1]) is None
    assert close(NO_LEDGER, Closing.ANSWERED, [1]) is None


def test_close_returns_the_ids_and_records_the_closure(config: RunnableConfig) -> None:
    assert close(config, Closing.HANDED, [2, 2]) == ("m2",)
    assert drain(RUN) == [Closure(how=Closing.HANDED, seqs=(2,))]
    assert still_open(RUN) == {1: "m1"}


def test_a_message_closed_earlier_in_the_same_step_can_be_named_again(
    config: RunnableConfig,
) -> None:
    close(config, Closing.REACTED, [1], "👀")
    assert close(config, Closing.HANDED, [1]) == ("m1",)
    assert drain(RUN) == [
        Closure(how=Closing.REACTED, seqs=(1,), emoji="👀", reacted=(1,)),
        Closure(how=Closing.HANDED, seqs=(1,)),
    ]


def test_naming_a_message_not_open_lists_what_is_open_and_closes_nothing(
    config: RunnableConfig,
) -> None:
    with pytest.raises(NotOpenError) as refused:
        close(config, Closing.ANSWERED, [1, 7, 9])
    assert str(refused.value) == (
        "name messages still open in this conversation (open now: #1, #2); not open: #7, #9"
    )
    assert still_open(RUN) == {1: "m1", 2: "m2"}
    assert drain(RUN) == []


def test_naming_no_message_is_refused_even_with_nothing_open(config: RunnableConfig) -> None:
    close(config, Closing.SILENT, [1, 2])
    drain(RUN)
    with pytest.raises(NotOpenError) as refused:
        named(config, [])
    assert str(refused.value) == (
        "name messages still open in this conversation (open now: none); not open: no ids given"
    )
