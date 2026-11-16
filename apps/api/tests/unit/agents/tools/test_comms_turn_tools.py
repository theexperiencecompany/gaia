from collections.abc import Iterator

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolCall
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException
import pytest

from app.agents.core.comms_ledger import (
    Closing,
    Closure,
    close_ledger,
    drain,
    open_ledger,
    still_open,
)
from app.agents.tools.comms_turn_tools import (
    AnsweredArgs,
    ReactArgs,
    answered,
    react,
    reaction_refusal,
    stay_silent,
    turn_ending,
    unanswered_in_words,
)
from app.constants.chat import ConversationSource
from app.constants.comms import ANSWERED_TOOL_NAME, REACT_TOOL_NAME
from app.constants.conversation import LOG_SEQ
from app.constants.reactions import TELEGRAM_REACTION_PALETTE
from tests.tool_helpers import tool_coroutine

RUN = "comms-turn-tools-run"


@pytest.fixture
def config() -> Iterator[RunnableConfig]:
    open_ledger(RUN, {1: "m1", 2: "m2", 3: "m3"})
    yield {"configurable": {"comms_run": RUN}}
    close_ledger(RUN)


def asked(seq: int) -> HumanMessage:
    return HumanMessage(content=f"question {seq}", additional_kwargs={LOG_SEQ: seq})


def test_telegram_refuses_an_emoji_outside_its_set_and_lists_the_set_one_by_one() -> None:
    surface: RunnableConfig = {
        "configurable": {"conversation_source": ConversationSource.TELEGRAM.value}
    }
    refusal = reaction_refusal("🔎", surface)
    assert refusal is not None
    _, offered = refusal.split("Pick exactly one of: ")
    assert offered.split(" ") == list(TELEGRAM_REACTION_PALETTE)


async def test_answered_closes_messages_a_reply_written_after_them_answers(
    config: RunnableConfig,
) -> None:
    said = [asked(1), AIMessage(content="36")]
    assert (
        await tool_coroutine(answered, str)(message_ids=[1], config=config, messages=said)
        == "Noted."
    )
    assert drain(RUN) == [Closure(how=Closing.ANSWERED, seqs=(1,))]


async def test_answered_with_no_words_names_every_unanswered_message_and_closes_none(
    config: RunnableConfig,
) -> None:
    said = [AIMessage(content="earlier"), asked(1), asked(2)]
    with pytest.raises(ToolException) as refused:
        await tool_coroutine(answered, str)(message_ids=[1, 2], config=config, messages=said)
    assert str(refused.value) == (
        "Nothing you wrote answers #1, #2 yet. Write the answer in your reply, then name it."
    )
    assert set(still_open(RUN)) == {1, 2, 3}


def test_only_gaias_own_words_after_a_message_answer_it() -> None:
    later_user_text: list[AnyMessage] = [asked(1), HumanMessage(content="also this")]
    wordless_call = [asked(1), AIMessage(content="")]
    never_given = [AIMessage(content="hi")]
    assert unanswered_in_words(later_user_text, [1]) == [1]
    assert unanswered_in_words(wordless_call, [1]) == [1]
    assert unanswered_in_words(never_given, [9]) == [9]


async def test_react_closes_its_message_with_its_emoji(config: RunnableConfig) -> None:
    assert (
        await tool_coroutine(react, str)(emoji="👀", message_id=2, config=config) == "Reacted 👀."
    )
    assert drain(RUN) == [Closure(how=Closing.REACTED, seqs=(2,), emoji="👀", reacted=(2,))]


async def test_stay_silent_closes_the_messages_it_names(config: RunnableConfig) -> None:
    result = await tool_coroutine(stay_silent, str)(
        reason="nothing new", config=config, message_ids=[1, 3]
    )
    assert result == "Sent nothing."
    assert drain(RUN) == [Closure(how=Closing.SILENT, seqs=(1, 3))]


def test_a_reaction_beside_answered_decides_how_the_turn_ends() -> None:
    calls = [
        ToolCall(name=ANSWERED_TOOL_NAME, args={"message_ids": [1]}, id="a"),
        ToolCall(name=REACT_TOOL_NAME, args={"emoji": "👍", "message_id": 2}, id="r"),
    ]
    assert turn_ending(AIMessage(content="", tool_calls=calls), {}) == ReactArgs(
        emoji="👍", message_id=2
    )
    assert turn_ending(AIMessage(content="", tool_calls=calls[:1]), {}) == AnsweredArgs(
        message_ids=[1]
    )
