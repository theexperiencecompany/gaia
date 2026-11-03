"""Every write_playbook attempt prod made since 2026-09-01, replayed through the pick flow.

The fixtures are real attempts (anonymised by scripts/playbook_corpus), each
re-expressed as picks over its own run's record. The gate: an attempt the pick
flow can express is accepted, or refused only for something the author
explicitly asked for that no server could reinterpret (AUTHOR_CHOICE_REFUSALS).
An attempt that cannot be said as picks carries why, and the why is checked
against its record. A change that turns any accepted attempt into a refusal
fails here; re-capture with python -m scripts.playbook_corpus to move the line.
"""

import asyncio

import pytest
from scripts.playbook_corpus.fixture import (
    AUTHOR_CHOICE_REFUSALS,
    CORPUS_DIR,
    CorpusAttempt,
    CorpusRun,
    Verdict,
)
from scripts.playbook_corpus.replay import numbered, replay
from scripts.playbook_corpus.translate import Unmappable

from app.models.playbook_models import PlaybookRefusal

CORPUS = [
    CorpusRun.model_validate_json(path.read_text()) for path in sorted(CORPUS_DIR.glob("*.json"))
]
ATTEMPTS = [(run, attempt) for run in CORPUS for attempt in run.attempts]
EXPRESSIBLE = [(run, attempt) for run, attempt in ATTEMPTS if attempt.picks is not None]


def _id(case: tuple[CorpusRun, CorpusAttempt]) -> str:
    run, attempt = case
    return f"{run.run}@{attempt.position}"


def _verdict(run: CorpusRun, attempt: CorpusAttempt) -> tuple[Verdict, list[PlaybookRefusal]]:
    assert attempt.picks is not None
    outcome = asyncio.run(
        replay(
            str(attempt.written.get("description") or ""),
            attempt.picks,
            str(attempt.written.get("result_brief") or ""),
            numbered(run.record, attempt.record_len),
        )
    )
    return (Verdict.REFUSED if outcome.issues else Verdict.ACCEPTED), outcome.refusals


def test_the_corpus_holds_every_prod_attempt_since_september() -> None:
    # 774 calls in prod traces from 2026-09-01 to 2026-11-03 (read-only count).
    assert len(ATTEMPTS) == 774
    assert len(EXPRESSIBLE) > 200


@pytest.mark.parametrize("case", EXPRESSIBLE, ids=[_id(case) for case in EXPRESSIBLE])
def test_an_expressible_attempt_gets_its_recorded_verdict(
    case: tuple[CorpusRun, CorpusAttempt],
) -> None:
    run, attempt = case

    verdict, refusals = _verdict(run, attempt)

    assert (verdict, refusals) == (attempt.expected, attempt.refusals)


def test_no_expressible_attempt_is_refused_for_anything_but_the_authors_own_choice() -> None:
    refused = {
        _id((run, attempt)): attempt.refusals
        for run, attempt in EXPRESSIBLE
        if attempt.expected is Verdict.REFUSED
    }
    not_chosen = {
        case: kinds for case, kinds in refused.items() if not set(kinds) <= AUTHOR_CHOICE_REFUSALS
    }

    assert not_chosen == {}


def test_every_unexpressible_attempt_says_why() -> None:
    silent = [
        _id((run, attempt))
        for run, attempt in ATTEMPTS
        if attempt.picks is None and (attempt.unmappable is None or not attempt.unmappable_detail)
    ]

    assert silent == []


@pytest.mark.parametrize(
    "case",
    [case for case in ATTEMPTS if case[1].unmappable is Unmappable.STEP_NEVER_RAN],
    ids=_id,
)
def test_a_step_that_never_ran_is_absent_from_the_record_the_author_saw(
    case: tuple[CorpusRun, CorpusAttempt],
) -> None:
    run, attempt = case
    tool = attempt.unmappable_detail.split(";")[0]

    ran = {entry.call.tool_name for entry in numbered(run.record, attempt.record_len)}

    assert tool not in ran
