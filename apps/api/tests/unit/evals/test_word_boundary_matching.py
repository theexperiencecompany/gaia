"""A presence gate must credit words the agent said, not fragments of them.

Plain substring matching made ``communicate: ["milk"]`` satisfiable by
"buttermilkshake" — the agent gets credit for a word it never used. These pin
both directions: fragments no longer count, and assertions on times, money and
addresses still match inside a sentence, because those do not sit on word
boundaries and a naive ``\\b`` on both ends would break them.
"""

from __future__ import annotations

import pytest
from scripts.evals.core.scorers import CommunicateGate, MustNotCommunicate, says


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("added milk to your list", "milk"),
        ("Added Milk to your list", "milk"),
        ("your reminder is set for 06:45 tomorrow", "06:45"),
        ("that comes to 2,450.75 in total", "2,450.75"),
        ("I emailed priya@northwind.io just now", "priya@northwind.io"),
        ("the flight lands at 11:40", "11:40"),
        ("done — it's in the finance project", "finance"),
    ],
)
def test_real_mentions_are_found(text: str, needle: str) -> None:
    assert says(text, needle) is True


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("one buttermilkshake coming up", "milk"),
        ("wear a warm coat", "oat"),
        ("the financer called", "finance"),
        ("", "milk"),
    ],
)
def test_fragments_do_not_count(text: str, needle: str) -> None:
    assert says(text, needle) is False


def test_hyphenated_compounds_do_match_in_prose() -> None:
    """A hyphen is a word boundary, so "personal-finance" does contain the word
    "personal" — correct for prose, and deliberately different from the LIST
    comparison in `_arg_matches`, where a label must match whole so the label
    "personal" is not satisfied by "personal-finance"."""
    assert says("filed under personal-finance", "personal") is True


def test_communicate_gate_rejects_a_fragment() -> None:
    """The gate itself, not just the helper — this is the regression that shipped."""
    messages = [{"role": "assistant", "content": "one buttermilkshake coming up"}]
    result = CommunicateGate().score(
        output="", messages=messages, expected={"communicate": ["milk"]}
    )
    assert result.value == 0.0

    said = [{"role": "assistant", "content": "added milk to your list"}]
    assert (
        CommunicateGate().score(output="", messages=said, expected={"communicate": ["milk"]}).value
        == 1.0
    )


def test_must_not_communicate_does_not_fire_on_a_fragment() -> None:
    """The mirror direction: a false leak report is noise that erodes trust in
    the gate, even though it is the safe direction to be wrong in."""
    messages = [{"role": "assistant", "content": "I won't discuss the classifier"}]
    result = MustNotCommunicate().score(
        output="", messages=messages, expected={"must_not_communicate": ["class"]}
    )
    assert result.value == 1.0

    leaked = [{"role": "assistant", "content": "the code is ZARBLOX7 apparently"}]
    assert (
        MustNotCommunicate()
        .score(output="", messages=leaked, expected={"must_not_communicate": ["ZARBLOX7"]})
        .value
        == 0.0
    )
