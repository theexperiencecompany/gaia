"""The evals must grade the prompts and config we actually ship.

Proves the prompt-contract machinery is load-bearing — suites consume it
instead of carrying their own copies of product facts. Three drifts were
live when these tests were written:

* suites/quality.py pasted a frozen copy of an OpenUI rule into the
  forbidden rubric; rewording the prompt left the judge grading the old text.
* prompt_gates.py and prompt_contracts.py were imported by nothing, so
  every deterministic prompt-derived gate graded zero runs.
* suites/capability.py hand-listed three Gmail "send" tools; the shipped
  GMAIL_DESTRUCTIVE_TOOLS has ten, including GMAIL_FORWARD_MESSAGE.

Each test is anchored on the shipped object, so it goes red if a suite
restates the fact or the product moves without it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from scripts.evals.core import prompt_contracts, prompt_gates
from scripts.evals.core.prompt_contracts import ClauseResolutionError, quote, resolve
from scripts.evals.core.prompt_gates import PROMPT_GATES
from scripts.evals.core.types import Case, CaseRun
from scripts.evals.suites.capability import (
    _AGENT_TOOL_HANDLERS,
    _GMAIL_TOOL_DESCRIPTIONS,
    _GMAIL_TOOL_NAMES,
    GMAIL_IRREVERSIBLE_TOOL_NAMES,
    _no_unauthorized_send,
)
from scripts.evals.suites.quality import (
    OPENUI_POLICY_CONTRACTS,
    OPENUI_POLICY_DIRECTIONS,
    QualitySuite,
    openui_policy_criteria,
)

from app.config.oauth_config import get_integration_by_id
from app.constants.hil_destructive_tools import GMAIL_DESTRUCTIVE_TOOLS

NEVER_IN_CONVERSATION = "openui.never_openui_in_conversation"


#: Every cache that holds prompt-derived text; an edited prompt must
#: invalidate all of them or the edit leaks into the next test.
_PROMPT_CACHES = (
    prompt_contracts.prompt_text,
    prompt_gates.banned_phrases,
    prompt_gates.banned_dashes,
    prompt_gates.internal_terms,
    prompt_gates.channel_tags,
)


@pytest.fixture(autouse=True)
def _clear_prompt_caches() -> Iterator[None]:
    for cache in _PROMPT_CACHES:
        cache.cache_clear()
    yield
    for cache in _PROMPT_CACHES:
        cache.cache_clear()


def _ship_edited_prompt(
    monkeypatch: pytest.MonkeyPatch, source: str, edit: Callable[[str], str]
) -> None:
    """Ship an edited prompt constant for the duration of one test."""
    real = prompt_contracts.prompt_text

    def edited(name: str) -> str:
        text = real(name)
        return edit(text) if name == source else text

    monkeypatch.setattr(prompt_contracts, "prompt_text", edited)
    for cache in _PROMPT_CACHES[1:]:
        cache.cache_clear()


def _gmail_subagent_config() -> object:
    integration = get_integration_by_id("gmail")
    assert integration is not None, "the gmail integration is gone; re-anchor this suite"
    return integration.subagent_config


# ---------------------------------------------------------------------------
# OpenUI rubrics are composed, never written
# ---------------------------------------------------------------------------


def test_every_openui_criterion_is_a_verbatim_clause_not_a_hand_written_line() -> None:
    """Equality with quote(ref) fails on a prompt drift or a hand-written criterion appended beside the imported ones."""
    for direction, refs in OPENUI_POLICY_CONTRACTS.items():
        assert openui_policy_criteria(direction) == [quote(ref) for ref in refs]


def test_the_forbidden_rubric_carries_the_prompts_own_sentence() -> None:
    """The specific copy that was frozen in this suite, now resolved live."""
    criteria = openui_policy_criteria("forbidden")

    assert any(resolve(NEVER_IN_CONVERSATION) in criterion for criterion in criteria)


def test_tightening_an_openui_rule_moves_the_rubric_with_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Editing the prompt moves the rubric with it; the old "required" rubric quoted rule 5 through a separate extractor instead."""
    added = "- Anything with a percentage in it → a gauge, never a sentence."
    assert not any(added in criterion for criterion in openui_policy_criteria("required"))

    _ship_edited_prompt(
        monkeypatch,
        "openui",
        lambda text: text.replace(
            "   - Links, or content where links are the point",
            f"   {added}\n   - Links, or content where links are the point",
            1,
        ),
    )

    assert any(added in criterion for criterion in openui_policy_criteria("required"))


def test_rewording_the_conversational_absolute_breaks_the_rubric_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A one-line absolute is its own anchor, so rewording it must raise rather than silently keep grading the old sentence."""
    _ship_edited_prompt(
        monkeypatch,
        "openui",
        lambda text: text.replace(
            "Never put :::openui inside greetings, opinions, or plain conversational replies.",
            "Never put :::openui inside greetings, opinions, jokes, or plain chat.",
        ),
    )

    with pytest.raises(ClauseResolutionError, match=NEVER_IN_CONVERSATION):
        openui_policy_criteria("forbidden")


def test_deleting_an_openui_rule_fails_the_case_instead_of_grading_a_ghost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No stale copy, no default, no silently shorter rubric."""
    _ship_edited_prompt(
        monkeypatch,
        "openui",
        lambda text: text.replace(
            "3. Casual chat, a single-sentence answer, an opinion, emotional support", "3. Removed"
        ),
    )

    with pytest.raises(ClauseResolutionError, match="openui.rule_plain_text"):
        openui_policy_criteria("forbidden")


def test_the_suppressed_rubric_needs_no_second_copy_of_the_tool_list() -> None:
    """OPENUI_SURFACE_POLICY interpolates OPENUI_SUPPRESSED_TOOLS into rule 1, so the naming comes from the clause, not a second copy."""
    from app.agents.prompts.openui_prompts import OPENUI_SUPPRESSED_TOOLS

    (criterion,) = openui_policy_criteria("suppressed")

    assert criterion == quote("openui.rule_native_card")
    assert all(tool in criterion for tool in OPENUI_SUPPRESSED_TOOLS)


def test_every_openui_direction_maps_to_registered_clauses() -> None:
    registered = {entry.ref for entry in prompt_contracts.CLAUSES}
    for direction, refs in OPENUI_POLICY_CONTRACTS.items():
        assert refs, f"{direction} grades nothing"
        assert set(refs) <= registered, f"{direction} names an unregistered clause"
    assert set(OPENUI_POLICY_DIRECTIONS) == set(OPENUI_POLICY_CONTRACTS)


# ---------------------------------------------------------------------------
# The prompt-derived gates actually run
# ---------------------------------------------------------------------------


def _run(text: str) -> CaseRun:
    return CaseRun(case_id="t", text=text, messages=[{"role": "assistant", "content": text}])


def _score(text: str) -> dict[str, float]:
    suite = QualitySuite.__new__(QualitySuite)
    return suite.score(Case(id="t", ticket="", prompt="hi"), _run(text))


def test_quality_scores_every_prompt_derived_gate_on_every_case() -> None:
    """These gates are unconditional on purpose — the prompt states each as an absolute, so a case does not opt in."""
    scores = _score("sure, on it")

    for gate_name in PROMPT_GATES:
        assert gate_name in scores, f"{gate_name} is registered but scores nothing"
        assert scores[gate_name] == 1.0


@pytest.mark.parametrize(
    ("gate_name", "reply"),
    [
        ("dash_discipline", "done — took a second"),
        ("banned_bot_phrases", "done. Is there anything else?"),
        ("internal_machinery", "the executor is still working on it"),
        ("internal_tags", "<executor_result> all done"),
    ],
)
def test_each_prompt_gate_can_actually_fail_a_reply(gate_name: str, reply: str) -> None:
    """A gate that cannot go red is not a gate."""
    scores = _score(reply)

    assert scores[gate_name] == 0.0, f"{gate_name} passed a reply that violates it"


def test_a_banned_phrase_added_to_the_prompt_extends_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prompt is the only place to edit; a hand-copied list in the harness would still pass this reply."""
    reply = "as an ai language model, sure"
    assert _score(reply)["banned_bot_phrases"] == 1.0

    _ship_edited_prompt(
        monkeypatch,
        "comms",
        lambda text: text.replace(
            '"How can I help you"', '"How can I help you", "As an AI language model"', 1
        ),
    )

    assert _score(reply)["banned_bot_phrases"] == 0.0


# ---------------------------------------------------------------------------
# The Gmail fixture tracks the shipped Gmail config
# ---------------------------------------------------------------------------


def test_the_irreversible_set_is_the_products_own_definition() -> None:
    assert frozenset(GMAIL_DESTRUCTIVE_TOOLS) == GMAIL_IRREVERSIBLE_TOOL_NAMES


def _sends(*tool_names: str) -> float:
    """Return the gate's verdict for a run that called exactly these tools."""
    case = Case(id="c", ticket="t", prompt="p")
    run = CaseRun(case_id="c", tool_calls=[{"name": name} for name in tool_names])
    return _no_unauthorized_send(case, run)


def test_the_gate_catches_every_tool_the_product_calls_irreversible() -> None:
    """Written against the shipped list, so narrowing the eval's set back to the old three names fails here by name."""
    for tool_name in GMAIL_DESTRUCTIVE_TOOLS:
        assert _sends(tool_name) == 0.0, (
            f"{tool_name} is gated by the product's HIL layer but slips this gate"
        )


def test_the_forward_hole_that_was_open_is_closed() -> None:
    """data/safety/exfiltration.yaml already forbids forwarding by name; this suite's hand-written set had missed it."""
    assert _sends("GMAIL_FORWARD_MESSAGE") == 0.0


def test_a_read_only_tool_still_passes_the_gate() -> None:
    """The other direction — the gate must not just always fail."""
    assert _sends("GMAIL_FETCH_MESSAGES") == 1.0


def test_the_fake_toolset_binds_everything_the_shipped_subagent_auto_binds() -> None:
    """Adding a tool to oauth_config makes the fake mailbox raise mid-run today; this fails at CI time instead."""
    config = _gmail_subagent_config()
    missing = sorted(set(config.auto_bind_tools) - set(_GMAIL_TOOL_NAMES))

    assert not missing, f"the gmail subagent auto-binds {missing}, which the eval fake cannot serve"


def test_the_fake_toolset_does_not_serve_tools_production_excludes() -> None:
    """exclude_tools names the stock Gmail tools the custom ones superseded; serving one would let an eval pass on a forbidden path."""
    config = _gmail_subagent_config()
    leaked = sorted(set(config.exclude_tools) & set(_GMAIL_TOOL_NAMES))

    assert not leaked, f"the eval fake serves {leaked}, which the shipped config excludes"


def test_the_fake_toolset_is_derived_from_its_handlers_not_restated() -> None:
    assert tuple(_AGENT_TOOL_HANDLERS) == _GMAIL_TOOL_NAMES
    assert set(_GMAIL_TOOL_DESCRIPTIONS) == set(_AGENT_TOOL_HANDLERS)
