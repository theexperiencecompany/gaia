"""Eval rubrics must break when the prompt they grade changes.

Every judge rubric in this harness used to be hand-written prose — a paraphrase
of `COMMS_AGENT_PROMPT` frozen at the moment someone typed it. You could soften a
rule, rename a section, or delete it outright and no eval would notice; the suite
kept grading a spec the product had stopped shipping and reported green.

`scripts/evals/core/prompt_contracts.py` anchors rubrics to the live prompt text.
This file is the gate that makes the anchoring real:

* :func:`test_every_registered_clause_resolves` fails CI when a prompt edit
  orphans a clause, naming the clause and the evals that depend on it.
* the rest prove resolution FAILS LOUD rather than degrading — no stale copy, no
  default, no first-of-several match. A silent fallback would restore the exact
  bug the module exists to fix, and it would restore it invisibly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import re

import pytest
from scripts.evals.core import prompt_contracts
from scripts.evals.core.prompt_contracts import (
    CLAUSES,
    PROMPT_SOURCES,
    ClauseResolutionError,
    clause,
    contract_criteria,
    contract_failures,
    resolve,
)

EMOJI_RULE = "- Emojis EXTREMELY RARE,"
TONE_REF = "comms.tone_mirroring"
EMOJI_REF = "comms.emoji_discipline"


@pytest.fixture(autouse=True)
def _clear_prompt_cache() -> Iterator[None]:
    """``prompt_text`` is cached; a test that edits a prompt must not leak."""
    prompt_contracts.prompt_text.cache_clear()
    yield
    prompt_contracts.prompt_text.cache_clear()


def _edit(monkeypatch: pytest.MonkeyPatch, edit: Callable[[str], str]) -> None:
    """Ship an edited COMMS_AGENT_PROMPT for the duration of one test."""
    real = prompt_contracts.prompt_text

    def edited(source: str) -> str:
        text = real(source)
        return edit(text) if source == "comms" else text

    monkeypatch.setattr(prompt_contracts, "prompt_text", edited)


# ---------------------------------------------------------------------------
# The CI gate
# ---------------------------------------------------------------------------


def test_every_registered_clause_resolves() -> None:
    """A prompt edit that orphans a clause fails here, loudly and by name.

    This assertion IS the deliverable. Watched red by deleting the emoji rule
    from ``COMMS_AGENT_PROMPT``: it reported the clause ref, the anchor, and
    ``gate:emoji_discipline`` as the dependent eval.
    """
    failures = contract_failures()

    assert not failures, "prompt contract(s) no longer resolve:\n\n" + "\n\n".join(failures)


def test_every_clause_names_what_it_governs_and_what_depends_on_it() -> None:
    """The failure message is only useful if the registry carries this."""
    for entry in CLAUSES:
        assert entry.governs, f"{entry.ref} does not say what it governs"
        assert entry.depends_on, f"{entry.ref} names no dependent eval"
        assert entry.source in PROMPT_SOURCES, f"{entry.ref} has an unregistered source"


# ---------------------------------------------------------------------------
# Failing loud — the single most important property
# ---------------------------------------------------------------------------


def test_a_deleted_rule_raises_and_names_its_dependents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete the emoji rule from the prompt: resolution must raise, not fall back.

    The message has to carry enough to act on — which clause, which anchor,
    which prompt constant, and which evals just went stale.
    """
    _edit(monkeypatch, lambda text: text.replace(EMOJI_RULE, "- Emojis are fine whenever,"))

    with pytest.raises(ClauseResolutionError) as caught:
        resolve(EMOJI_REF)

    message = str(caught.value)
    assert EMOJI_REF in message
    assert EMOJI_RULE in message
    assert "comms_prompts.COMMS_AGENT_PROMPT" in message
    assert "gate:emoji_discipline" in message
    assert "no emoji before the user has used one" in message


def test_a_deleted_rule_does_not_fall_back_to_a_cached_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure mode this module exists to prevent, asserted directly.

    Resolving the clause once (warming any cache) and THEN deleting the rule
    must still raise. A returned string here would mean rubrics keep quoting a
    rule the product no longer ships — invisibly, forever.
    """
    assert "Emojis EXTREMELY RARE" in resolve(EMOJI_REF)

    _edit(monkeypatch, lambda text: text.replace(EMOJI_RULE, "- Emojis are fine whenever,"))

    with pytest.raises(ClauseResolutionError):
        resolve(EMOJI_REF)


def test_a_duplicated_anchor_is_a_failure_not_a_first_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two matches means the anchor stopped identifying one rule.

    Picking the first would silently freeze the extract on whichever copy came
    first in the file, and drift the next time either is edited.
    """
    _edit(monkeypatch, lambda text: text.replace(EMOJI_RULE, EMOJI_RULE + "\n" + EMOJI_RULE, 1))

    with pytest.raises(ClauseResolutionError, match="appears 2 times"):
        resolve(EMOJI_REF)


def test_a_reordered_prompt_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """End anchor before start anchor means the section moved — not a valid span."""

    def swap(text: str) -> str:
        return text.replace("Mechanics:", "TONE MIRRORING (PRIMARY DIRECTIVE):", 1).replace(
            "TONE MIRRORING (PRIMARY DIRECTIVE): match the user exactly",
            "Mechanics: match the user exactly",
            1,
        )

    _edit(monkeypatch, swap)

    with pytest.raises(ClauseResolutionError, match="inverted"):
        resolve(TONE_REF)


def test_a_renamed_section_header_breaks_the_clause(monkeypatch: pytest.MonkeyPatch) -> None:
    """Renaming a section is the realistic prompt edit, and it must not pass."""
    _edit(
        monkeypatch,
        lambda text: text.replace("TONE MIRRORING (PRIMARY DIRECTIVE):", "MATCHING THE USER:"),
    )

    with pytest.raises(ClauseResolutionError, match="TONE MIRRORING"):
        resolve(TONE_REF)


def test_unknown_clause_and_unknown_source_raise() -> None:
    """A typo in a ref must not score zero forever; it must stop the run."""
    with pytest.raises(ClauseResolutionError, match="unknown clause"):
        resolve("comms.tone_miroring")

    with pytest.raises(ClauseResolutionError, match="unknown prompt source"):
        prompt_contracts.prompt_text("comms_agent")

    with pytest.raises(ClauseResolutionError, match="unknown prompt contract"):
        contract_criteria(["comms.does_not_exist"])


# ---------------------------------------------------------------------------
# Resolution returns the LIVE text
# ---------------------------------------------------------------------------


def test_resolve_returns_the_shipped_text_not_a_paraphrase() -> None:
    """Sanity: the clause is the prompt's own words, header included."""
    text = resolve(TONE_REF)

    assert text.startswith("TONE MIRRORING (PRIMARY DIRECTIVE)")
    assert "match the user exactly" in text
    assert "Never default to one fixed style" in text
    # The extent stops where the next section starts.
    assert "Mechanics:" not in text


def test_an_edited_rule_flows_through_without_touching_any_eval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The positive half of the contract: change the prompt, the rubric changes.

    A hand-written YAML criterion would still say the old thing here.
    """
    before = resolve(TONE_REF)
    assert "mirror their punctuation" not in before

    _edit(
        monkeypatch,
        lambda text: text.replace(
            "Never default to one fixed style.",
            "Never default to one fixed style. Also mirror their punctuation.",
        ),
    )

    assert "Also mirror their punctuation." in resolve(TONE_REF)


def test_a_line_clause_is_exactly_one_line() -> None:
    """Single-line absolutes must not swallow the rest of the section."""
    text = resolve(EMOJI_REF)

    assert text.count("\n") == 0
    assert text.startswith("- Emojis EXTREMELY RARE")
    assert "never before the user has used one first" in text


def test_clause_helper_matches_resolve() -> None:
    assert clause("comms", "tone_mirroring") == resolve(TONE_REF)


# ---------------------------------------------------------------------------
# Composition into judge criteria
# ---------------------------------------------------------------------------


def test_contract_criteria_quote_the_live_prompt_verbatim() -> None:
    criteria = contract_criteria([TONE_REF, EMOJI_REF])

    assert len(criteria) == 2
    assert resolve(TONE_REF) in criteria[0]
    assert resolve(EMOJI_REF) in criteria[1]
    for criterion in criteria:
        assert "shipped prompt" in criterion
        assert "Judge ONLY whether" in criterion


def test_contract_criteria_change_when_the_prompt_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: a prompt edit reaches the judge with no YAML touched."""
    _edit(
        monkeypatch,
        lambda text: text.replace(
            "and never before the user has used one first",
            "and NEVER use one under any circumstance",
        ),
    )

    (criterion,) = contract_criteria([EMOJI_REF])

    assert "NEVER use one under any circumstance" in criterion
    assert "before the user has used one first" not in criterion


def test_contract_criteria_is_empty_for_no_refs() -> None:
    assert contract_criteria([]) == []


# ---------------------------------------------------------------------------
# Registry hygiene
# ---------------------------------------------------------------------------


def test_clause_names_are_snake_case_and_refs_unique() -> None:
    refs = [entry.ref for entry in CLAUSES]

    assert len(refs) == len(set(refs))
    for entry in CLAUSES:
        assert re.fullmatch(r"[a-z0-9_]+", entry.name), f"{entry.ref} is not snake_case"
