"""Eval: does the brief's heading check judge each heading by its items' actions and outcomes alone?

A subject, a time or an occasion a heading names is never judged: only what it says items need
or where they got to.

Run it before changing the heading prompt or the helper model it runs on:
uv run pytest tests/model_onboarding/test_brief_headings.py -m model_onboarding -v.
A heading fits when every item under it satisfies it; tone and register never count. The first
case of each kind is a heading a live brief got wrong: "Landed overnight" over a draft still
waiting on approval got through, and "Ready when you are" over finished research was rejected.
"""

from datetime import date

import pytest

from app.constants.briefing import BriefAction, BriefOutcome
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefComposition
from app.models.briefing_models import BriefingItemKind
from app.services.briefing.composition.headings import heading_problems
from app.services.briefing.fact_pool.pool import FactPool, PoolContext

pytestmark = pytest.mark.model_onboarding

_USER = "64f1c0ffee0000000000abcd"
_Side = BriefAction | BriefOutcome
# Each pool item: its title, the state its producer gave it, and its action or outcome.
_ITEMS: dict[int, tuple[str, BriefingItemKind, _Side]] = {
    1: ("Priya's offsite venues", "you", BriefAction.APPROVE),
    2: ("Competitor pricing research", "lookback", BriefOutcome.FINISHED),
    3: ("Investor update", "lookback", BriefOutcome.SENT),
    4: ("Board deck numbers", "gaia", BriefOutcome.STARTED),
    5: ("Acme invoice", "you", BriefAction.REVIEW),
    6: ("Reply to Maya on the term sheet", "you", BriefAction.REPLY),
    7: ("CRM sync", "failed", BriefAction.RETRY),
    8: ("Globex invoice", "you", BriefAction.APPROVE),
    9: ("Lisbon flights", "lookback", BriefOutcome.BOOKED),
}
_POOL = FactPool(
    items={
        i: BriefCandidate(source="gaia", app="GAIA", state=state, title=title)
        for i, (title, state, _) in _ITEMS.items()
    },
    series=[],
    quotes=[],
    goals=[],
    context=PoolContext(
        reader="Ada",
        timezone="UTC",
        today=date(2026, 11, 11),
        calendar_events=0,
        calendar_connected=True,
        calendar_span="today",
        recent_openings=[],
    ),
    criteria={},
)


def _group(heading: str, *ids: int) -> BriefComposition:
    items = []
    for i in ids:
        title, _, side = _ITEMS[i]
        asks = isinstance(side, BriefAction)
        items.append(
            {
                "id": i,
                "action": side if asks else None,
                "outcome": None if asks else side,
                "title": title,
                "detail": None,
            }
        )
    if all(i["action"] is not None for i in items):
        state = "needs_you"
    else:
        state = "in_progress" if all(i["outcome"] == "started" for i in items) else "done"
    return BriefComposition.model_validate(
        {"blocks": [{"kind": "items", "state": state, "heading": heading, "items": items}]}
    )


# Each must fit: every item under it satisfies it, however it is phrased.
_FITTING = {
    "ready when you are, over finished research": _group("Ready when you are", 2),
    "landed overnight, over sent and booked work": _group("Landed overnight", 3, 9),
    "waiting on you, over asks of every kind": _group("Waiting on you", 1, 5, 6, 7),
    "money, over the invoices": _group("Money", 5, 8),
    "still running, over started work": _group("Still running", 4),
    "needs your review, over a retry and a reply": _group("Needs your review", 7, 6),
    # The e2e busy day refused these three, each true of every item under it.
    "a decision, over invoices to review": _group("Money needing a decision", 5, 8),
    "a moment of the day, over asks and running work": _group("Before today's calls", 6, 4),
    "two acts named, over one of them": _group("Replies and approvals", 6, 1),
}
# Each must be refused: a group code passed, every item in its state, under a heading untrue of it.
_MISFITTING = {
    "landed overnight, over a draft waiting on approval": _group("Landed overnight", 1),
    "done, over work only started": _group("Done", 4),
    "a done heading, over an ask": _group("Finished for you", 5),
    "waiting on you, over finished work": _group("Waiting on you", 3, 9),
    "still running, over a failed sync to retry": _group("Still running", 7),
}


@pytest.mark.parametrize("composition", _FITTING.values(), ids=_FITTING.keys())
async def test_a_heading_true_of_every_item_fits(composition: BriefComposition) -> None:
    assert await heading_problems(_USER, composition, _POOL) == []


@pytest.mark.parametrize("composition", _MISFITTING.values(), ids=_MISFITTING.keys())
async def test_a_heading_untrue_of_an_item_is_named(composition: BriefComposition) -> None:
    assert await heading_problems(_USER, composition, _POOL) != []
