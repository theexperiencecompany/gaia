"""The stub's Decisions route answers what a test scripts, and refuses an unscripted call like an unpaid account."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from decisions import (
    NO_CREDIT_STATUS,
    SCRIPTED_CONFIDENCE,
    DecisionsScriptError,
    answer_decisions,
)

_CHOICES = {"approve": "…", "amend": "…", "deny": "…", "leave": "…", "unrelated": "…"}


def _call(reply: str, *names: str) -> dict[str, object]:
    return {
        "model": "typesafe/jev",
        "state": {"reply": reply, "pending_actions": []},
        "questions": {name: {"type": "choice", "criteria": _CHOICES} for name in names},
    }


def test_every_question_gets_the_scripted_choice() -> None:
    answer = answer_decisions(_call("yes but high priority [[jev:amend]]", "action_1", "action_2"))

    assert answer.status == 200
    assert {name: a["choice"] for name, a in answer.body["answers"].items()} == {
        "action_1": "amend",
        "action_2": "amend",
    }
    assert answer.body["answers"]["action_1"]["confidence"] == SCRIPTED_CONFIDENCE


def test_an_unscripted_reply_is_refused_as_no_credit() -> None:
    assert answer_decisions(_call("yes but high priority", "action_1")).status == NO_CREDIT_STATUS


def test_a_call_with_no_reply_is_refused_as_no_credit() -> None:
    reaction = {"state": {"message": "thanks [[jev:approve]]"}, "questions": {}}

    assert answer_decisions(reaction).status == NO_CREDIT_STATUS


def test_a_choice_the_question_does_not_offer_fails_loud() -> None:
    with pytest.raises(DecisionsScriptError, match="maybe"):
        answer_decisions(_call("hmm [[jev:maybe]]", "action_1"))


def test_two_directives_fail_loud() -> None:
    with pytest.raises(DecisionsScriptError, match="more than one"):
        answer_decisions(_call("[[jev:approve]] [[jev:deny]]", "action_1"))
