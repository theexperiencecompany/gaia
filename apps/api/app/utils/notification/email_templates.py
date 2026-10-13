"""Email renderings of notifications: the briefing emails and the plain fallback.

The briefing emails render the same validated ``BriefingPayload`` the dashboard
card renders, through the Jinja templates in ``app/templates`` (``briefing_daily``
/ ``briefing_weekly`` on ``_briefing_email.html``, which extends the shared
``_base_email.html``). This module only shapes the payload into what the
template prints: one link per item, a readable date, the kind's accent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.config.settings import settings
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.models.briefing_models import BRIEFING_ITEM_LABELS, BriefingItemKind, BriefingPayload
from app.services.email.service import render_email_template

# Inter first (loaded by the template's <link> where the client allows it),
# then each platform's system UI face.
EMAIL_FONT_STACK = (
    "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
)

# The dot beside each item, by what the item asks of the user.
_ITEM_ACCENTS: dict[BriefingItemKind, str] = {
    "you": "#00bbff",
    "gaia": "#a1a1aa",
    "lookback": "#22c55e",
    "failed": "#ef4444",
    "note": "#f59e0b",
}


@dataclass(frozen=True)
class _BriefingVariant:
    template: str
    cta_label: str


_VARIANTS: dict[str, _BriefingVariant] = {
    NOTIFICATION_KIND_BRIEFING_DAILY: _BriefingVariant("briefing_daily.html", "Open today's brief"),
    NOTIFICATION_KIND_BRIEFING_WEEKLY: _BriefingVariant(
        "briefing_weekly.html", "See your week in GAIA"
    ),
}


@dataclass(frozen=True)
class EmailItem:
    text: str
    href: str
    label: str
    accent: str


@dataclass(frozen=True)
class EmailSection:
    title: str
    items: list[EmailItem]


@dataclass(frozen=True)
class EmailStat:
    value: str
    label: str


@dataclass(frozen=True)
class BriefingEmail:
    """Everything a briefing template prints, already escaped-safe primitives."""

    kicker: str
    date_label: str
    headline: str
    lede: str
    preheader: str
    caption: str
    stats: list[EmailStat]
    sections: list[EmailSection]
    app_url: str
    logo_url: str
    cta_url: str
    cta_label: str
    manage_url: str


def is_briefing_kind(kind: str | None) -> bool:
    return kind in _VARIANTS


def briefing_url() -> str:
    return f"{settings.FRONTEND_URL}/briefings"


def _item_href(todo_id: str | None, link: str | None) -> str:
    """Where tapping an item lands: its own artifact link when the run minted
    one, else the todo it is bound to, else the brief in the app."""
    if link:
        return link
    if todo_id:
        return f"{settings.FRONTEND_URL}/todos?todoId={todo_id}"
    return briefing_url()


def _date_label(iso_date: str) -> str:
    day = date.fromisoformat(iso_date)
    return f"{day:%A}, {day:%B} {day.day}"


def build_briefing_email(payload: BriefingPayload, kind: str) -> tuple[BriefingEmail, str]:
    """Shape a payload into the template's view and pick the variant's template."""
    variant = _VARIANTS[kind]
    sections = [
        EmailSection(
            title=section.title,
            items=[
                EmailItem(
                    text=item.text,
                    href=_item_href(item.todo_id, item.link),
                    label=BRIEFING_ITEM_LABELS[item.kind],
                    accent=_ITEM_ACCENTS[item.kind],
                )
                for item in section.items
            ],
        )
        for section in payload.sections
        if section.items
    ]
    view = BriefingEmail(
        kicker=payload.kicker,
        date_label=_date_label(payload.date),
        headline=payload.headline,
        lede=payload.lede,
        preheader=payload.lede,
        caption=payload.caption,
        stats=[EmailStat(value=s.value, label=s.label) for s in payload.stats],
        sections=sections,
        app_url=settings.FRONTEND_URL,
        logo_url=f"{settings.HOST}/static/logo.png",
        cta_url=briefing_url(),
        cta_label=variant.cta_label,
        manage_url=f"{settings.FRONTEND_URL}/settings/notifications",
    )
    return view, variant.template


def render_briefing_email(
    payload: dict[str, Any], kind: str, unsubscribe_url: str
) -> tuple[str, str]:
    """``(subject, html)`` for a daily brief or weekly recap notification.

    The payload arrives as the notification's ``rich_content`` dict; it is
    re-validated here so a malformed payload fails the send loudly instead of
    rendering a half-empty email.
    """
    brief = BriefingPayload.model_validate(payload)
    view, template = build_briefing_email(brief, kind)
    html = render_email_template(
        template, brief=view, fonts=EMAIL_FONT_STACK, unsubscribe_url=unsubscribe_url
    )
    return brief.headline, html


def render_notification_email(title: str, body: str, unsubscribe_url: str) -> str:
    """A plain notification as a short GAIA note with a link back into the app."""
    return render_email_template(
        "notification_email.html",
        title=title,
        body=body,
        cta_url=settings.FRONTEND_URL,
        cta_label="Open GAIA",
        unsubscribe_url=unsubscribe_url,
    )
