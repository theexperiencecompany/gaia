"""The daily brief's voice prompt gives each situation its own instructions, and only that one.

The idle-streak warning, the goodbye brief, the win-back message and the first brief
each switch on a branch. A branch that drops its instructions, or leaks them into an
ordinary morning, changes what the model tells the user with nothing else noticing:
an active user told the briefs are about to stop, or a dormant one never warned.
"""

from typing import Any

import pytest

from app.agents.prompts.briefing_prompts import (
    VoicePromptBlocks,
    VoiceSituation,
    build_briefing_voice_prompt,
    build_day_zero_hello_prompt,
    build_weekly_digest_prompt,
    reader_line,
    voice_correction_note,
)

_GOAL = "Raising a seed round [mentioned 2026-10-01]"

_BLOCKS = VoicePromptBlocks(
    reader=reader_line("Ada"),
    facts="- gaia: vetted 12 investors",
    goal=_GOAL,
    lookback="Yesterday: two drafts written",
    replies="(no replies)",
)


def test_the_voice_knows_the_readers_first_name_and_may_cite_it() -> None:
    """The voice check rejects any name outside the context, so the reader's must be in it."""
    assert "You're writing to Ada." in _prompt()
    assert "Ada" in _BLOCKS.context


def test_a_named_reader_is_named_at_most_once_and_never_in_a_greeting() -> None:
    assert reader_line("Ada") == (
        "You're writing to Ada. Use their name at most once, only where a friend "
        "naturally would, never as a greeting."
    )


@pytest.mark.parametrize("first_name", [None, ""])
def test_a_reader_with_no_name_is_never_addressed_by_one(first_name: str | None) -> None:
    assert reader_line(first_name) == "You don't know their name, so never address them by name."


_WIND_DOWN_WARN = (
    "GAIA has had nothing to work on for days: no goal, no lanes.",
    "Say so plainly in ONE short message and warn honestly: unless they tell you what "
    "they're working on, tomorrow's brief is the last one and the nightly work pauses "
    "with it.",
    "Not a guilt trip, plain operational honesty; end on the one question that restarts "
    "everything (what are you working on right now?).",
)

_WIND_DOWN_FINAL = (
    "This is the goodbye brief.",
    "ONE short message only: you're pausing the daily briefs and the night work because there's "
    "nothing to work on, and one reply naming a goal brings it all back the moment they "
    "send it.",
    "No summary, no stats, no filler; warm, short, zero guilt.",
    "This overrides the goal-question guidance below: no multi-option question, just the goodbye.",
)

_WINBACK = (
    "This user has ignored the last several briefings; this is the one message before "
    "GAIA goes quiet.",
    'Set mood to "winback" and send ONE short message.',
    "Lead with the single most valuable specific sitting in the facts: the finished "
    "deliverable they never opened, named concretely ('the 12-investor list is still "
    "sitting here; want it, or should I bin it?').",
    "End on one binary choice: they want it, or they tell GAIA what changed.",
    "If the facts hold nothing of value, ask one concrete question about whether the goal "
    "itself is still right ('still raising, or has the plan moved?').",
    "Never 'just checking in', never 'we miss you', never a guilt-trip, never a feature tour.",
)

_FIRST_BRIEF = (
    "This is the user's first briefing: make it land, reference their goal by name, keep "
    "it warm and specific.",
)

_FIRST_WEEK = (
    "This user joined GAIA this week. After today's facts, close on ONE concrete step that "
    "gets them real value, chosen from THEIR GAIA SETUP and the goal knowledge: no app "
    "connected yet, offer to connect the one their goal or work most needs; no goal known, "
    "ask for one; otherwise name one thing you can do with an app they already connected.",
    "Never name an app, goal or capability those facts don't support.",
)

_LIGHTER_CADENCE = (
    "This user hasn't opened GAIA in over a week.",
    "Don't guilt them and don't go quiet: in one short line, offer a lighter rhythm than "
    "THEIR GAIA SETUP shows (weekdays only, just the Sunday digest, or no briefs) and say "
    "a one-word reply changes it.",
)

_ALL_SITUATIONS = (
    _WIND_DOWN_WARN,
    _WIND_DOWN_FINAL,
    _WINBACK,
    _FIRST_BRIEF,
    _FIRST_WEEK,
    _LIGHTER_CADENCE,
)


def _prompt(
    *,
    winback: bool = False,
    is_first_briefing: bool = False,
    wind_down: str | None = None,
    first_week: bool = False,
    offer_lighter_cadence: bool = False,
    recent_openings: list[str] | None = None,
) -> str:
    return build_briefing_voice_prompt(
        date_local="Tuesday, October 14",
        blocks=_BLOCKS,
        situation=VoiceSituation(
            winback=winback,
            is_first_briefing=is_first_briefing,
            wind_down=wind_down,
            first_week=first_week,
            offer_lighter_cadence=offer_lighter_cadence,
        ),
        recent_openings=recent_openings or [],
    )


def test_an_ordinary_morning_goes_straight_from_goal_memory_to_the_goal_guidance() -> None:
    prompt = _prompt()

    assert f"{_GOAL}\n\nIf no goal lane exists" in prompt
    for situation in _ALL_SITUATIONS:
        assert situation[0] not in prompt


@pytest.mark.parametrize(
    ("situation", "expected"),
    [
        ({"wind_down": "warn"}, _WIND_DOWN_WARN),
        ({"wind_down": "final"}, _WIND_DOWN_FINAL),
        ({"winback": True}, _WINBACK),
        ({"is_first_briefing": True}, _FIRST_BRIEF),
        ({"first_week": True}, _FIRST_WEEK),
        ({"offer_lighter_cadence": True}, _LIGHTER_CADENCE),
    ],
    ids=[
        "wind-down-warn",
        "wind-down-final",
        "winback",
        "first-brief",
        "first-week",
        "lighter-cadence",
    ],
)
def test_each_situation_gives_its_own_instructions_and_no_other(
    situation: dict[str, Any], expected: tuple[str, ...]
) -> None:
    prompt = _prompt(**situation)

    for instruction in expected:
        assert instruction in prompt
    for other in _ALL_SITUATIONS:
        if other is not expected:
            assert other[0] not in prompt


@pytest.mark.parametrize(
    ("situation", "note"),
    [({"first_week": True}, _FIRST_WEEK), ({"offer_lighter_cadence": True}, _LIGHTER_CADENCE)],
    ids=["first-week", "lighter-cadence"],
)
def test_an_account_note_sits_whole_between_goal_memory_and_the_goal_guidance(
    situation: dict[str, Any], note: tuple[str, ...]
) -> None:
    assert f"{_GOAL}\n\n{' '.join(note)}\n\nIf no goal lane exists" in _prompt(**situation)


def test_the_voice_is_told_to_summarise_first_and_link_only_what_the_user_opens() -> None:
    """Every fact carries a summary, a size and a link; only an item worth opening earns its link."""
    prompt = " ".join(_prompt().split())

    assert "ALWAYS summarise, THEN maybe link — never a bare link." in prompt
    assert (
        "Every fact carries a ``summary:`` (concrete specifics) you MUST voice, a size hint "
        "(``artifact holds ~N chars``), and a ``link:`` you decide whether to use."
    ) in prompt
    assert (
        "Never invent a token number, and never paste an artifact's contents into the message."
    ) in prompt


def test_an_unknown_wind_down_stage_adds_nothing() -> None:
    assert _prompt(wind_down="paused") == _prompt()


def test_the_correction_note_lists_each_problem_on_its_own_line_between_header_and_retry() -> None:
    note = voice_correction_note(["headline names Dhruv", "lede counts 3 drafts"])

    assert note.splitlines() == [
        "## YOUR LAST BRIEF WAS REJECTED",
        "It did not match today's facts:",
        "- headline names Dhruv",
        "- lede counts 3 drafts",
        "Write it again from today's facts only, then return the whole JSON.",
    ]


def test_recent_openings_are_listed_for_the_model_to_avoid() -> None:
    prompt = _prompt(recent_openings=["Priya replied overnight.", "Big day for the raise."])

    assert (
        "## HOW YOUR LAST BRIEFS OPENED (open today's message differently)\n"
        "- Priya replied overnight.\n"
        "- Big day for the raise.\n"
    ) in prompt


def test_without_recent_briefs_no_openings_block_is_added() -> None:
    prompt = _prompt()

    assert "HOW YOUR LAST BRIEFS OPENED" not in prompt
    assert 'Never ask an open-ended "what can I help with".\n\n## THE MESSAGE' in prompt


@pytest.mark.parametrize(
    "prompt",
    [_prompt(), build_weekly_digest_prompt(date_local="2026-10-18", week_summary_block="-")],
    ids=["daily", "weekly"],
)
def test_daily_and_weekly_share_one_message_voice(prompt: str) -> None:
    assert "## THE MESSAGE (``message``)" in prompt
    assert '"message": "<the brief as a text, see THE MESSAGE>"' in prompt


def test_everything_the_model_is_shown_is_what_its_prose_may_cite() -> None:
    context = _BLOCKS.context

    for block in (_BLOCKS.facts, _BLOCKS.goal, _BLOCKS.lookback, _BLOCKS.replies):
        assert block in context


_OFFERS_A_DELIVERABLE = "OFFER one specific\nfirst deliverable as a QUESTION"
_ASKS_FOR_THE_GOAL = "You don't know their goal\nyet, so ask ONE specific question"


def test_the_day_zero_hello_offers_a_first_deliverable_when_the_goal_is_known() -> None:
    prompt = build_day_zero_hello_prompt(first_name="Priya", goal_block=_GOAL, has_goal=True)

    assert "Say hi to Priya by name" in prompt
    assert _OFFERS_A_DELIVERABLE in prompt
    assert "NEVER promise finished work" in prompt
    assert _ASKS_FOR_THE_GOAL not in prompt


def test_the_day_zero_hello_asks_for_the_goal_when_none_is_known() -> None:
    prompt = build_day_zero_hello_prompt(
        first_name="Priya", goal_block="(nothing yet)", has_goal=False
    )

    assert "Say hi to Priya by name" in prompt
    assert _ASKS_FOR_THE_GOAL in prompt
    assert _OFFERS_A_DELIVERABLE not in prompt
