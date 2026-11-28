"""The tool timeline an item shows, built from the card sequences live turns and old logs produce."""

import copy
from itertools import pairwise

from hypothesis import given, strategies as st
from pydantic import JsonValue

from app.constants.chat import BROWSER_TASK_TOOL_NAME, SUBAGENT_GROUP_TOOL_NAME, TOOL_CALLS_CARD
from app.services.conversation.tool_timeline import tool_timeline
from shared.py.conversation_wire import (
    TimelineStepKind,
    ToolDataEntry,
    ToolProgress,
    ToolTimeline,
)

_Json = dict[str, JsonValue]
_Row = tuple[TimelineStepKind, str, JsonValue]
TOOL = TimelineStepKind.TOOL
SUBAGENT = TimelineStepKind.SUBAGENT


def _calls(*calls: JsonValue) -> ToolDataEntry:
    return {
        "tool_name": TOOL_CALLS_CARD,
        "tool_category": "",
        "data": list(calls),
        "timestamp": None,
    }


def _group_card(group: JsonValue) -> ToolDataEntry:
    return {
        "tool_name": SUBAGENT_GROUP_TOOL_NAME,
        "tool_category": "",
        "data": group,
        "timestamp": None,
    }


def _call(call_id: str, tool_name: str = "web_search", **extra: JsonValue) -> _Json:
    return {"tool_call_id": call_id, "tool_name": tool_name, **extra}


def _thought(text: str) -> _Json:
    return {"reasoning": text}


def _handoff(call_id: str, agent: str, **extra: JsonValue) -> _Json:
    return _call(call_id, "handoff", message=f"Handing off to {agent}", **extra)


def _group(
    subagent_id: str,
    name: str,
    agent_type: str,
    calls: list[JsonValue] | None = None,
    nested: list[JsonValue] | None = None,
) -> _Json:
    return {
        "subagent_id": subagent_id,
        "subagent_name": name,
        "agent_type": agent_type,
        "tool_calls": calls or [],
        "nested_subagents": nested or [],
        "duration_ms": 1200,
    }


def _synthetic(
    subagent_id: str, name: str, *, handoff: bool, category: str | None, **extra: JsonValue
) -> _Json:
    return {
        "subagent_id": subagent_id,
        "subagent_name": name,
        "agent_type": "handoff" if handoff else "spawned",
        "tool_calls": [],
        "duration_ms": None,
        "token_count": None,
        "started_at": "",
        "completed_at": "synthetic",
        "icon_url": None,
        "tool_category": category,
        "nested_subagents": [],
        "step_keys": [],
        **extra,
    }


def _rows(cards: list[ToolDataEntry]) -> list[_Row]:
    return [(step.kind, step.key, step.data) for step in tool_timeline(cards).steps]


# --- plain calls ---------------------------------------------------------------------------------


def test_no_cards_show_nothing() -> None:
    assert tool_timeline([]) == ToolTimeline()


def test_calls_are_rows_keyed_by_call_id_or_a_slot_after_the_last_id() -> None:
    first: _Json = {"tool_name": "a"}
    second = _call("", "b")
    extra: _Json = {"tool_name": "a2"}
    named = _call("c1")
    third: _Json = {"tool_name": "c"}
    fourth: _Json = {"tool_name": "d"}
    cards = [_calls(first, second, 7, extra, named, third), _calls(fourth)]

    assert _rows(cards) == [
        (TOOL, "head#0", first),
        (TOOL, "head#1", second),
        (TOOL, "head#2", extra),
        (TOOL, "tc-c1", named),
        (TOOL, "tc-c1#0", third),
        (TOOL, "tc-c1#1", fourth),
    ]


def test_a_calls_card_holding_one_call_object_is_that_call() -> None:
    card: ToolDataEntry = {"tool_name": TOOL_CALLS_CARD, "data": _call("c1")}

    assert _rows([card]) == [(TOOL, "tc-c1", _call("c1"))]


def test_adjacent_thoughts_merge_into_the_first_and_a_tool_call_splits_them() -> None:
    cards = [
        _calls({"tool_call_id": "t1", "reasoning": "Let me "}, _thought("check ")),
        _calls(_thought("mail."), _call("c1"), _thought("Done"), {"reasoning": None}),
    ]

    assert _rows(cards) == [
        (TOOL, "tc-t1", {"tool_call_id": "t1", "reasoning": "Let me check mail."}),
        (TOOL, "tc-c1", _call("c1")),
        (TOOL, "tc-c1#0", _thought("Done")),
        (TOOL, "tc-c1#1", {"reasoning": None}),
    ]


def test_a_thought_never_merges_across_a_subagent_row() -> None:
    gmail = {**_group("g1", "Gmail", "handoff"), "reasoning": "group"}
    cards = [
        _calls(_thought("before"), _handoff("h1", "Gmail"), _thought("after")),
        _group_card(gmail),
    ]

    assert [(kind, key) for kind, key, _ in _rows(cards)] == [
        (TOOL, "head#0"),
        (SUBAGENT, "sa-g1"),
        (TOOL, "sa-g1#0"),
    ]


# --- progress ------------------------------------------------------------------------------------


def test_progress_is_the_newest_tool_call_that_names_a_message() -> None:
    older: ToolDataEntry = {
        "tool_name": TOOL_CALLS_CARD,
        "data": {
            "message": "Searching the web",
            "tool_name": "web_search",
            "tool_category": "search",
            "integration_name": "Google",
            "icon_url": "https://icons/google.png",
            "show_category": False,
        },
    }
    silent: ToolDataEntry = {"tool_name": TOOL_CALLS_CARD, "data": {"message": ""}}
    listed = _calls({"message": "in a list"})
    other: ToolDataEntry = {"tool_name": "weather_data", "data": {"message": "not a call"}}

    progress = tool_timeline([older, silent, listed, other]).progress

    assert progress == ToolProgress(
        message="Searching the web",
        tool_name="web_search",
        tool_category="search",
        integration_name="Google",
        icon_url="https://icons/google.png",
        show_category=False,
    )


def test_progress_reads_the_newest_of_several_and_defaults_what_it_lacks() -> None:
    older: ToolDataEntry = {"tool_name": TOOL_CALLS_CARD, "data": {"message": "Old"}}
    newer: ToolDataEntry = {
        "tool_name": TOOL_CALLS_CARD,
        "data": {
            "message": "Reading",
            "tool_name": 3,
            "tool_category": None,
            "integration_name": 5,
            "icon_url": 7,
            "show_category": "no",
        },
    }

    assert tool_timeline([older, newer]).progress == ToolProgress(
        message="Reading",
        tool_name="",
        tool_category="",
        integration_name=None,
        icon_url=None,
        show_category=True,
    )


def test_no_call_naming_a_message_has_no_progress() -> None:
    assert tool_timeline([_calls(_call("c1", message="in a list"))]).progress is None


# --- stand-alone cards ---------------------------------------------------------------------------


def test_grouped_cards_fold_into_one_card_each_ahead_of_the_single_cards() -> None:
    by_id: ToolDataEntry = {"tool_name": "weather_data", "data": {"tool_call_id": "w1"}}
    stamped: ToolDataEntry = {"tool_name": "weather_data", "data": {}, "timestamp": "T1"}
    listed: ToolDataEntry = {"tool_name": "notes", "data": [1, 2], "timestamp": None}
    blank: ToolDataEntry = {"tool_name": "notes", "data": {"tool_call_id": ""}, "timestamp": ""}
    cards: list[ToolDataEntry] = [
        by_id,
        {"tool_name": "search_results", "data": {"q": 1}},
        stamped,
        {"tool_name": "approval_request", "data": {"id": "a1"}},
        {"tool_name": "search_results", "data": {"q": 2}},
        listed,
        blank,
    ]

    shown = tool_timeline(cards).cards

    assert [(card.key, card.card) for card in shown] == [
        (
            "grouped-search_results",
            {
                "tool_name": "search_results",
                "tool_category": "",
                "data": [{"q": 1}, {"q": 2}],
                "timestamp": None,
            },
        ),
        (
            "grouped-approval_request",
            {
                "tool_name": "approval_request",
                "tool_category": "",
                "data": [{"id": "a1"}],
                "timestamp": None,
            },
        ),
        ("weather_data-w1", by_id),
        ("weather_data-T1", stamped),
        ("weather_data-T1#0", listed),
        ("weather_data-T1#1", blank),
    ]
    assert tool_timeline(cards).steps == ()


def test_a_subagent_group_card_that_is_not_an_object_shows_as_its_own_card() -> None:
    timeline = tool_timeline([_group_card("broken"), _calls(_call("c1"))])

    assert [(card.key, card.card) for card in timeline.cards] == [("head#0", _group_card("broken"))]
    assert [step.key for step in timeline.steps] == ["tc-c1"]


# --- logs written before subagent groups streamed ------------------------------------------------


def test_a_handoff_gathers_the_calls_after_it_into_a_synthetic_group() -> None:
    opener = _handoff(
        "h1", "Gmail", inputs={"subagent_id": "subagent:gmail_agent", "task": "read mail"}
    )
    inner = _call("c2")
    tail: _Json = {"tool_name": "x"}
    cards = [_calls(_call("c0"), opener, inner, _thought("a"), _thought("b"), tail)]

    assert _rows(cards) == [
        (TOOL, "tc-c0", _call("c0")),
        (
            SUBAGENT,
            "sa-h1",
            _synthetic(
                "h1",
                "Gmail",
                handoff=True,
                category="gmail",
                handoff_input="read mail",
                tool_calls=[inner, _thought("ab"), tail],
                step_keys=["h1-tc-c2", "h1-tc-c2#0", "h1-tc-c2#1"],
            ),
        ),
    ]


def test_a_handoff_that_failed_at_once_holds_none_of_the_later_calls() -> None:
    opener: _Json = {
        "tool_name": "call_subagent",
        "message": "handing off to Calendar",
        "inputs": "not an object",
        "output": "no calendar access",
    }
    cards = [_calls(opener, _call("c9"))]

    assert _rows(cards) == [
        (
            SUBAGENT,
            "sa-synth-0",
            _synthetic(
                "synth-0",
                "Calendar",
                handoff=True,
                category=None,
                handoff_output="no calendar access",
            ),
        ),
        (TOOL, "tc-c9", _call("c9")),
    ]


def test_a_spawn_outside_a_handoff_is_its_own_row_and_inside_one_nests() -> None:
    lone_spawn: _Json = {
        "tool_name": "think",
        "message": "Spawning subagent",
        "inputs": {"task": "dig"},
    }
    unnamed: _Json = {
        "tool_name": "handoff",
        "message": "Delegating",
        "inputs": {"subagent_id": "subagent:notion_agent"},
    }
    inner_spawn = _call("s2", "spawn_subagent", inputs={"task": "sum"}, output="done")
    cards = [_calls(lone_spawn, unnamed, inner_spawn, _call("c3"))]

    assert _rows(cards) == [
        (
            SUBAGENT,
            "sa-synth-spawn-0",
            _synthetic(
                "synth-spawn-0",
                "Task Agent",
                handoff=False,
                category="spawn_subagent",
                handoff_input="dig",
            ),
        ),
        (
            SUBAGENT,
            "sa-synth-1",
            _synthetic(
                "synth-1",
                "Subagent",
                handoff=True,
                category="notion",
                tool_calls=[_call("c3")],
                step_keys=["synth-1-tc-c3"],
                nested_subagents=[
                    _synthetic(
                        "s2",
                        "Task Agent",
                        handoff=False,
                        category="spawn_subagent",
                        handoff_input="sum",
                        handoff_output="done",
                    )
                ],
            ),
        ),
    ]


def test_unnamed_synthetic_groups_count_every_group_made_before_them() -> None:
    spawn: _Json = {"tool_name": "spawn_subagent"}
    handoff: _Json = {"tool_name": "handoff"}
    cards = [_calls(spawn, spawn, handoff, handoff, spawn, spawn)]

    rows = _rows(cards)

    assert [key for _, key, _ in rows] == [
        "sa-synth-spawn-0",
        "sa-synth-spawn-1",
        "sa-synth-2",
        "sa-synth-3",
    ]
    last = rows[-1][2]
    assert isinstance(last, dict)
    assert last["nested_subagents"] == [
        _synthetic(f"synth-spawn-{i}", "Task Agent", handoff=False, category="spawn_subagent")
        for i in (4, 5)
    ]


# --- streamed subagent groups --------------------------------------------------------------------


def test_a_streamed_group_takes_the_place_of_the_handoff_that_opened_it() -> None:
    gmail = _group("g1", "Gmail", "handoff", [_call("in1"), _thought("a"), _thought("b"), 5])
    cards = [
        _calls(
            _call("c0"),
            _handoff("h1", "Gmail", inputs={"task": "read"}, output="3 unread"),
            _call("in1"),
            _call("c2"),
        ),
        _group_card(gmail),
    ]

    assert _rows(cards) == [
        (TOOL, "tc-c0", _call("c0")),
        (
            SUBAGENT,
            "sa-g1",
            {
                **gmail,
                "tool_calls": [_call("in1"), _thought("ab")],
                "handoff_input": "read",
                "handoff_output": "3 unread",
                "step_keys": ["g1-tc-in1", "g1-tc-in1#0"],
            },
        ),
        (TOOL, "tc-c2", _call("c2")),
    ]


def test_a_group_whose_result_was_cut_names_the_results_full_length() -> None:
    spawned = _group("s1", "Task Agent", "spawned")
    spawn = _call("c1", "spawn_subagent", output="cut", output_original_length=500_000)

    ((_, _, row),) = _rows([_calls(spawn), _group_card(spawned)])

    assert isinstance(row, dict)
    assert (row["handoff_output"], row["handoff_output_original_length"]) == ("cut", 500_000)


def test_a_group_whose_result_is_whole_names_no_length() -> None:
    spawned = _group("s1", "Task Agent", "spawned")

    ((_, _, row),) = _rows(
        [_calls(_call("c1", "spawn_subagent", output="all")), _group_card(spawned)]
    )

    assert isinstance(row, dict)
    assert "handoff_output_original_length" not in row


def test_unanswered_handoffs_drop_and_groups_never_opened_trail() -> None:
    namesake = _group("s1", "Gmail", "spawned")
    gmail, notion = _group("g1", "Gmail", "handoff"), _group("g2", "Notion", "handoff")
    cards = [
        _calls(
            _handoff("hs", "Slack"),
            _handoff("ha", "Gmail"),
            _call("c1"),
            _handoff("hb", "Gmail"),
        ),
        _group_card(namesake),
        _group_card(gmail),
        _group_card(notion),
    ]

    assert [(kind, key) for kind, key, _ in _rows(cards)] == [
        (SUBAGENT, "sa-g1"),
        (TOOL, "tc-c1"),
        (SUBAGENT, "sa-s1"),
        (SUBAGENT, "sa-g2"),
    ]


def test_spawn_calls_open_the_spawned_groups_in_order() -> None:
    first, second = _group("s1", "Task Agent", "spawned"), _group("s2", "Task Agent", "spawned")
    cards = [
        _calls(
            _call("sp1", "spawn_subagent", inputs={"task": "a"}),
            _call("c1"),
            {"tool_name": "think", "message": "spawning subagent"},
            _call("sp3", "spawn_subagent"),
        ),
        _group_card(first),
        _group_card(second),
    ]

    assert _rows(cards) == [
        (SUBAGENT, "sa-s1", {**first, "handoff_input": "a", "step_keys": []}),
        (TOOL, "tc-c1", _call("c1")),
        (SUBAGENT, "sa-s2", {**second, "step_keys": []}),
    ]


def test_a_root_spawned_group_nests_in_the_next_handoff_that_spawned_one() -> None:
    first = _group("s1", "Task Agent", "spawned", [_call("deep")])
    gmail = _group("h1", "Gmail", "handoff", [_call("sp", "spawn_subagent")])
    notion = _group("h2", "Notion", "handoff", [_call("n1")])
    browser = _group("browser:b1", "Browser", "browser")
    slack = _group("h3", "Slack", "handoff", [_call("sp9", "spawn_subagent")], [browser])
    drive = _group("h4", "Drive", "handoff", [_call("sp4", "spawn_subagent")])
    second = _group("s2", "Task Agent", "spawned")
    groups = [first, gmail, notion, slack, drive, second]
    cards = [_calls(_call("deep"), _call("n1")), *map(_group_card, groups)]

    assert _rows(cards) == [
        (
            SUBAGENT,
            "sa-h1",
            {
                **gmail,
                "step_keys": ["h1-tc-sp"],
                "nested_subagents": [{**first, "step_keys": ["s1-tc-deep"]}],
            },
        ),
        (SUBAGENT, "sa-h2", {**notion, "step_keys": ["h2-tc-n1"]}),
        (
            SUBAGENT,
            "sa-h3",
            {
                **slack,
                "step_keys": ["h3-tc-sp9"],
                "nested_subagents": [
                    {**browser, "step_keys": []},
                    {**second, "step_keys": []},
                ],
            },
        ),
        (SUBAGENT, "sa-h4", {**drive, "step_keys": ["h4-tc-sp4"]}),
    ]


def test_a_group_already_nested_by_its_parent_does_not_repeat_as_a_root() -> None:
    calls: list[JsonValue] = [_call("deep"), _call("mid"), _thought("x"), _thought("y")]
    child = _group("s9", "Task Agent", "spawned", calls)
    parent = _group("h1", "Gmail", "handoff", nested=[child])
    # The child's own card is an earlier snapshot, streamed before its calls arrived.
    early = _group("s9", "Task Agent", "spawned")
    cards = [_calls(_call("deep")), _group_card(parent), _group_card(early)]
    before = copy.deepcopy(cards)

    rows = _rows(cards)

    assert cards == before
    assert rows == [
        (
            SUBAGENT,
            "sa-h1",
            {
                **parent,
                "step_keys": [],
                "nested_subagents": [
                    {
                        **child,
                        "tool_calls": [_call("deep"), _call("mid"), _thought("xy")],
                        "step_keys": ["s9-tc-deep", "s9-tc-mid", "s9-tc-mid#0"],
                    }
                ],
            },
        )
    ]


def test_a_browser_task_opens_its_own_browser_group_once() -> None:
    booked = _group("browser:bt1", "Browser", "browser", [_call("click")])
    unopened = _group("browser:", "Browser", "browser")
    mismatched = _group("browser:ws", "Browser", "browser")
    opener = _call("bt1", BROWSER_TASK_TOOL_NAME, inputs={"task": "book"}, output="booked")
    again, lone = _call("bt1", BROWSER_TASK_TOOL_NAME), _call("bt2", BROWSER_TASK_TOOL_NAME)
    blank = _call("", BROWSER_TASK_TOOL_NAME)
    cards = [
        _calls(opener, again, lone, blank, _call("ws")),
        _group_card(booked),
        _group_card(unopened),
        _group_card(mismatched),
    ]

    assert _rows(cards) == [
        (
            SUBAGENT,
            "sa-browser:bt1",
            {
                **booked,
                "handoff_input": "book",
                "handoff_output": "booked",
                "step_keys": ["browser:bt1-tc-click"],
            },
        ),
        (TOOL, "tc-bt1", again),
        (TOOL, "tc-bt2", lone),
        (TOOL, "tc-bt2#0", blank),
        (TOOL, "tc-ws", _call("ws")),
        (SUBAGENT, "sa-browser:", {**unopened, "step_keys": []}),
        (SUBAGENT, "sa-browser:ws", {**mismatched, "step_keys": []}),
    ]


# --- properties over random turns ----------------------------------------------------------------


def _random_call(index: int, kind: str) -> _Json:
    call_id = f"c{index}"
    match kind:
        case "handoff":
            return _handoff(call_id, "Gmail", inputs={"task": "t"})
        case "spawn":
            return _call(call_id, "spawn_subagent")
        case "thought":
            return _thought(f"r{index}")
        case "browser":
            return _call(call_id, BROWSER_TASK_TOOL_NAME)
        case _:
            return _call(call_id)


_KINDS = st.sampled_from(["plain", "handoff", "spawn", "thought", "browser"])


@given(kinds=st.lists(_KINDS, max_size=12), streamed=st.booleans())
def test_the_timeline_is_pure_and_keys_every_row_once(kinds: list[str], streamed: bool) -> None:
    calls: list[JsonValue] = [_random_call(i, kind) for i, kind in enumerate(kinds)]
    cards: list[ToolDataEntry] = [_calls(*calls)]
    if streamed:
        cards += [
            _group_card(_group("g", "Gmail", "handoff", [_call("x0"), _thought("a")])),
            _group_card(_group("s", "Task Agent", "spawned")),
            _group_card(_group("browser:c1", "Browser", "browser")),
        ]
    before = copy.deepcopy(cards)

    timeline = tool_timeline(cards)

    assert cards == before
    assert tool_timeline(cards) == timeline
    keys = [step.key for step in timeline.steps]
    assert len(keys) == len(set(keys))
    # A tool-call row never holds two thoughts in a row: adjacent ones fold into one.
    kinds_shown = [
        isinstance(step.data, dict) and isinstance(step.data.get("reasoning"), str)
        for step in timeline.steps
    ]
    assert not any(a and b for a, b in pairwise(kinds_shown))
