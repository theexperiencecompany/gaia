"""The assistant must not emoji before the user does.

The comms prompt states it verbatim: "Emojis EXTREMELY RARE, and NEVER use one
before the user has used one first." It was judge-only coverage until a live
quality run produced this transcript, which passed every structural gate it had
because none of them could see the violation:

    user      | add a todo to water the plants
    assistant | aight, add kar raha hoon Inbox me 🌱ho gaya nahi abhi...

A deterministic rule graded by an LLM rubric is a rule that gets graded
inconsistently and costs a judge call. This pins it.
"""

from __future__ import annotations

from scripts.evals.core.types import CaseRun
from scripts.evals.suites.quality import _emoji_discipline_check


def _run(*messages: tuple[str, str]) -> CaseRun:
    return CaseRun(
        case_id="t",
        messages=[{"role": role, "content": content} for role, content in messages],
    )


def test_emoji_before_the_user_is_caught() -> None:
    """The live transcript that motivated the check."""
    value, reason = _emoji_discipline_check(
        _run(
            ("user", "add a todo to water the plants"),
            ("assistant", "aight, add kar raha hoon Inbox me \U0001f331ho gaya nahi abhi"),
        )
    )

    assert value == 0.0, f"live violation scored as clean: {reason}"
    assert "\U0001f331" in reason


def test_plain_text_reply_passes() -> None:
    """Mutation guard: an ordinary reply must not be flagged."""
    value, reason = _emoji_discipline_check(
        _run(
            ("user", "add a todo to water the plants"),
            ("assistant", "on it, adding that now"),
        )
    )

    assert value == 1.0, reason


def test_user_emoji_first_permits_the_reply_to_answer_in_kind() -> None:
    """The rule is ordering, not abstinence — mirroring the user is correct."""
    value, reason = _emoji_discipline_check(
        _run(("user", "\U0001f62d"), ("assistant", "oof \U0001f62d what happened"))
    )

    assert value == 1.0, reason


def test_ordering_is_respected_across_turns() -> None:
    """An emoji in turn 1's reply is a violation even if turn 2's user sends one."""
    value, _ = _emoji_discipline_check(
        _run(
            ("user", "hey"),
            ("assistant", "yo \U0001f44b"),
            ("user", "haha \U0001f602"),
            ("assistant", "\U0001f602 fr"),
        )
    )
    assert value == 0.0, "an emoji sent before the user's first was not caught"

    value, _ = _emoji_discipline_check(
        _run(
            ("user", "hey"),
            ("assistant", "yo"),
            ("user", "haha \U0001f602"),
            ("assistant", "\U0001f602 fr"),
        )
    )
    assert value == 1.0, "the reply was blocked from mirroring an emoji the user already used"


def test_ordinary_punctuation_is_not_an_emoji() -> None:
    """False positives would make the gate noise: these must all stay clean."""
    for text in ("we use ™ and © here", "step 1 → step 2", "✓ done", "a ± b", "100°C"):
        value, reason = _emoji_discipline_check(_run(("user", "x"), ("assistant", text)))
        assert value == 1.0, f"{text!r} was wrongly flagged as an emoji: {reason}"
