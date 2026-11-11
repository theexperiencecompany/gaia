"""Eval: does the brief's faithfulness check flag what real briefs got wrong, and pass what they got right?

Run it before changing the check's prompt or the helper model it runs on:
uv run pytest tests/model_onboarding/test_brief_faithfulness.py -m model_onboarding -v.
The bad drafts are the shapes live briefs shipped (a person no fact names, an event over an
empty calendar, a count the facts never gave); the good ones restate the facts in other words.
Values in ⟦ ⟧ are what slots filled in, as the check sees them in production. The honest
drafts are vague, paraphrased or reordered on purpose: the check must never flag those.
"""

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

_TRUE_FIELDS = {
    "headline": "Lena's NDA is waiting on you",
    "lede": "Send the signed NDA back to Lena, then Sequoia at ⟦11:00 AM⟧.",
    "caption": "One signature before the partner meeting.",
    "message": (
        "Lena at Northwind is waiting on the signed NDA, so that's the one to clear first.\n"
        "The CRM sync failed because the HubSpot token expired. Want me to reconnect it?\n"
        "The investor update went out, and Elad Gil and Nat Friedman already replied.\n"
        "Then the Sequoia partner meeting at ⟦11:00 AM⟧, a good moment for the seed round."
    ),
}


def _with(**prose: str) -> CheckedProse:
    return CheckedProse(fields=tuple({**_TRUE_FIELDS, **prose}.items()))


_TRUE = _with()


# Each must pass: true, however loosely, briefly or out of order it says so.
_HONEST = {
    "full": _TRUE,
    "counted by a slot": _with(
        headline="Two things need you before Sequoia",
        message="⟦2⟧ things need you: Lena's NDA and the CRM sync.\nSequoia at ⟦11:00 AM⟧.",
    ),
    "vague": _with(
        lede="A few things need you this morning, the NDA among them.",
        message=(
            "A couple of things are on your plate, the NDA for Lena first.\n"
            "Something broke in the CRM sync overnight; want me to look?\n"
            "Sequoia later this morning."
        ),
    ),
    "paraphrased": _with(
        headline="Lena needs your signature",
        lede="The Northwind NDA wants your signature, and HubSpot needs a fresh login.",
        message=(
            "Lena's waiting on your signature for the Northwind NDA.\n"
            "The HubSpot connection behind the CRM sync lapsed, so the sync stopped.\n"
            "Your investor note is out; Elad and Nat have already written back.\n"
            "You meet the Sequoia partners at ⟦11:00 AM⟧."
        ),
    ),
    "reordered": _with(
        headline="Sequoia at ⟦11:00 AM⟧, NDA first",
        message=(
            "Sequoia partner meeting at ⟦11:00 AM⟧.\n"
            "Before it: the investor update shipped and two investors replied.\n"
            "Lena still needs the signed NDA, and the CRM sync needs a new HubSpot token."
        ),
    ),
    "offer and wit": _with(
        caption="Fourteen investors emailed, and only one signature left for you.",
        message=_TRUE_FIELDS["message"]
        + "\nWant me to draft a note to Lena so you only have to sign?",
    ),
}
# Each must fail: a specific the facts contradict or do not hold.
_FALSE = {
    "a person no fact names": _with(headline="Arjun's contract redlines need you"),
    "an empty calendar over a meeting": _with(
        lede="Send Lena the NDA; your calendar is clear all day."
    ),
    "a count the facts never gave": _with(
        message=_TRUE_FIELDS["message"].replace("Lena at Northwind", "Three things need you. Lena")
    ),
    "a failure called fixed": _with(
        message=_TRUE_FIELDS["message"].replace(
            "The CRM sync failed because the HubSpot token expired. Want me to reconnect it?",
            "I fixed the CRM sync overnight, so HubSpot is back in step.",
        )
    ),
    "an invented deadline": _with(caption="Your lawyer needs the NDA by Friday."),
    "done work called unfinished": _with(
        message=_TRUE_FIELDS["message"].replace(
            "The investor update went out, and Elad Gil and Nat Friedman already replied.",
            "I'm still drafting the investor update; nobody has seen it yet.",
        )
    ),
}


@pytest.mark.parametrize("draft", _HONEST.values(), ids=_HONEST.keys())
async def test_a_brief_that_restates_its_facts_passes(draft: CheckedProse) -> None:
    assert await unsupported_claims(_USER, _FACTS, draft) == []


@pytest.mark.parametrize("draft", _FALSE.values(), ids=_FALSE.keys())
async def test_a_brief_that_claims_what_its_facts_do_not_is_flagged(draft: CheckedProse) -> None:
    assert await unsupported_claims(_USER, _FACTS, draft) != []
