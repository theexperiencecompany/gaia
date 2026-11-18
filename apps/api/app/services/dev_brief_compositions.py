"""Four composed sample briefs: busy, quiet with a goal, a charted spike, a week.

Each is a BriefingPayload as the pipeline stores it after composition, with every block kind and
chart kind between them, so each edition family's renderer for each kind is exercised. The
Briefing settings demo images are rendered from the busy one.
"""

from datetime import date, timedelta
from typing import Any

from app.constants.briefing import BriefAction, BriefOutcome, EditionFamily
from app.models.brief_payload_models import BriefingPayload
from app.services.briefing.editions.capabilities import split_drawable

TODAY = "2026-11-10"
_DAYS = [(date(2026, 11, 10) - timedelta(days=6 - n)).isoformat() for n in range(7)]
_WEEK = [(date(2026, 11, 9) + timedelta(days=n)).isoformat() for n in range(7)]


_BASE: dict[str, Any] = {
    "kicker": "THE MORNING BRIEF",
    "date": TODAY,
    "lede": "",
    "mood": "packed",
    "caption": "",
    "generated_at": "6:02 AM",
    "recipient_name": "Alexandra Okonkwo-Fitzgerald",
    "template_family": "swiss",
}

_LEAD = {
    "numeral": "I",
    "title": "First up",
    "items": [
        {
            "text": "Northwind renewal is up 18%",
            "kind": "you",
            "action": BriefAction.APPROVE,
            "source": "gmail",
            "app": "Gmail",
            "detail": "Due Thu 17:00. Last year's terms capped rises at 10%.",
        }
        | {"offer": "GAIA can draft a reply asking Dana to hold the 10% cap."}
    ],
}
_NEEDS_YOU = {
    "numeral": "II",
    "title": "Needs you",
    "items": [
        {
            "text": "Priyanka on the Lisbon offsite venues",
            "kind": "you",
            "action": BriefAction.REPLY,
            "source": "slack",
            "app": "Slack",
            "detail": "2 messages in Slack, due today 12:00",
        },
        {
            "text": "Reconnect Notion",
            "kind": "you",
            "action": BriefAction.RETRY,
            "source": "notion",
            "app": "Notion",
            "detail": "The roadmap sync is paused until you do",
        },
        {
            "text": "PR #1452, the billing webhook fix",
            "kind": "you",
            "action": BriefAction.REVIEW,
            "source": "github",
            "app": "GitHub",
        },
        {
            "text": "Linear cycle 14 scope",
            "kind": "you",
            "action": BriefAction.READ,
            "source": "linear",
            "app": "Linear",
        },
    ],
}
_DONE = {
    "numeral": "III",
    "title": "Done for you",
    "items": [
        {
            "text": "PR #1448, by two reviewers",
            "kind": "lookback",
            "outcome": BriefOutcome.APPROVED,
            "source": "github",
            "app": "GitHub",
            "detail": "Sam K. and Ines M. on GitHub",
        },
        {
            "text": "$4,210 Stripe payout",
            "kind": "lookback",
            "outcome": BriefOutcome.LANDED,
            "source": "gmail",
            "app": "Gmail",
            "detail": "In the operating account",
        },
        {
            "text": "Replies to 6 newsletters",
            "kind": "lookback",
            "outcome": BriefOutcome.DRAFTED,
            "source": "gaia",
            "app": "GAIA",
            "detail": "41 promotions archived too",
        },
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
    "sources_read": ["GitHub", "Gmail", "Slack", "Linear", "Notion", "Google Calendar"],
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
                {
                    "id": "you_finished",
                    "label": "You",
                    "unit": "tasks",
                    "source": "gaia",
                    "app": "GAIA",
                    "shape": "time_series",
                    "points": [
                        {"x": x, "y": y} for x, y in zip(_DAYS, [4, 6, 3, 5, 7, 1, 0], strict=True)
                    ],
                },
                {
                    "id": "gaia_finished",
                    "label": "GAIA",
                    "unit": "tasks",
                    "source": "gaia",
                    "app": "GAIA",
                    "shape": "time_series",
                    "points": [
                        {"x": x, "y": y}
                        for x, y in zip(_DAYS, [7, 9, 11, 8, 12, 3, 2], strict=True)
                    ],
                },
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
    "sources_read": ["Gmail", "Google Calendar"],
    "headline": "A quiet Tuesday, and the hiring plan is five roles in",
    "mood": "idle",
    "sections": [
        {
            "numeral": "I",
            "title": "Done overnight",
            "items": [
                {
                    "text": "Offer letter for the staff engineer",
                    "kind": "lookback",
                    "outcome": BriefOutcome.SENT,
                    "source": "gmail",
                    "app": "Gmail",
                    "detail": "Signed copy filed to Drive",
                },
                {
                    "text": "Interview loop for the designer role",
                    "kind": "lookback",
                    "outcome": BriefOutcome.BOOKED,
                    "source": "googlecalendar",
                    "app": "Google Calendar",
                },
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
    "sources_read": ["Gmail", "Google Calendar"],
    "headline": "Your inbox tripled overnight, and two of the new threads need you",
    "sections": [
        {
            "numeral": "I",
            "title": "First up",
            "items": [
                {
                    "text": "Acme's security questionnaire",
                    "kind": "you",
                    "action": BriefAction.REVIEW,
                    "source": "gmail",
                    "app": "Gmail",
                    "detail": "Due Friday; 42 questions, 30 drafted",
                }
                | {"offer": "GAIA can fill the rest from last year's answers."}
            ],
        },
        {
            "numeral": "II",
            "title": "From the spike",
            "items": [
                {
                    "text": "Lena on the launch date",
                    "kind": "you",
                    "action": BriefAction.REPLY,
                    "source": "gmail",
                    "app": "Gmail",
                    "detail": "Asked twice since Sunday",
                },
                {
                    "text": "38 launch-list signups",
                    "kind": "lookback",
                    "outcome": BriefOutcome.FINISHED,
                    "source": "gaia",
                    "app": "GAIA",
                    "detail": "Filed to the waitlist sheet",
                },
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
                {
                    "id": "mail_received",
                    "label": "Emails received",
                    "unit": "emails",
                    "source": "gmail",
                    "app": "Gmail",
                    "shape": "time_series",
                    "points": [
                        {"x": x, "y": y}
                        for x, y in zip(_DAYS, [18, 22, 19, 24, 20, 23, 61], strict=True)
                    ],
                },
            ],
        },
        {"kind": "items", "section": 1},
        {
            "kind": "chart",
            "chart": "bar",
            "title": "Meeting hours each day",
            "takeaway": "Today holds 3.5 hours, the week's lightest weekday.",
            "series": [
                {
                    "id": "calendar_meeting_hours",
                    "label": "Meeting hours",
                    "unit": "hours",
                    "source": "googlecalendar",
                    "app": "Google Calendar",
                    "shape": "time_series",
                    "points": [
                        {"x": x, "y": y}
                        for x, y in zip(_DAYS, [5.5, 4, 6, 4.5, 5, 0.5, 3.5], strict=True)
                    ],
                },
            ],
        },
    ],
}

WEEKLY: dict[str, Any] = _BASE | {
    "sources_read": ["GitHub", "Gmail", "Linear", "Google Calendar"],
    "headline": "Your busiest week since September, and GAIA carried most of it",
    "mood": "weekly",
    "date": "2026-11-15",
    "sections": [
        {
            "numeral": "I",
            "title": "Shipped",
            "items": [
                {
                    "text": "Scouts on the morning brief",
                    "kind": "lookback",
                    "outcome": BriefOutcome.FINISHED,
                    "source": "github",
                    "app": "GitHub",
                },
                {
                    "text": "Air Mail postmarks",
                    "kind": "lookback",
                    "outcome": BriefOutcome.FINISHED,
                    "source": "github",
                    "app": "GitHub",
                },
                {
                    "text": "Onboarding paywall copy",
                    "kind": "lookback",
                    "outcome": BriefOutcome.FINISHED,
                    "source": "linear",
                    "app": "Linear",
                },
            ],
        },
        {
            "numeral": "II",
            "title": "Handled by GAIA",
            "items": [
                {
                    "text": "38 routine emails",
                    "kind": "lookback",
                    "outcome": BriefOutcome.SENT,
                    "source": "gmail",
                    "app": "Gmail",
                },
                {
                    "text": "12 receipts to Drive",
                    "kind": "lookback",
                    "outcome": BriefOutcome.FINISHED,
                    "source": "gaia",
                    "app": "GAIA",
                },
                {
                    "text": "3 clashing meetings",
                    "kind": "lookback",
                    "outcome": BriefOutcome.CHANGED,
                    "source": "googlecalendar",
                    "app": "Google Calendar",
                },
                {
                    "text": "Vendor W-9 reminders",
                    "kind": "lookback",
                    "outcome": BriefOutcome.SENT,
                    "source": "gmail",
                    "app": "Gmail",
                },
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
                {
                    "id": "you_finished",
                    "label": "You",
                    "unit": "tasks",
                    "source": "gaia",
                    "app": "GAIA",
                    "shape": "time_series",
                    "points": [
                        {"x": x, "y": y} for x, y in zip(_WEEK, [4, 6, 3, 5, 7, 1, 0], strict=True)
                    ],
                },
                {
                    "id": "gaia_finished",
                    "label": "GAIA",
                    "unit": "tasks",
                    "source": "gaia",
                    "app": "GAIA",
                    "shape": "time_series",
                    "points": [
                        {"x": x, "y": y}
                        for x, y in zip(_WEEK, [7, 9, 11, 8, 12, 3, 2], strict=True)
                    ],
                },
            ],
        },
        {
            "kind": "chart",
            "chart": "spark",
            "title": "Emails GAIA handled",
            "takeaway": "Up every day since Tuesday.",
            "series": [
                {
                    "id": "mail_handled",
                    "label": "Emails handled",
                    "unit": "emails",
                    "source": "gmail",
                    "app": "Gmail",
                    "shape": "time_series",
                    "points": [
                        {"x": x, "y": y}
                        for x, y in zip(_WEEK, [9, 12, 8, 15, 18, 21, 27], strict=True)
                    ],
                },
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


def composed_payload(
    composition: str, family: EditionFamily, artwork_id: str | None, stamp_city: str | None = None
) -> BriefingPayload:
    """Return the composition as the pipeline hands it to the family: its blocks split by what it draws."""
    payload = BriefingPayload.model_validate(
        COMPOSITIONS[composition]
        | {"template_family": family, "artwork_id": artwork_id, "stamp_city": stamp_city}
    )
    drawn, undrawn = split_drawable(family, payload.blocks)
    return payload.model_copy(update={"blocks": drawn, "undrawn": undrawn})
