"""Assemble a briefing email whose body IS the rendered edition.

The high-craft edition template (``editions/``) targets a real browser, so it
leans on modern CSS that Gmail/Outlook strip. Rather than degrade the design to
email-safe HTML, we rasterize the edition to a PNG (``render.py``), host it on
the CDN, and reference it by URL — Gmail blocks base64 ``data:`` images and a
hosted URL has no size ceiling, so the full-res edition renders everywhere.
Beneath it sits a small, genuinely email-safe **action strip** (real links +
alt text) so approvals stay one tap and the mail degrades if images are off.

Nothing here performs an outward action — links deep-link into the app where the
user approves. The email can never approve or send on its own.
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
from app.services.briefing.editions import render_edition, renderer_for
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
    """The app URL to link to from email — never localhost. An email is always
    opened away from the dev host, so a localhost FRONTEND_URL must fall back to
    the public origin or every link in the mail is dead."""
    url = (settings.FRONTEND_URL or "").rstrip("/")
    if not url or "localhost" in url or "127.0.0.1" in url:
        return _PUBLIC_APP_URL
    return url


def _edition_no(iso_date: str | None) -> int:
    if not iso_date:
        return 1
    try:
        return (date_cls.fromisoformat(iso_date) - _EDITION_EPOCH).days + 1
    except ValueError:
        return 1


def _action_items(payload: dict) -> list[dict]:
    """Proposal / needs-you items that carry a call to action, for the strip."""
    out: list[dict] = []
    for section in payload.get("sections", []):
        for item in section.get("items", []):
            if item.get("kind") in ("proposal", "needs_you"):
                out.append(item)
    return out


def _resolve_link(link: str | None) -> str | None:
    if not link:
        return None
    # False positive: this is a scheme-prefix check classifying already-absolute
    # URLs, not an insecure outbound request.
    if link.startswith(("http://", "https://")):  # NOSONAR python:S5332
        return link
    base = _public_app_url()
    return f"{base}/{link.lstrip('/')}"


def _action_strip(payload: dict, unsubscribe_url: str) -> str:
    """Email-safe (table + inline-styled) strip under the image: primary CTA,
    per-proposal review links, unsubscribe. Deep-links only — never approves."""
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
            href = _resolve_link(item.get("link")) or app_url
            text = escape((item.get("text") or "").strip())
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


async def render_edition_email(
    payload: dict,
    *,
    kind: str,
    user_id: str,
    generated_local: str = "",
    tz_label: str = "",
    unsubscribe_url: str,
) -> str:
    """Render the edition to a hosted image and wrap it with the action strip.

    The full-res PNG is uploaded to the CDN and referenced by URL — Gmail blocks
    base64 ``data:`` images, and a hosted URL has no size ceiling. Raises on any
    render/upload failure so the caller can fall back to the plain HTML template.
    """
    edition_no = _edition_no(payload.get("date"))
    # Weekly editions carry a rotation-assigned template family; the classic
    # edition (and every daily/legacy payload) renders via render_edition.
    family_renderer = renderer_for(payload.get("template_family"))
    render = family_renderer if family_renderer is not None else render_edition
    edition_html = render(
        payload,
        edition_no=edition_no,
        generated_local=generated_local,
        tz_label=tz_label,
    )
    image = await render_html_to_image(
        edition_html,
        # ImageRenderOptions already defaults to this width and scale, so
        # dropping either keyword builds an identical object — equivalent
        # mutants. Stated anyway: the email's dimensions are this module's
        # decision, not render.py's.
        ImageRenderOptions(  # pragma: no mutate
            width=_EDITION_WIDTH, device_scale_factor=_EMAIL_IMAGE_SCALE
        ),
    )
    public_id = f"briefing/editions/{user_id}/{kind}_{payload.get('date', 'latest')}"
    image_url = await asyncio.to_thread(upload_file_to_cloudinary, public_id, file_data=image)
    log.debug(
        "briefing.edition_email.rendered",
        kind=kind,
        edition_no=edition_no,
        image_bytes=len(image),
        url=image_url,
    )

    alt = escape(
        f"{payload.get('headline', 'Your GAIA brief')} — {payload.get('lede', '')}".strip(" —")
    )
    app_url = _public_app_url()

    return (
        f'<div style="margin:0;padding:0;background:{_BG};">'
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
