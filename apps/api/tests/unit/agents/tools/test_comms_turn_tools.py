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
from app.agents.prompts.comms_prompts import COMMS_AGENT_PROMPT
from app.agents.tools.comms_turn_tools import (
    AnsweredArgs,
    HandoffArgs,
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
from app.constants.general import CALL_EXECUTOR_NAME
from app.constants.reactions import TELEGRAM_REACTION_PALETTE, THANKS_REACTION_EMOJI
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


def test_telegram_takes_an_emoji_written_with_its_presentation_selector() -> None:
    surface: RunnableConfig = {
        "configurable": {"conversation_source": ConversationSource.TELEGRAM.value}
    }
    assert reaction_refusal("❤️", surface) is None


@pytest.mark.parametrize("source", list(ConversationSource))
def test_the_prompts_thanks_reaction_is_accepted_on_every_surface(
    source: ConversationSource,
) -> None:
    assert f"{REACT_TOOL_NAME} with {THANKS_REACTION_EMOJI}" in COMMS_AGENT_PROMPT
    surface: RunnableConfig = {"configurable": {"conversation_source": source.value}}
    assert reaction_refusal(THANKS_REACTION_EMOJI, surface) is None


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
    wordless_call: list[AnyMessage] = [asked(1), AIMessage(content="")]
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


def _handoff(args: dict[str, object]) -> ToolCall:
    return ToolCall(name=CALL_EXECUTOR_NAME, args={"task": "clean my inbox", **args}, id="h")


def test_a_hand_off_carrying_its_ack_ends_the_turn_and_one_without_does_not() -> None:
    def ending(*calls: ToolCall) -> object:
        return turn_ending(AIMessage(content="", tool_calls=list(calls)), {})

    answering = ToolCall(name=ANSWERED_TOOL_NAME, args={"message_ids": [2]}, id="a")
    lookup = ToolCall(name="web_search_tool", args={"query": "x"}, id="w")
    assert ending(_handoff({"ack": "on it"})) == HandoffArgs(ack="on it")
    assert ending(answering, _handoff({"ack": "36. on it"})) == HandoffArgs(ack="36. on it")
    assert ending(_handoff({})) is None
    assert ending(_handoff({"ack": "  "})) is None
    assert ending(_handoff({"ack": "on it"}), lookup) is None


def test_a_hand_offs_ack_is_words_answered_can_name() -> None:
    acked: list[AnyMessage] = [
        asked(1),
        AIMessage(content="", tool_calls=[_handoff({"ack": "36. on the rest now"})]),
    ]
    assert unanswered_in_words(acked, [1]) == []
