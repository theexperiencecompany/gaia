"""Eval: does the brief's faithfulness check flag what real briefs got wrong, and pass what they got right?

Run it before changing the check's prompt or the helper model it runs on:
uv run pytest tests/model_onboarding/test_brief_faithfulness.py -m model_onboarding -v.
The bad drafts are the shapes live briefs shipped (a person no fact names, an event over an
empty calendar, a count the facts never gave); the good ones restate the facts in other words.
Values in ⟦ ⟧ are what slots filled in, as the check sees them in production.
"""

from dataclasses import replace

import pytest

from app.services.briefing.faithfulness import CheckedProse, unsupported_claims

pytestmark = pytest.mark.model_onboarding

_USER = "64f1c0ffee0000000000abcd"
_FACTS = """You're writing to Ada. Use their name at most once.
[COUNTS] needs_you: 2 · done: 1 · events: 1
[Needs you]
- fact 1 | Waiting on you: Send the signed NDA back to Lena at Northwind | in Gmail
- fact 2 | Failed: CRM sync failed | detail: HubSpot token expired
[GAIA's work]
- fact 3 | Done: Investor update | summary: Sent to fourteen investors; Elad Gil and Nat \
Friedman replied | artifact holds ~900 chars | linkable
The user's own todo list is empty.
Today's calendar:
- fact 4 | 11:00 AM: Sequoia partner meeting
Raising a seed round [mentioned 2026-10-01]
Yesterday: two investor drafts written
(no replies)"""

_TRUE = CheckedProse(
    headline="Lena's NDA is waiting on you",
    lede="Send the signed NDA back to Lena, then Sequoia at ⟦11:00 AM⟧.",
    caption="One signature before the partner meeting.",
    message=(
        "Lena at Northwind is waiting on the signed NDA, so that's the one to clear first.\n"
        "The CRM sync failed because the HubSpot token expired. Want me to reconnect it?\n"
        "The investor update went out, and Elad Gil and Nat Friedman already replied.\n"
        "Then the Sequoia partner meeting at ⟦11:00 AM⟧, a good moment for the seed round."
    ),
)
_QUIET_AND_TRUE = CheckedProse(
    headline="Two things need you before Sequoia",
    lede="The NDA for Lena and a sync that needs a fresh HubSpot token.",
    caption="Short list, big meeting.",
    message=(
        "⟦2⟧ things need you this morning: Lena's NDA and the CRM sync.\nSequoia at ⟦11:00 AM⟧."
    ),
)


def _with(**prose: str) -> CheckedProse:
    return replace(_TRUE, **prose)


_FALSE = {
    "a person no fact names": _with(headline="Arjun's contract redlines need you"),
    "an empty calendar over a meeting": _with(
        lede="Send Lena the NDA; your calendar is clear all day."
    ),
    "a count the facts never gave": _with(
        message=_TRUE.message.replace("Lena at Northwind", "Three things need you. Lena")
    ),
    "a failure called fixed": _with(
        message=_TRUE.message.replace(
            "The CRM sync failed because the HubSpot token expired. Want me to reconnect it?",
            "I fixed the CRM sync overnight, so HubSpot is back in step.",
        )
    ),
    "an invented deadline": _with(caption="Your lawyer needs the NDA by Friday."),
}


@pytest.mark.parametrize("draft", [_TRUE, _QUIET_AND_TRUE], ids=["full", "quiet"])
async def test_a_brief_that_restates_its_facts_passes(draft: CheckedProse) -> None:
    assert await unsupported_claims(_USER, _FACTS, draft) == []


@pytest.mark.parametrize("draft", _FALSE.values(), ids=_FALSE.keys())
async def test_a_brief_that_claims_what_its_facts_do_not_is_flagged(draft: CheckedProse) -> None:
    assert await unsupported_claims(_USER, _FACTS, draft) != []
