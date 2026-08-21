"""Deterministic gates whose banned lists are READ OUT OF the prompt.

The failure these prevent is subtle: a gate can carry its own copy of the rule
("never say 'How can I help you'") and keep passing forever after someone edits
the prompt. So the interesting assertions here are not "the gate catches a
violation" — they are:

* :func:`test_a_new_banned_phrase_is_gated_with_no_eval_change` — add a phrase to
  the prompt, the gate covers it immediately;
* :func:`test_a_reworded_rule_raises_instead_of_checking_nothing` — reword the
  rule so the list can no longer be read out, and extraction fails loud rather
  than gating on an empty list and reporting green.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from scripts.evals.core import prompt_contracts
from scripts.evals.core.prompt_contracts import ClauseResolutionError
from scripts.evals.core.prompt_gates import (
    PROMPT_GATES,
    banned_bot_phrases,
    banned_dashes,
    banned_phrases,
    channel_tags,
    dash_discipline,
    internal_machinery,
    internal_tags,
    internal_terms,
)
from scripts.evals.core.types import CaseRun

EM_DASH = "—"
EN_DASH = "–"


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    """Every derived list is cached; a test that edits a prompt must not leak."""
    caches = (
        prompt_contracts.prompt_text,
        banned_phrases,
        banned_dashes,
        internal_terms,
        channel_tags,
    )
    for cache in caches:
        cache.cache_clear()
    yield
    for cache in caches:
        cache.cache_clear()


def _run(*messages: tuple[str, str]) -> CaseRun:
    return CaseRun(
        case_id="t",
        messages=[{"role": role, "content": content} for role, content in messages],
    )


def _edit(monkeypatch: pytest.MonkeyPatch, edit: Callable[[str], str]) -> None:
    real = prompt_contracts.prompt_text

    def edited(source: str) -> str:
        text = real(source)
        return edit(text) if source == "comms" else text

    monkeypatch.setattr(prompt_contracts, "prompt_text", edited)


# ---------------------------------------------------------------------------
# The lists really are derived
# ---------------------------------------------------------------------------


def test_banned_phrases_come_from_the_prompt_including_ones_that_wrap() -> None:
    """ "No problem at all" wraps across two lines in the prompt source.

    A naive extraction returns "No problem\\n  at all" and then never matches a
    real reply — the gate would look wired up and catch nothing.
    """
    phrases = banned_phrases()

    assert "no problem at all" in phrases
    assert "how can i help you" in phrases
    assert "i apologize for the confusion" in phrases
    assert not any("\n" in phrase for phrase in phrases)


def test_dashes_and_tags_come_from_the_prompt() -> None:
    assert set(banned_dashes()) == {EM_DASH, EN_DASH}
    assert set(channel_tags()) == {
        "<executor_result>",
        "<executor_error>",
        "<returned_to_frontend>",
    }


def test_internal_terms_drop_only_the_ordinary_english_ones() -> None:
    """The prompt quotes executor/agent/subagent/tool; two are unavoidable words."""
    terms = internal_terms()

    assert "executor" in terms
    assert "subagent" in terms
    assert "agent" not in terms
    assert "tool" not in terms


def test_a_new_banned_phrase_is_gated_with_no_eval_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole thesis, in one test: edit the prompt, the gate follows."""
    reply = "Happy to assist you today!"
    assert banned_bot_phrases(_run(("user", "hey"), ("assistant", reply)))[0] == 1.0

    _edit(
        monkeypatch,
        lambda text: text.replace(
            '"I\'ll carry that out right away"',
            '"I\'ll carry that out right away", "Happy to assist"',
        ),
    )
    banned_phrases.cache_clear()

    value, why = banned_bot_phrases(_run(("user", "hey"), ("assistant", reply)))

    assert value == 0.0, "a phrase added to the prompt was not picked up by the gate"
    assert "happy to assist" in why


def test_a_reworded_rule_raises_instead_of_checking_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reword the rule into prose: the gate must refuse to run.

    Returning an empty banned list here would be the worst outcome available —
    every case passes the gate, the report is green, and nothing is checked.

    Note the deliberate non-failure this pins by contrast: de-quoting ONE phrase
    is a legitimate prompt edit (that phrase is no longer banned) and flows
    through silently, which is the feature. Only losing the whole list is drift.
    """

    def dequote(text: str) -> str:
        start = text.index("- Banned phrases (they scream chatbot):")
        stop = text.index("- When the user is just chatting,")
        return text[:start] + text[start:stop].replace('"', "") + text[stop:]

    _edit(monkeypatch, dequote)
    banned_phrases.cache_clear()

    # The clause itself still resolves; only its INPUTS became unreadable, which
    # is exactly the case a resolution-only check would miss.
    assert prompt_contracts.resolve("comms.banned_bot_phrases")

    with pytest.raises(ClauseResolutionError, match="check nothing"):
        banned_bot_phrases(_run(("user", "hey"), ("assistant", "hi")))


def test_a_reworded_dash_rule_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _edit(
        monkeypatch,
        lambda text: text.replace(
            "- NEVER use em dashes (—) or en dashes (–) anywhere in your output, ever.",
            "- NEVER use em dashes or en dashes anywhere in your output, ever.",
        ),
    )
    banned_dashes.cache_clear()

    with pytest.raises(ClauseResolutionError, match="check nothing"):
        dash_discipline(_run(("user", "hey"), ("assistant", "hi")))


# ---------------------------------------------------------------------------
# The gates catch real violations, and only real ones
# ---------------------------------------------------------------------------


def test_dash_discipline_catches_an_em_dash() -> None:
    value, why = dash_discipline(
        _run(("user", "how'd it go"), ("assistant", f"went fine {EM_DASH} better than expected"))
    )

    assert value == 0.0
    assert EM_DASH in why


def test_dash_discipline_catches_an_en_dash() -> None:
    value, _ = dash_discipline(_run(("user", "when"), ("assistant", f"tue{EN_DASH}thu works")))

    assert value == 0.0


def test_dash_discipline_passes_ordinary_punctuation() -> None:
    """Mutation guard: hyphens, commas and parentheses are not banned."""
    for reply in ("went fine, better than expected", "tue-thu works (i think)", "yeah: all good"):
        value, why = dash_discipline(_run(("user", "x"), ("assistant", reply)))
        assert value == 1.0, f"{reply!r} was wrongly flagged: {why}"


def test_dash_discipline_grades_the_assistant_not_the_user() -> None:
    """The user may write however they like; only the reply is under contract."""
    value, _ = dash_discipline(
        _run(("user", f"the meeting {EM_DASH} did it move?"), ("assistant", "yep, 3pm now"))
    )

    assert value == 1.0


def test_banned_bot_phrases_catches_the_phrase_however_it_is_cased_and_spaced() -> None:
    value, why = banned_bot_phrases(
        _run(("user", "thanks"), ("assistant", "No problem   at all!\nIs there anything else?"))
    )

    assert value == 0.0
    assert "no problem at all" in why


def test_banned_bot_phrases_passes_a_human_reply() -> None:
    value, why = banned_bot_phrases(_run(("user", "thanks"), ("assistant", "np, got u")))

    assert value == 1.0, why


def test_internal_machinery_catches_the_tool_name_and_the_word() -> None:
    for reply in ("lemme fire off call_executor for that", "the Executor is handling it"):
        value, why = internal_machinery(_run(("user", "check my cal"), ("assistant", reply)))
        assert value == 0.0, f"{reply!r} slipped past"
        assert "executor" in why


def test_internal_machinery_does_not_fire_on_ordinary_words() -> None:
    """Mutation guard: 'tool' and 'agent' are deliberately not gated."""
    for reply in ("that's the right tool for the job", "your travel agent emailed back"):
        value, why = internal_machinery(_run(("user", "x"), ("assistant", reply)))
        assert value == 1.0, f"{reply!r} was wrongly flagged: {why}"


def test_internal_tags_catches_a_leaked_channel_tag() -> None:
    value, why = internal_tags(
        _run(("user", "any mail?"), ("assistant", "<executor_result> you have 3 unread"))
    )

    assert value == 0.0
    assert "<executor_result>" in why


def test_internal_tags_catches_a_leaked_closing_tag() -> None:
    """A model that echoes only the closing tag has still leaked the plumbing —
    the opening-tag-only check this replaces scored that reply a clean 1.0."""
    value, why = internal_tags(
        _run(("user", "any mail?"), ("assistant", "you have 3 unread</executor_result>"))
    )

    assert value == 0.0
    assert "<executor_result>" in why


def test_internal_tags_passes_a_clean_reply() -> None:
    value, why = internal_tags(
        _run(("user", "any mail?"), ("assistant", "3 unread, all newsletters"))
    )

    assert value == 1.0, why


def test_gates_read_run_text_when_there_is_no_transcript() -> None:
    """Transports that record only ``text`` must still be graded."""
    run = CaseRun(case_id="t", text=f"sure {EM_DASH} on it")

    assert dash_discipline(run)[0] == 0.0


def test_every_registered_gate_runs_and_scores_a_clean_reply() -> None:
    clean = _run(("user", "hey"), ("assistant", "yo, what's good"))

    for name, gate in PROMPT_GATES.items():
        value, why = gate(clean)
        assert value == 1.0, f"{name} wrongly failed a clean reply: {why}"
        assert why
