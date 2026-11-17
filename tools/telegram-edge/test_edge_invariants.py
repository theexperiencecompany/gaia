"""Unit tests for the edge suite's invariants and scenario checks, on hand-built transcripts."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from edge_invariants import Budgets, check_invariants
from edge_scenarios import Scenario, check_expectations, load_scenarios, parse_scenario
from edge_transcript import BotMessage, ReactionState, SentMessage, TextState, Transcript

PROMPT_ONE = "Want me to add “x alpha” to your todos?\nPriority: none\n\nReply yes or no."


def bubble(mid: int, at: float, *texts: str, reply_to: int | None = None) -> BotMessage:
    return BotMessage(mid, at, reply_to, [TextState(at + i * 0.5, t) for i, t in enumerate(texts)])


def transcript(
    sent: list[SentMessage], bot: list[BotMessage], ended_at: float = 100.0
) -> Transcript:
    return Transcript("t", sent=sent, bot=bot, ended_at=ended_at)


def kinds(t: Transcript, budget: float = 20.0) -> list[str]:
    return [v.invariant for v in check_invariants(t, Budgets(first_response_s=budget))]


def test_clean_streamed_reply_passes() -> None:
    t = transcript([SentMessage(1, "hi", 0.0)], [bubble(2, 3.0, "Sun", "Sunday.")])
    assert kinds(t) == []


def test_unanswered_message_fails() -> None:
    t = transcript(
        [SentMessage(1, "hi", 0.0), SentMessage(3, "again", 50.0)], [bubble(2, 3.0, "ok")]
    )
    assert kinds(t) == ["answered"]


def test_reaction_alone_answers_a_message() -> None:
    t = transcript([SentMessage(1, "thanks", 0.0, [ReactionState(1.2, ("❤",))])], [])
    assert kinds(t) == []


def test_slow_first_response_breaks_the_budget() -> None:
    t = transcript([SentMessage(1, "hi", 0.0)], [bubble(2, 25.0, "late")])
    assert kinds(t) == ["latency"]


def test_edit_that_removes_shown_text_is_taken_back() -> None:
    t = transcript([SentMessage(1, "hi", 0.0)], [bubble(2, 1.0, "Saved the note to", "Saved")])
    assert kinds(t) == ["taken_back"]


def test_deleted_bubble_is_taken_back() -> None:
    gone = bubble(2, 1.0, "partial")
    gone.deleted_at = 4.0
    t = transcript([SentMessage(1, "hi", 0.0)], [gone])
    assert kinds(t) == ["taken_back"]


def test_stranded_partial_bubble_is_a_duplicate() -> None:
    t = transcript(
        [SentMessage(1, "guide", 0.0)],
        [bubble(2, 1.0, "1"), bubble(3, 9.0, "1) Equipment: get shoes")],
    )
    assert kinds(t) == ["duplicate"]


def test_identical_bubbles_are_duplicates() -> None:
    text = "Here is the whole answer to your question."
    t = transcript([SentMessage(1, "q", 0.0)], [bubble(2, 1.0, text), bubble(3, 2.0, text)])
    assert "duplicate" in kinds(t)


def test_long_line_repeated_in_another_bubble_is_a_duplicate() -> None:
    line = "Part 2 covers grind size, water ratio and brew time."
    t = transcript(
        [SentMessage(1, "q", 0.0)],
        [bubble(2, 1.0, f"Intro\n{line}"), bubble(3, 2.0, f"{line}\nMore")],
    )
    assert kinds(t) == ["duplicate"]


@pytest.mark.parametrize(
    "text",
    [
        ":::openui\nroot = Stack([title])\n:::",
        "Saved to /workspace/sessions/abc/artifacts/x.csv",
        "See [#3] above",
        "call_tbjLNDUgOfDTJp92mZs9cW8l failed",
        "[[say:hi]]",
    ],
)
def test_internals_in_any_shown_text_leak(text: str) -> None:
    t = transcript([SentMessage(1, "q", 0.0)], [bubble(2, 1.0, text, text + " and more")])
    assert kinds(t) == ["leak"]


@pytest.mark.parametrize(
    "text", ["the **best** one", "read [docs](https://x.org/a)", "## Heading", "<b>bold</b>"]
)
def test_unconverted_markdown_in_final_text_leaks(text: str) -> None:
    t = transcript([SentMessage(1, "q", 0.0)], [bubble(2, 1.0, text)])
    assert kinds(t) == ["leak"]


def test_half_written_bold_mid_stream_is_not_a_leak() -> None:
    t = transcript([SentMessage(1, "q", 0.0)], [bubble(2, 1.0, "the **be", "the best one")])
    assert "leak" not in kinds(t)


def test_bubble_after_stop_notice_fails() -> None:
    sent = [SentMessage(1, "research", 0.0), SentMessage(3, "/stop", 10.0)]
    bot = [
        bubble(2, 2.0, "On it"),
        bubble(4, 10.4, "Stopped."),
        bubble(5, 30.0, "Here is the research"),
    ]
    assert kinds(transcript(sent, bot)) == ["stop"]


def test_bubble_growing_after_stop_notice_fails() -> None:
    sent = [SentMessage(1, "research", 0.0), SentMessage(3, "/stop", 10.0)]
    growing = BotMessage(
        2, 2.0, None, [TextState(2.0, "Part"), TextState(20.0, "Part one and more")]
    )
    bot = [growing, bubble(4, 10.4, "Stopped.")]
    assert kinds(transcript(sent, bot)) == ["stop"]


def test_reply_to_a_message_after_stop_is_allowed() -> None:
    sent = [
        SentMessage(1, "research", 0.0),
        SentMessage(3, "/stop", 10.0),
        SentMessage(5, "7*8?", 50.0),
    ]
    bot = [bubble(2, 2.0, "On it"), bubble(4, 10.4, "Stopped."), bubble(6, 53.0, "56")]
    assert kinds(transcript(sent, bot)) == []


def test_approval_asked_twice_fails() -> None:
    first = "2 things need your OK:\n1. Add “x alpha”\n2. Add “x beta”\n\nReply yes to all"
    again = "One more needs your OK:\n2. Add “x beta”\n\nReply by number"
    t = transcript(
        [SentMessage(1, "two todos", 0.0)], [bubble(2, 5.0, first), bubble(3, 6.0, again)]
    )
    assert kinds(t, budget=30) == ["asked_twice"]


def test_reask_that_leads_with_the_change_is_not_asked_twice() -> None:
    again = "Updated priority to high, still OK to add it?\nPriority: high\n\nReply yes or no."
    sent = [SentMessage(1, "add", 0.0), SentMessage(3, "yes but high", 8.0)]
    t = transcript(sent, [bubble(2, 5.0, PROMPT_ONE), bubble(4, 10.0, again)])
    assert kinds(t) == []


def scenario(expect: list[dict[str, object]]) -> Scenario:
    return parse_scenario({"name": "s", "steps": [{"send": "x"}], "expect": expect}, "n1")


def test_every_repo_scenario_parses() -> None:
    names = [s.name for s in load_scenarios("n1")]
    assert len(names) == len(set(names)) > 0


def test_text_expectation_without_loose_reason_is_refused() -> None:
    with pytest.raises(ValueError, match="loose"):
        scenario([{"contains": {"after": 0, "pattern": "x"}}])


def test_unknown_step_is_refused() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        parse_scenario({"name": "s", "steps": [{"shout": "x"}]}, "n1")


def burst_transcript(*bot: BotMessage) -> Transcript:
    return transcript([SentMessage(1, "capital?", 0.0), SentMessage(2, "legs?", 0.2)], list(bot))


DISTINCT = [{"distinct_answers": ["canberra", "eight"], "loose": "facts"}]


def test_one_bubble_answering_both_is_distinct() -> None:
    t = burst_transcript(bubble(3, 4.0, "Canberra; eight."))
    assert check_expectations(scenario(DISTINCT), t, [], "n1") == []


def test_separate_answers_that_quote_their_questions_are_distinct() -> None:
    t = burst_transcript(
        bubble(3, 4.0, "Canberra.", reply_to=1), bubble(4, 5.0, "Eight.", reply_to=2)
    )
    assert check_expectations(scenario(DISTINCT), t, [], "n1") == []


def test_separate_unquoted_answers_are_not_distinct() -> None:
    t = burst_transcript(bubble(3, 4.0, "Canberra."), bubble(4, 5.0, "Eight."))
    found = check_expectations(scenario(DISTINCT), t, [], "n1")
    assert [v.invariant for v in found] == ["distinct_answers", "distinct_answers"]


def test_contains_within_window_uses_when_the_text_was_shown() -> None:
    exp = scenario(
        [{"contains": {"after": 0, "pattern": r"\b36\b", "within_s": 30}, "loose": "number"}]
    )
    late = transcript([SentMessage(1, "15% of 240?", 0.0)], [bubble(2, 40.0, "36.")])
    early = transcript([SentMessage(1, "15% of 240?", 0.0)], [bubble(2, 5.0, "36.")])
    assert [v.invariant for v in check_expectations(exp, late, [], "n1")] == ["contains"]
    assert check_expectations(exp, early, [], "n1") == []


def test_approval_numbers_follow_the_prompt_not_the_request_order() -> None:
    """Run 4 showed beta as the first prompt: "yes 1" must then create beta, not alpha."""
    exp = scenario(
        [{"approval_numbers": {"tags": ["alpha", "beta"], "decisions": {1: "yes", 2: "no"}}}]
    )
    beta_first = "Want me to add “n1 beta” to your todos?\n\nReply yes or no."
    alpha_second = "One more needs your OK:\n2. Add “n1 alpha”\n\nReply by number"
    t = transcript(
        [SentMessage(1, "two", 0.0)], [bubble(2, 5.0, beta_first), bubble(3, 6.0, alpha_second)]
    )
    assert check_expectations(exp, t, [{"title": "n1 beta"}], "n1") == []
    wrong = check_expectations(exp, t, [{"title": "n1 alpha"}], "n1")
    assert sorted(v.message for v in wrong) == [
        "expected one todo tagged beta, found 0",
        "todo tagged alpha exists though it was denied",
    ]


def test_todo_priority_is_checked() -> None:
    exp = scenario([{"todos": [{"tag": "amend", "exists": True, "priority": "high"}]}])
    t = transcript([SentMessage(1, "x", 0.0)], [])
    assert check_expectations(exp, t, [{"title": "n1 amend", "priority": "high"}], "n1") == []
    assert len(check_expectations(exp, t, [{"title": "n1 amend", "priority": "none"}], "n1")) == 1


def test_warn_severity_is_kept() -> None:
    exp = scenario([{"reaction": 0, "severity": "warn"}])
    found = check_expectations(exp, transcript([SentMessage(1, "thanks", 0.0)], []), [], "n1")
    assert [(v.invariant, v.severity) for v in found] == [("reaction", "warn")]
