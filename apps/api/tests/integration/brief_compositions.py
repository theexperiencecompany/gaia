"""Four composed briefs every edition family renders: busy, quiet with a goal, a charted spike, a week.

Each is a BriefingPayload as the pipeline stores it after composition, with every block kind and
chart kind between them, so each family's renderer for each kind is exercised.
"""

from datetime import date, timedelta
from typing import Any

from app.constants.briefing import BriefAction, BriefOutcome
from app.models.briefing_models import BriefingPayload
from app.services.briefing.editions.capabilities import split_drawable
from app.services.briefing.fact_pool.window import SeriesName
from tests.factories import make_brief_item

TODAY = "2026-11-10"
_DAYS = [(date(2026, 11, 10) - timedelta(days=6 - n)).isoformat() for n in range(7)]
_WEEK = [(date(2026, 11, 9) + timedelta(days=n)).isoformat() for n in range(7)]


def _series(name: SeriesName, ys: list[float], days: list[str]) -> dict[str, Any]:
    return {
        "id": name.id,
        "label": name.label,
        "unit": name.unit,
        "source": name.source,
        "app": name.app,
        "shape": "time_series",
        "points": [{"x": x, "y": y} for x, y in zip(days, ys, strict=True)],
    }


def _ask(
    text: str, action: BriefAction, source: str, app: str, detail: str | None = None
) -> dict[str, Any]:
    return make_brief_item(text, "you", action=action, source=source, app=app, detail=detail)


def _done(
    text: str, outcome: BriefOutcome, source: str, app: str, detail: str | None = None
) -> dict[str, Any]:
    return make_brief_item(text, "lookback", outcome=outcome, source=source, app=app, detail=detail)


_BASE: dict[str, Any] = {
    "kicker": "THE MORNING BRIEF",
    "date": TODAY,
    "lede": "",
    "mood": "packed",
    "caption": "",
    "generated_at": "6:02 AM",
    "recipient_name": "Alexandra Okonkwo-Fitzgerald",
    "link": "https://heygaia.link/aB3dE5gH7jK",
    "template_family": "swiss",
}

_LEAD = {
    "numeral": "I",
    "title": "First up",
    "items": [
        _ask(
            "Northwind renewal is up 18%",
            BriefAction.APPROVE,
            "gmail",
            "Gmail",
            "Due Thu 17:00. Last year's terms capped rises at 10%.",
        )
        | {"offer": "GAIA can draft a reply asking Dana to hold the 10% cap."}
    ],
}
_NEEDS_YOU = {
    "numeral": "II",
    "title": "Needs you",
    "items": [
        _ask(
            "Priyanka on the Lisbon offsite venues",
            BriefAction.REPLY,
            "slack",
            "Slack",
            "2 messages in Slack, due today 12:00",
        ),
        _ask(
            "Reconnect Notion",
            BriefAction.RETRY,
            "notion",
            "Notion",
            "The roadmap sync is paused until you do",
        ),
        _ask("PR #1452, the billing webhook fix", BriefAction.REVIEW, "github", "GitHub"),
        _ask("Linear cycle 14 scope", BriefAction.READ, "linear", "Linear"),
    ],
}
_DONE = {
    "numeral": "III",
    "title": "Done for you",
    "items": [
        _done(
            "PR #1448, by two reviewers",
            BriefOutcome.APPROVED,
            "github",
            "GitHub",
            "Sam K. and Ines M. on GitHub",
        ),
        _done(
            "$4,210 Stripe payout",
            BriefOutcome.LANDED,
            "gmail",
            "Gmail",
            "In the operating account",
        ),
        _done(
            "Replies to 6 newsletters",
            BriefOutcome.DRAFTED,
            "gaia",
            "GAIA",
            "41 promotions archived too",
        ),
    ],
}
_CALENDAR = [
    {"date": TODAY, "start": None, "title": "Quarterly planning week"},
    {"date": TODAY, "start": "09:30", "title": "Standup"},
    {
        "date": TODAY,
        "start": "11:00",
        "title": "Design review: brief v2 editions",
        "location": "Studio 4, Fifth Floor",
    },
    {"date": TODAY, "start": "15:30", "title": "Investor call with Sequoia"},
]

BUSY: dict[str, Any] = _BASE | {
    "headline": "Three things need you before Thursday, and the contract is the one that can't slip",
    "sections": [_LEAD, _NEEDS_YOU, _DONE],
    "calendar": _CALENDAR,
    "tallies": {"done_by_you": 3, "done_by_gaia": 9},
    "blocks": [
        {"kind": "lead", "section": 0},
        {"kind": "items", "section": 1},
        {"kind": "items", "section": 2},
        {
            "kind": "chart",
            "chart": "stacked_bar",
            "title": "Tasks closed each day",
            "takeaway": "Sunday was the week's peak, and GAIA closed two in three.",
            "series": [
                _series(
                    SeriesName("you_finished", "You", "tasks", "gaia", "GAIA"),
                    [4, 6, 3, 5, 7, 1, 0],
                    _DAYS,
                ),
                _series(
                    SeriesName("gaia_finished", "GAIA", "tasks", "gaia", "GAIA"),
                    [7, 9, 11, 8, 12, 3, 2],
                    _DAYS,
                ),
            ],
        },
        {
            "kind": "quote",
            "quote": {
                "id": "q1",
                "text": "If we can lock Northwind at last year's cap, the whole Q4 budget holds.",
                "author": "Dana Whitlock",
                "source": "gmail",
                "app": "Gmail",
                "item_id": 1,
            },
        },
        {
            "kind": "note",
            "text": "You reply fastest before 10:00; the Northwind draft will be ready by 9.",
        },
    ],
}

QUIET_GOAL: dict[str, Any] = _BASE | {
    "headline": "A quiet Tuesday, and the hiring plan is five roles in",
    "mood": "idle",
    "sections": [
        {
            "numeral": "I",
            "title": "Done overnight",
            "items": [
                _done(
                    "Offer letter for the staff engineer",
                    BriefOutcome.SENT,
                    "gmail",
                    "Gmail",
                    "Signed copy filed to Drive",
                ),
                _done(
                    "Interview loop for the designer role",
                    BriefOutcome.BOOKED,
                    "googlecalendar",
                    "Google Calendar",
                ),
            ],
        }
    ],
    "calendar": [{"date": TODAY, "start": None, "title": "Focus day"}],
    "tallies": {"done_by_you": 1, "done_by_gaia": 2},
    "blocks": [
        {"kind": "items", "section": 0},
        {
            "kind": "progress",
            "goal": {
                "id": "g1",
                "statement": "Fill eight roles in the Q4 hiring plan",
                "origin": "memory",
                "done": 5,
                "open": 3,
                "linked": [],
            },
        },
        {"kind": "note", "text": "Nothing waits on you today, so the afternoon is yours."},
    ],
}

SPIKE: dict[str, Any] = _BASE | {
    "headline": "Your inbox tripled overnight, and two of the new threads need you",
    "sections": [
        {
            "numeral": "I",
            "title": "First up",
            "items": [
                _ask(
                    "Acme's security questionnaire",
                    BriefAction.REVIEW,
                    "gmail",
                    "Gmail",
                    "Due Friday; 42 questions, 30 drafted",
                )
                | {"offer": "GAIA can fill the rest from last year's answers."}
            ],
        },
        {
            "numeral": "II",
            "title": "From the spike",
            "items": [
                _ask(
                    "Lena on the launch date",
                    BriefAction.REPLY,
                    "gmail",
                    "Gmail",
                    "Asked twice since Sunday",
                ),
                _done(
                    "38 launch-list signups",
                    BriefOutcome.FINISHED,
                    "gaia",
                    "GAIA",
                    "Filed to the waitlist sheet",
                ),
            ],
        },
    ],
    "calendar": [
        {"date": TODAY, "start": "10:00", "title": "Launch sync"},
        {"date": TODAY, "start": "14:00", "title": "Acme security call"},
    ],
    "tallies": {"done_by_you": 2, "done_by_gaia": 5},
    "blocks": [
        {"kind": "lead", "section": 0},
        {
            "kind": "chart",
            "chart": "line",
            "title": "Emails received each day",
            "takeaway": "Yesterday brought 61, three times a usual day.",
            "series": [
                _series(
                    SeriesName("mail_received", "Emails received", "emails", "gmail", "Gmail"),
                    [18, 22, 19, 24, 20, 23, 61],
                    _DAYS,
                ),
            ],
        },
        {"kind": "items", "section": 1},
        {
            "kind": "chart",
            "chart": "bar",
            "title": "Meeting hours each day",
            "takeaway": "Today holds 3.5 hours, the week's lightest weekday.",
            "series": [
                _series(
                    SeriesName(
                        "calendar_meeting_hours",
                        "Meeting hours",
                        "hours",
                        "googlecalendar",
                        "Google Calendar",
                    ),
                    [5.5, 4, 6, 4.5, 5, 0.5, 3.5],
                    _DAYS,
                ),
            ],
        },
    ],
}

WEEKLY: dict[str, Any] = _BASE | {
    "headline": "Your busiest week since September, and GAIA carried most of it",
    "mood": "weekly",
    "date": "2026-11-15",
    "sections": [
        {
            "numeral": "I",
            "title": "Shipped",
            "items": [
                _done("Scouts on the morning brief", BriefOutcome.FINISHED, "github", "GitHub"),
                _done("Air Mail postmarks", BriefOutcome.FINISHED, "github", "GitHub"),
                _done("Onboarding paywall copy", BriefOutcome.FINISHED, "linear", "Linear"),
            ],
        },
        {
            "numeral": "II",
            "title": "Handled by GAIA",
            "items": [
                _done("38 routine emails", BriefOutcome.SENT, "gmail", "Gmail"),
                _done("12 receipts to Drive", BriefOutcome.FINISHED, "gaia", "GAIA"),
                _done(
                    "3 clashing meetings", BriefOutcome.CHANGED, "googlecalendar", "Google Calendar"
                ),
                _done("Vendor W-9 reminders", BriefOutcome.SENT, "gmail", "Gmail"),
            ],
        },
    ],
    "tallies": {"done_by_you": 26, "done_by_gaia": 52},
    "week": {
        "days": [
            {"you": y, "gaia": g}
            for y, g in [(4, 7), (6, 9), (3, 11), (5, 8), (7, 12), (1, 3), (0, 2)]
        ],
        "ahead": [
            {"date": "2026-11-17", "start": "10:00", "title": "Board update"},
            {"date": "2026-11-18", "start": "14:00", "title": "Hiring panel: staff engineer"},
            {"date": "2026-11-20", "start": None, "title": "Lisbon summit"},
        ],
    },
    "blocks": [
        {"kind": "items", "section": 0},
        {"kind": "items", "section": 1},
        {
            "kind": "chart",
            "chart": "stacked_bar",
            "title": "Tasks closed each day",
            "takeaway": "Friday carried the week; the weekend stayed light.",
            "series": [
                _series(
                    SeriesName("you_finished", "You", "tasks", "gaia", "GAIA"),
                    [4, 6, 3, 5, 7, 1, 0],
                    _WEEK,
                ),
                _series(
                    SeriesName("gaia_finished", "GAIA", "tasks", "gaia", "GAIA"),
                    [7, 9, 11, 8, 12, 3, 2],
                    _WEEK,
                ),
            ],
        },
        {
            "kind": "chart",
            "chart": "spark",
            "title": "Emails GAIA handled",
            "takeaway": "Up every day since Tuesday.",
            "series": [
                _series(
                    SeriesName("mail_handled", "Emails handled", "emails", "gmail", "Gmail"),
                    [9, 12, 8, 15, 18, 21, 27],
                    _WEEK,
                ),
            ],
        },
        {
            "kind": "progress",
            "goal": {
                "id": "g1",
                "statement": "Fill eight roles in the Q4 hiring plan",
                "origin": "memory",
                "done": 5,
                "open": 3,
                "linked": [],
            },
        },
        {
            "kind": "note",
            "text": "Two of next week's three meetings fall before 11:00; mornings will be tight.",
        },
    ],
}

COMPOSITIONS: dict[str, dict[str, Any]] = {
    "busy": BUSY,
    "quiet": QUIET_GOAL,
    "spike": SPIKE,
    "weekly": WEEKLY,
}


def composed_payload(composition: str, family: str, artwork_id: str | None) -> BriefingPayload:
    """Return the composition as the pipeline hands it to the family: its blocks split by what it draws."""
    payload = BriefingPayload.model_validate(
        COMPOSITIONS[composition] | {"template_family": family, "artwork_id": artwork_id}
    )
    drawn, undrawn = split_drawable(family, payload.blocks)
    return payload.model_copy(update={"blocks": drawn, "undrawn": undrawn})
