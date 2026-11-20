"""fold_cards: a run's stream payloads fold into exactly the cards and image a client shows."""

from typing import cast

from app.constants.chat import SUBAGENT_GROUP_TOOL_NAME
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.models.conversation_frame_models import (
    ImageEvent,
    ReasoningEvent,
    SubagentEndEvent,
    SubagentStartEvent,
    TodoProgressEvent,
    ToolDataEvent,
    ToolOutputEvent,
)
from app.models.stream_events import (
    ReasoningPayload,
    SubagentEndPayload,
    SubagentStartPayload,
    ToolOutputPayload,
)
from app.services.conversation.tool_cards import (
    MCP_APP_CARD,
    REASONING_STEP,
    TODO_PROGRESS_CARD,
    TOOL_CALLS_CARD,
    FoldedCards,
    fold_cards,
)
from shared.py.conversation_wire import ImageData, ToolDataEntry

STARTED_AT = "2026-11-14T10:00:00+00:00"


def card(tool_name: str, data: object, **extra: str) -> ToolDataEntry:
    return cast(ToolDataEntry, {"tool_name": tool_name, "data": data, **extra})


def approval(approval_id: str, summary: str) -> ToolDataEvent:
    return ToolDataEvent(
        tool_data=card(APPROVAL_REQUEST_TOOL_NAME, {"approval_id": approval_id, "summary": summary})
    )


def start(subagent_id: str, parent: str | None = None) -> SubagentStartEvent:
    return SubagentStartEvent(
        subagent_start=SubagentStartPayload(
            subagent_id=subagent_id,
            subagent_name=f"{subagent_id}-name",
            subagent="gmail",
            agent_type="spawned",
            started_at=STARTED_AT,
            icon_url="https://icon",
            tool_category="mail",
            parent_subagent_id=parent,
        )
    )


def group(subagent_id: str, **changes: object) -> dict[str, object]:
    return {
        "subagent_id": subagent_id,
        "subagent": "gmail",
        "subagent_name": f"{subagent_id}-name",
        "agent_type": "spawned",
        "started_at": STARTED_AT,
        "icon_url": "https://icon",
        "tool_category": "mail",
        "tool_calls": [],
        "duration_ms": None,
        "token_count": None,
        "completed_at": None,
        "nested_subagents": [],
        **changes,
    }


def group_card(data: dict[str, object]) -> ToolDataEntry:
    return card(SUBAGENT_GROUP_TOOL_NAME, data, tool_category="subagent", timestamp=STARTED_AT)


def thinking(content: str) -> dict[str, object]:
    return {
        "tool_name": REASONING_STEP,
        "tool_category": REASONING_STEP,
        "message": "",
        "reasoning": content,
    }


def reasoning(content: str, subagent_id: str | None = None) -> ReasoningEvent:
    return ReasoningEvent(reasoning=ReasoningPayload(content=content, subagent_id=subagent_id))


def output(tool_call_id: str, text: str, subagent_id: str | None = None) -> ToolOutputEvent:
    return ToolOutputEvent(
        tool_output=ToolOutputPayload(
            tool_call_id=tool_call_id, output=text, subagent_id=subagent_id
        )
    )


def test_cards_fold_in_order_onto_a_seed_left_untouched() -> None:
    seed = [card("search", {"q": "a"})]
    shown = card("weather", {"city": "Pune"})
    folded = fold_cards([ToolDataEvent(tool_data=shown)], seed)
    assert folded == FoldedCards(
        tool_data=(card("search", {"q": "a"}), card("weather", {"city": "Pune"}))
    )
    folded.tool_data[0]["data"]["q"] = "changed"
    assert seed == [card("search", {"q": "a"})]


def test_an_approvals_later_frame_replaces_its_card_in_place() -> None:
    folded = fold_cards(
        [
            approval("a1", "first"),
            ToolDataEvent(tool_data=card("search", {"approval_id": "a1"})),
            approval("a2", "other"),
            approval("a1", "decided"),
        ]
    )
    assert folded.tool_data == (
        card(APPROVAL_REQUEST_TOOL_NAME, {"approval_id": "a1", "summary": "decided"}),
        card("search", {"approval_id": "a1"}),
        card(APPROVAL_REQUEST_TOOL_NAME, {"approval_id": "a2", "summary": "other"}),
    )


def test_a_subagents_tool_call_lands_in_its_group_and_its_other_cards_stand_alone() -> None:
    call = {"tool_call_id": "c1", "tool_name": "gmail_send"}
    own = card("weather", {"city": "Pune"}, subagent_id="s1")
    folded = fold_cards(
        [
            start("s1"),
            ToolDataEvent(tool_data=card(TOOL_CALLS_CARD, call, subagent_id="s1")),
            ToolDataEvent(tool_data=own),
        ]
    )
    assert folded.tool_data == (group_card(group("s1", tool_calls=[call])), own)


def test_an_output_fills_the_card_of_its_call_and_an_mcp_apps_tool_result() -> None:
    folded = fold_cards(
        [
            ToolDataEvent(tool_data=card("search", {"tool_call_id": "c1"})),
            ToolDataEvent(tool_data=card(MCP_APP_CARD, {"tool_call_id": "c2"})),
            ToolDataEvent(tool_data=card("plain", "not a dict")),
            output("c1", "found"),
            output("c2", "<html>"),
            output("c9", "nobody's"),
        ]
    )
    assert folded.tool_data == (
        card("search", {"tool_call_id": "c1", "output": "found"}),
        card(MCP_APP_CARD, {"tool_call_id": "c2", "tool_result": "<html>"}),
        card("plain", "not a dict"),
    )


def test_a_subagents_output_fills_only_its_own_call() -> None:
    first = {"tool_call_id": "c1", "tool_name": "a"}
    second = {"tool_call_id": "c2", "tool_name": "b"}
    folded = fold_cards(
        [
            start("s1"),
            ToolDataEvent(tool_data=card(TOOL_CALLS_CARD, first, subagent_id="s1")),
            ToolDataEvent(tool_data=card(TOOL_CALLS_CARD, second, subagent_id="s1")),
            ToolDataEvent(tool_data=card("search", {"tool_call_id": "c2"})),
            output("c2", "done", subagent_id="s1"),
        ]
    )
    assert folded.tool_data == (
        group_card(group("s1", tool_calls=[first, {**second, "output": "done"}])),
        card("search", {"tool_call_id": "c2"}),
    )


def test_thinking_merges_into_one_step_until_a_tool_call_follows_it() -> None:
    folded = fold_cards([reasoning("let me "), reasoning(""), reasoning("think")])
    assert folded.tool_data == (
        card(TOOL_CALLS_CARD, [thinking("let me think")], tool_category=REASONING_STEP),
    )
    after_a_call = fold_cards(
        [reasoning("plan")],
        [card(TOOL_CALLS_CARD, [{"tool_name": "search"}])],
    )
    assert after_a_call.tool_data == (
        card(TOOL_CALLS_CARD, [{"tool_name": "search"}]),
        card(TOOL_CALLS_CARD, [thinking("plan")], tool_category=REASONING_STEP),
    )


def test_a_subagents_thinking_lands_in_its_group() -> None:
    call = {"tool_call_id": "c1"}
    folded = fold_cards(
        [
            start("s1"),
            reasoning("first ", subagent_id="s1"),
            reasoning("thought", subagent_id="s1"),
            ToolDataEvent(tool_data=card(TOOL_CALLS_CARD, call, subagent_id="s1")),
            reasoning("then", subagent_id="s1"),
            reasoning(" more", subagent_id="s1"),
        ]
    )
    assert folded.tool_data == (
        group_card(
            group("s1", tool_calls=[thinking("first thought"), call, thinking("then more")])
        ),
    )


def test_a_call_lands_in_the_group_that_holds_its_subagent_and_no_other() -> None:
    call = {"tool_call_id": "c1"}
    lookalike = card("search", {"subagent_id": "s2"})
    folded = fold_cards(
        [
            ToolDataEvent(tool_data=lookalike),
            start("s1"),
            start("child", parent="s1"),
            start("s2"),
            ToolDataEvent(tool_data=card(TOOL_CALLS_CARD, call, subagent_id="s2")),
        ]
    )
    assert folded.tool_data == (
        lookalike,
        group_card(group("s1", nested_subagents=[group("child")])),
        group_card(group("s2", tool_calls=[call])),
    )


def test_a_nested_subagent_opens_and_ends_inside_its_parent() -> None:
    folded = fold_cards(
        [
            start("parent"),
            start("child", parent="parent"),
            start("orphan", parent="never-started"),
            SubagentEndEvent(
                subagent_end=SubagentEndPayload(
                    subagent_id="child", duration_ms=1500, token_count=7
                )
            ),
            SubagentEndEvent(
                subagent_end=SubagentEndPayload(subagent_id="parent", duration_ms=60000)
            ),
        ]
    )
    child = group(
        "child",
        duration_ms=1500,
        token_count=7,
        completed_at="2026-11-14T10:00:01.500000+00:00",
    )
    assert folded.tool_data == (
        group_card(
            group(
                "parent",
                duration_ms=60000,
                completed_at="2026-11-14T10:01:00+00:00",
                nested_subagents=[child],
            )
        ),
    )


def test_one_todo_card_leads_and_keeps_each_sources_newest_snapshot() -> None:
    folded = fold_cards(
        [
            ToolDataEvent(tool_data=card("search", {})),
            TodoProgressEvent(todo_progress={"todos": [1]}),
            TodoProgressEvent(todo_progress={"source": "s1", "todos": [2]}),
            TodoProgressEvent(todo_progress={"todos": [3]}),
        ]
    )
    assert folded.tool_data == (
        card(
            TODO_PROGRESS_CARD,
            {"executor": {"todos": [3]}, "s1": {"source": "s1", "todos": [2]}},
        ),
        card("search", {}),
    )


def test_the_last_image_made_is_the_runs_image() -> None:
    first, last = ImageData(url="https://a", prompt="a"), ImageData(url="https://b", prompt="b")
    folded = fold_cards([ImageEvent(image_data=first), ImageEvent(image_data=last)])
    assert folded == FoldedCards(image=last)
