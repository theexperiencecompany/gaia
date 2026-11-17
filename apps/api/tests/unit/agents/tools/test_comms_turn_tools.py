from collections.abc import Iterator
import re

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolCall
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException
from pydantic import ValidationError
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
from app.agents.templates.agent_template import get_comms_static_prompt
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
from app.constants.reactions import (
    REACTION_PALETTE_BY_SURFACE,
    TELEGRAM_REACTION_PALETTE,
    THANKS_REACTION_EMOJI,
    surface_reaction,
)
from app.models.agent_config import RunSurfaceMissingError
from tests.tool_helpers import tool_coroutine

RUN = "comms-turn-tools-run"
# An emoji with any joiners, selectors and gender signs that make one glyph of it.
EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff\u2600-\u27bf]"
    "(?:[\u200d\ufe0f\u2640\u2642]|[\U0001f000-\U0001faff\u2600-\u27bf])*"
)
QUOTED_RE = re.compile(r'"[^"\n]*"')


@pytest.fixture
def config() -> Iterator[RunnableConfig]:
    open_ledger(RUN, {1: "m1", 2: "m2", 3: "m3"})
    yield {
        "configurable": {
            "comms_run": RUN,
            "conversation_source": ConversationSource.WEB.value,
        }
    }
    close_ledger(RUN)


def asked(seq: int) -> HumanMessage:
    return HumanMessage(content=f"question {seq}", additional_kwargs={LOG_SEQ: seq})


def test_telegram_refuses_an_emoji_outside_its_set_and_lists_the_set_one_by_one() -> None:
    assert surface_reaction(ConversationSource.TELEGRAM, "🔎") is None
    refusal = reaction_refusal(ConversationSource.TELEGRAM, "🔎")
    _, offered = refusal.split("Pick exactly one of: ")
    assert offered.split(" ") == list(TELEGRAM_REACTION_PALETTE)


@pytest.mark.parametrize(
    ("configurable", "refused"),
    [({}, RunSurfaceMissingError), ({"conversation_source": "fax"}, ValidationError)],
)
async def test_a_run_with_no_known_surface_is_refused_rather_than_taking_any_emoji(
    configurable: dict[str, str], refused: type[Exception]
) -> None:
    with pytest.raises(refused):
        await tool_coroutine(react, str)(
            emoji="🔎", message_id=1, config={"configurable": configurable}
        )


async def test_telegram_stores_an_emoji_written_with_its_presentation_selector_as_its_palette_spells_it(
    config: RunnableConfig,
) -> None:
    config["configurable"]["conversation_source"] = ConversationSource.TELEGRAM.value
    reply = await tool_coroutine(react, str)(emoji="❤️", message_id=2, config=config)
    assert reply == "Reacted ❤."
    assert drain(RUN) == [Closure(how=Closing.REACTED, seqs=(2,), emoji="❤", reacted=(2,))]


async def test_a_refused_reaction_closes_nothing_and_tells_the_model_the_set(
    config: RunnableConfig,
) -> None:
    config["configurable"]["conversation_source"] = ConversationSource.TELEGRAM.value
    reply = await tool_coroutine(react, str)(emoji="🔎", message_id=2, config=config)
    assert reply == reaction_refusal(ConversationSource.TELEGRAM, "🔎")
    assert drain(RUN) == []


@pytest.mark.parametrize("source", list(ConversationSource))
def test_the_prompts_thanks_reaction_is_accepted_on_every_surface(
    source: ConversationSource,
) -> None:
    assert f"{REACT_TOOL_NAME} with {THANKS_REACTION_EMOJI}" in COMMS_AGENT_PROMPT
    assert surface_reaction(source, THANKS_REACTION_EMOJI) == THANKS_REACTION_EMOJI


@pytest.mark.parametrize("source", sorted(REACTION_PALETTE_BY_SURFACE))
def test_every_emoji_a_surfaces_prompt_names_is_one_its_reactions_accept(
    source: ConversationSource,
) -> None:
    # A quoted name ("🤖 BACKGROUND EXECUTION") is a banner the context shows, not a reaction to give.
    unquoted = QUOTED_RE.sub("", get_comms_static_prompt(source))
    named = EMOJI_RE.findall(unquoted)
    refused = {emoji for emoji in named if surface_reaction(source, emoji) is None}
    assert named
    assert refused == set()


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
    web: RunnableConfig = {"configurable": {"conversation_source": ConversationSource.WEB.value}}
    calls = [
        ToolCall(name=ANSWERED_TOOL_NAME, args={"message_ids": [1]}, id="a"),
        ToolCall(name=REACT_TOOL_NAME, args={"emoji": "👍", "message_id": 2}, id="r"),
    ]
    assert turn_ending(AIMessage(content="", tool_calls=calls), web) == ReactArgs(
        emoji="👍", message_id=2
    )
    assert turn_ending(AIMessage(content="", tool_calls=calls[:1]), web) == AnsweredArgs(
        message_ids=[1]
    )
