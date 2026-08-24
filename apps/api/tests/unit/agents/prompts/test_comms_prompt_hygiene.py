"""The shipped prompts must not model the tells they ban.

A prompt is a style sample before it is a rulebook. Every em dash, every
"not X, it's Y" and every "here's the thing" sitting in the prompt's own prose
is a few-shot example of the exact thing the rules forbid, and the model copies
what it reads over what it is told. Production replies proved it: 25 negation
antitheses and 16 mirror forms across 42 turns, under a prompt that banned the
construction in one line and then used it five times.

The one exception is the banned-literals line, which cannot ban a literal
without naming it. Everything outside that line is prose the model imitates.
"""

import pytest

from app.agents.prompts.comms_prompts import BANNED_LITERALS_LINE_PREFIX
from app.agents.templates.agent_template import (
    COMMS_PROMPT_BY_SOURCE,
    EXECUTOR_PROMPT_TEMPLATE,
)

EM_DASH = "—"
EN_DASH = "–"

#: Messaging channels whose replies are delivered as separate chat messages.
MESSAGING_SOURCES = ("whatsapp", "telegram", "discord", "slack")

#: Literal spellings of the negation-antithesis. These may not appear anywhere,
#: not even as a "bad example" — a negative few-shot still puts the string in
#: context, and the model reaches for what is in context.
NEGATION_ANTITHESIS_SPELLINGS = (
    "isn't just",
    "isn’t just",
    "it's not a",
    "it’s not a",
    "not x, it's y",
    "but because",
)

#: Tells the prompt may name in its banned-literals line and nowhere else.
PROSE_BANNED_TELLS = ("here's the thing", "here’s the thing")

ALL_PROMPTS = {**COMMS_PROMPT_BY_SOURCE, "executor": EXECUTOR_PROMPT_TEMPLATE}


def prose_of(prompt: str) -> str:
    """The prompt minus the one line allowed to quote the literals it bans."""
    return "\n".join(
        line
        for line in prompt.splitlines()
        if not line.lstrip().startswith(BANNED_LITERALS_LINE_PREFIX)
    )


@pytest.mark.parametrize("source", sorted(ALL_PROMPTS))
def test_prompt_prose_has_no_dashes(source: str) -> None:
    prose = prose_of(ALL_PROMPTS[source])
    offenders = [line for line in prose.splitlines() if EM_DASH in line or EN_DASH in line]
    assert not offenders, (
        f"{source} prompt uses {len(offenders)} dash line(s) it forbids, first: {offenders[0]!r}"
    )


@pytest.mark.parametrize("source", sorted(ALL_PROMPTS))
def test_prompt_never_spells_out_the_negation_antithesis(source: str) -> None:
    lowered = ALL_PROMPTS[source].lower()
    found = [s for s in NEGATION_ANTITHESIS_SPELLINGS if s in lowered]
    assert not found, f"{source} prompt spells out the construction it bans: {found}"


@pytest.mark.parametrize("source", sorted(ALL_PROMPTS))
def test_prompt_prose_has_no_banned_tells(source: str) -> None:
    lowered = prose_of(ALL_PROMPTS[source]).lower()
    found = [tell for tell in PROSE_BANNED_TELLS if tell in lowered]
    assert not found, f"{source} prompt prose uses tells it bans: {found}"


@pytest.mark.parametrize("source", MESSAGING_SOURCES)
def test_messaging_prompts_restate_the_bubble_rule_in_the_addendum(source: str) -> None:
    """The platform addendum is the last thing the model reads, so the bubble
    rule has to be there and not only 27k characters earlier."""
    addendum = COMMS_PROMPT_BY_SOURCE[source].split("Platform Context")[-1]
    assert "<NEW_MESSAGE_BREAK>" in addendum
    assert "bubble" in addendum.lower()
