"""A multi-turn quality case must actually send every turn.

Regression cover for a silent data-shape bug: ``QualitySuite.load_cases`` built
each ``Case`` with ``setup=row`` — the whole leftover YAML row — so a case
written with a ``setup:`` block landed at ``case.setup["setup"]["turns"]`` while
``ChatStreamTransport`` read ``case.setup["turns"]``. The lookup missed, the
transport fell back to splitting ``prompt``, and every ``setup.turns`` case ran
turn 1 only.

Nothing failed loudly. ``quality-hard-correction-loop`` gates on
``communicate: ["plumber"]`` but the plumber turn was never sent, so the gate
could only ever go red — the harness was reporting an agent failure for a
conversation the agent was never given. ``quality-hard-deep-session`` graded
three-turn coherence rubrics against a single turn.
"""

from __future__ import annotations

from scripts.evals.core.providers import EvalConfig
from scripts.evals.core.types import Case
from scripts.evals.suites.quality import DATA_DIR, QualitySuite, turns_for
import yaml

# The two cases in data/quality/hard.yaml that declare turns via `setup:`.
CORRECTION_LOOP = "quality-hard-correction-loop"
DEEP_SESSION = "quality-hard-deep-session"


def _config() -> EvalConfig:
    """QualitySuite ignores cfg entirely (both __init__ and load_cases `del` it);
    this exists only to satisfy the signature."""
    return EvalConfig(
        providers={},
        rotation_order=[],
        default_max_usd=0.0,
        judge={"base_url_env": "X", "api_key_env": "Y"},
    )


def _quality_cases() -> dict[str, Case]:
    cfg = _config()
    return {c.id: c for c in QualitySuite(cfg).load_cases(cfg)}


def _declared_turn_counts() -> dict[str, int]:
    """Turn counts as the YAML author wrote them, read straight off disk.

    Deliberately independent of ``Case``/``load_cases`` — the bug lived in that
    translation, so the expectation cannot be sourced from it.
    """
    declared: dict[str, int] = {}
    for path in sorted(DATA_DIR.glob("*.yaml")):
        for row in yaml.safe_load(path.read_text(encoding="utf-8")):
            turns = (row.get("setup") or {}).get("turns")
            if turns:
                declared[row["id"]] = len(turns)
    return declared


def test_setup_turns_reach_the_transport() -> None:
    """A `setup.turns` case sends all of its turns, not just the first."""
    turns = turns_for(_quality_cases()[CORRECTION_LOOP])

    assert len(turns) == 2, f"{CORRECTION_LOOP} sends {len(turns)} turn(s): {turns}"
    assert "vet" in turns[0]
    assert "plumber" in turns[1], "the correction turn never reaches the agent"


def test_deep_session_sends_all_three_turns() -> None:
    """Three-turn coherence rubrics need three turns to grade."""
    turns = turns_for(_quality_cases()[DEEP_SESSION])

    assert len(turns) == 3, f"{DEEP_SESSION} sends {len(turns)} turn(s): {turns}"
    assert "pasta" in turns[1]
    assert "day before" in turns[2].lower()


def test_every_declared_turn_is_sent() -> None:
    """The general form: no case may silently drop turns its YAML declares.

    This is what the bug actually was — a case declaring N turns running as 1 —
    and it catches the next case authored in the `setup:` form too.
    """
    cases = _quality_cases()
    dropped = {
        case_id: (declared, len(turns_for(cases[case_id])))
        for case_id, declared in _declared_turn_counts().items()
        if len(turns_for(cases[case_id])) != declared
    }
    assert not dropped, (
        f"cases sending fewer turns than declared {{id: (declared, sent)}}: {dropped}"
    )


def test_prompt_separator_cases_still_split() -> None:
    """Mutation guard: the `---` form must keep working after the fix."""
    turns = turns_for(_quality_cases()["quality-mt-elliptical-followups"])

    assert turns == [
        "what's the capital of australia",
        "and new zealand",
        "and canada",
    ]


def test_single_turn_case_is_one_turn() -> None:
    """Mutation guard: an ordinary case must not gain phantom turns."""
    assert turns_for(_quality_cases()["quality-everyday-greeting"]) == ["hey! what's up?"]
