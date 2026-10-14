"""Assemble a briefing email whose body IS the rendered edition.

The edition targets a real browser, so it is rasterized to an image (render.py),
hosted on the CDN, and referenced by URL (Gmail blocks base64 data: images). Beneath
it sits a small email-safe action strip of deep links into the app; the email can
never approve or send on its own.
"""

from __future__ import annotations

import asyncio
from datetime import date as date_cls
from html import escape

from app.config.settings import settings
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.models.briefing_models import BriefingItem, BriefingPayload
from app.services.briefing.editions import paper_selector, render_edition, renderer_for
from app.services.briefing.render import ImageRenderOptions, render_html_to_image
from app.services.upload_service import upload_file_to_cloudinary
from shared.py.wide_events import log

# The edition is hosted (Cloudinary) and referenced by URL, so it renders in
# Gmail (which blocks base64 data: URIs) with no size ceiling — full-res 2x PNG.
_EMAIL_IMAGE_SCALE = 2

# Edition numbering is cosmetic furniture; anchor it to a fixed epoch so the
# number is stable and monotonic across days without any stored counter.
_EDITION_EPOCH = date_cls(2026, 1, 1)
_EDITION_WIDTH = 1180
_PUBLIC_APP_URL = "https://heygaia.io"

# GAIA email palette: dark-first, single cyan accent (matches DESIGN.md).
_BG = "#000000"
_ACCENT = "#00bbff"
_ACCENT_FG = "#000000"
_TEXT = "#f4f4f5"
_MUTED = "#a1a1aa"
_HAIRLINE = "#27272a"


def _public_app_url() -> str:
    """Return the app URL to link to from email — never localhost.

    An email is always opened away from the dev host, so a localhost FRONTEND_URL must
    fall back to the public origin or every link in the mail is dead.
    """
    url = (settings.FRONTEND_URL or "").rstrip("/")
    if not url or "localhost" in url or "127.0.0.1" in url:
        return _PUBLIC_APP_URL
    return url


def _edition_no(iso_date: str) -> int:
    try:
        return (date_cls.fromisoformat(iso_date) - _EDITION_EPOCH).days + 1
    except ValueError:
        return 1


def _action_items(payload: BriefingPayload) -> list[BriefingItem]:
    """Items waiting on the user, each a call to action in the strip."""
    return [item for section in payload.sections for item in section.items if item.kind == "you"]


def _resolve_link(link: str | None) -> str | None:
    if not link:
        return None
    # False positive: this is a scheme-prefix check classifying already-absolute
    # URLs, not an insecure outbound request.
    if link.startswith(("http://", "https://")):  # NOSONAR python:S5332
        return link
    base = _public_app_url()
    return f"{base}/{link.lstrip('/')}"


def _action_strip(payload: BriefingPayload, unsubscribe_url: str) -> str:
    """Build the email-safe (table + inline-styled) strip under the image.

    It holds the primary CTA, per-proposal review links and unsubscribe. Deep-links
    only — never approves.
    """
    app_url = _public_app_url()
    actions = _action_items(payload)

    sans = "Inter,-apple-system,Helvetica,Arial,sans-serif"
    rows = [
        (
            f'<tr><td align="center" style="padding:24px 24px 8px 24px;">'
            f'<a href="{escape(app_url)}" '
            f'style="display:inline-block;background:{_ACCENT};color:{_ACCENT_FG};'
            f"text-decoration:none;font:600 15px/1.2 {sans};"
            'padding:13px 30px;border-radius:10px;">'
            "Open today&#39;s brief in GAIA</a></td></tr>"
        )
    ]

    if actions:
        links = []
        for item in actions:
            href = _resolve_link(item.link) or app_url
            text = escape(item.text.strip())
            links.append(
                f'<div style="margin:7px 0;font:400 13px/1.5 {sans};color:{_TEXT};">'
                f"{text} &nbsp;"
                f'<a href="{escape(href)}" style="color:{_ACCENT};text-decoration:none;font-weight:600;">Review</a>'
                f"</div>"
            )
        rows.append(
            f'<tr><td style="padding:8px 32px 4px 32px;">'
            f'<div style="font:600 12px/1.4 {sans};color:{_MUTED};'
            f'border-top:1px solid {_HAIRLINE};padding-top:14px;">Waiting on your call</div>'
            + "".join(links)
            + "</td></tr>"
        )

    rows.append(
        f'<tr><td align="center" style="padding:20px 24px 28px 24px;">'
        f'<div style="font:400 11px/1.5 {sans};color:{_MUTED};">'
        "You&#39;re getting this because GAIA works your day. "
        f'<a href="{escape(unsubscribe_url)}" style="color:{_MUTED};">Unsubscribe</a>.'
        "</div></td></tr>"
    )

    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="max-width:640px;margin:0 auto;background:{_BG};">' + "".join(rows) + "</table>"
    )


async def render_edition_png(payload: BriefingPayload, *, crop_to_paper: bool) -> bytes:
    """Render the edition as a PNG.

    crop_to_paper cuts it to the family's paper (the chat image); the email keeps the
    full composition.
    """
    family = payload.template_family
    # The classic edition (and every legacy payload without a family) renders
    # via render_edition.
    render = renderer_for(family) or render_edition
    edition_html = render(payload, edition_no=_edition_no(payload.date), generated_local="")
    return await render_html_to_image(
        edition_html,
        ImageRenderOptions(
            width=_EDITION_WIDTH,
            device_scale_factor=_EMAIL_IMAGE_SCALE,
            clip_selector=paper_selector(family) if crop_to_paper else None,
        ),
    )


async def host_edition_image(
    payload: BriefingPayload, *, user_id: str, kind: str, crop_to_paper: bool
) -> str:
    """Render the edition and host it on the CDN; returns the image URL.

    One public id per user, kind, date and crop, uploaded with overwrite, so a re-run
    replaces the same asset.
    """
    image = await render_edition_png(payload, crop_to_paper=crop_to_paper)
    crop = "_chat" if crop_to_paper else ""
    public_id = f"briefing/editions/{user_id}/{kind}_{payload.date}{crop}"
    image_url = await asyncio.to_thread(upload_file_to_cloudinary, public_id, file_data=image)
    log.debug(
        "briefing.edition_image.hosted",
        kind=kind,
        crop_to_paper=crop_to_paper,
        image_bytes=len(image),
        url=image_url,
    )
    return image_url


async def render_edition_email(
    payload: BriefingPayload,
    *,
    kind: str,
    user_id: str,
    unsubscribe_url: str,
    preheader: str = "",
) -> str:
    """Render the edition to a hosted image and wrap it with the action strip.

    Raises on any render/upload failure so the caller can fall back to the plain HTML
    template.
    """
    image_url = await host_edition_image(payload, user_id=user_id, kind=kind, crop_to_paper=False)

    alt = escape(f"{payload.headline} — {payload.lede}".strip(" —"))
    app_url = _public_app_url()

    # The inbox preview line (the skim's asks + overnight sentence), hidden in
    # the body so clients show it under the subject instead of image alt text.
    preheader_html = (
        '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">'
        f"{escape(preheader)}</div>"
        if preheader
        else ""
    )
    return (
        f'<div style="margin:0;padding:0;background:{_BG};">{preheader_html}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BG};">'
        '<tr><td align="center" style="padding:0;">'
        f'<a href="{escape(app_url)}" style="text-decoration:none;">'
        f'<img src="{escape(image_url)}" alt="{alt}" width="640" '
        'style="display:block;width:100%;max-width:640px;height:auto;border:0;" /></a>'
        "</td></tr></table>" + _action_strip(payload, unsubscribe_url) + "</div>"
    )


def is_edition_kind(kind: str | None) -> bool:
    """Both daily and weekly briefings render as editions."""

    return kind in (NOTIFICATION_KIND_BRIEFING_DAILY, NOTIFICATION_KIND_BRIEFING_WEEKLY)
