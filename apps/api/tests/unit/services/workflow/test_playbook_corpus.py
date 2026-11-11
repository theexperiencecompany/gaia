"""Every write_playbook attempt prod made since 2026-09-01, replayed through the pick flow.

The fixtures are real attempts (anonymised by scripts/playbook_corpus), each
re-expressed as picks over its own run's record. The gate: an attempt the pick
flow can express is accepted, or refused only for something the author
explicitly asked for that no server could reinterpret (AUTHOR_CHOICE_REFUSALS).
Drive runs carry picks a real model sent on a local stack, refusals included.
An attempt that cannot be said as picks carries why, and the why is checked
against its record. A change that turns any accepted attempt into a refusal
fails here; re-capture with python -m scripts.playbook_corpus to move the line.
"""

import asyncio
import json
from pathlib import Path
import re

import pytest
from scripts.playbook_corpus.__main__ import _tally_key
from scripts.playbook_corpus.fixture import (
    AUTHOR_CHOICE_REFUSALS,
    CORPUS_DIR,
    CorpusAttempt,
    CorpusRun,
    OldOutcome,
    Origin,
    Verdict,
)
from scripts.playbook_corpus.replay import entries, replay
from scripts.playbook_corpus.translate import Unmappable

from app.models.playbook_models import PlaybookRefusal

CORPUS = [
    CorpusRun.model_validate_json(path.read_text()) for path in sorted(CORPUS_DIR.glob("*.json"))
]
ATTEMPTS = [(run, attempt) for run in CORPUS for attempt in run.attempts]
EXPRESSIBLE = [(run, attempt) for run, attempt in ATTEMPTS if attempt.picks is not None]
PROD = [(run, attempt) for run, attempt in ATTEMPTS if run.origin is Origin.PROD]
#: What a person's data looks like once it has slipped past the anonymiser.
LEAKS = {
    "phone": re.compile(r"\+\d{1,3}[ .-]\(?\d{3}|\+\d{10,14}|\d{3}\)?[ .-]{1,2}\d{3}[ .-]\d{4}"),
    "ip": re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])"),
    "non-ascii letter": re.compile(r"[^\W\d_](?<![A-Za-z])"),
}


def _strings(node: object) -> list[str]:
    """Every key and string in a fixture, nested JSON text (a result digest) decoded too."""
    if isinstance(node, dict):
        return [text for key, item in node.items() for text in [key, *_strings(item)]]
    if isinstance(node, list):
        return [text for item in node for text in _strings(item)]
    if not isinstance(node, str):
        return []
    if node[:1] in ("{", "["):
        try:
            return [node, *_strings(json.loads(node))]
        except ValueError:
            return [node]
    return [node]


def _leaks(path: Path) -> list[str]:
    return [
        f"{path.name}: {kind} {match.group(0)!r}"
        for text in _strings(json.loads(path.read_text()))
        for kind, pattern in LEAKS.items()
        for match in pattern.finditer(text)
    ]


def test_no_fixture_holds_a_phone_number_an_ip_or_unscrubbed_text() -> None:
    leaks = [leak for path in sorted(CORPUS_DIR.glob("*.json")) for leak in _leaks(path)]

    assert leaks == []


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
            entries(run.record, attempt.record_len),
            run.replaces,
        )
    )
    return (Verdict.REFUSED if outcome.issues else Verdict.ACCEPTED), outcome.refusals


def test_the_corpus_holds_every_prod_attempt_since_september() -> None:
    # 774 calls in prod traces from 2026-09-01 to 2026-11-03 (read-only count).
    assert len(PROD) == 774
    assert len([case for case in PROD if case[1].picks is not None]) > 200


@pytest.mark.parametrize("case", EXPRESSIBLE, ids=[_id(case) for case in EXPRESSIBLE])
def test_an_expressible_attempt_gets_its_recorded_verdict(
    case: tuple[CorpusRun, CorpusAttempt],
) -> None:
    run, attempt = case

    verdict, refusals = _verdict(run, attempt)

    assert (verdict, refusals) == (attempt.expected, attempt.refusals)


def test_no_prod_attempt_is_refused_for_anything_but_the_authors_own_choice() -> None:
    refused = {
        _id((run, attempt)): attempt.refusals
        for run, attempt in PROD
        if attempt.expected is Verdict.REFUSED
    }
    not_chosen = {
        case: kinds for case, kinds in refused.items() if not set(kinds) <= AUTHOR_CHOICE_REFUSALS
    }

    assert not_chosen == {}


def test_a_time_layout_refusal_is_tallied_as_the_authors_choice() -> None:
    """It names the {"$time", "format"} slot to write, so the author sent the wrong layout."""
    attempt = CorpusAttempt(
        position=0,
        record_len=1,
        written={},
        old_outcome=OldOutcome.REFUSED,
        expected=Verdict.REFUSED,
        refusals=[PlaybookRefusal.TIME_LAYOUT],
    )

    assert _tally_key(attempt) == "refused:time_layout"


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

    ran = {entry.call.tool_name for entry in entries(run.record, attempt.record_len)}

    assert tool not in ran


@pytest.mark.parametrize(
    "case",
    [case for case in ATTEMPTS if case[1].unmappable is Unmappable.EMPTY_RECORD],
    ids=_id,
)
def test_an_empty_record_holds_no_pickable_call(case: tuple[CorpusRun, CorpusAttempt]) -> None:
    run, attempt = case

    assert entries(run.record, attempt.record_len) == []
