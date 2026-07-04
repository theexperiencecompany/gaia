"""Assemble a briefing email whose body IS the rendered edition.

The high-craft edition template (``editions/``) targets a real browser, so it
leans on modern CSS that Gmail/Outlook strip. Rather than degrade the design to
email-safe HTML, we rasterize the edition to a PNG (``render.py``) and embed it
inline in the email, with a small, genuinely email-safe **action strip** beneath
it (real links + alt text) so approvals stay one tap and the mail degrades
gracefully when images are blocked.

Nothing here performs an outward action — links deep-link into the app where the
user approves. The email can never approve or send on its own.
"""

from __future__ import annotations

import base64
from datetime import date as date_cls
from html import escape

from app.config.settings import settings
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.services.briefing.editions.broadsheet import render_edition
from app.services.briefing.render import render_html_to_image
from shared.py.wide_events import log

# JPEG quality tuned so the base64 image + strip stays under Gmail's ~102KB clip
# (a clipped mail truncates the data URI → broken image). Downscaled to a 640px
# display the compression is invisible. Full-res PNG is the R2/hosted follow-up.
_EMAIL_JPEG_QUALITY = 62

# Edition numbering is cosmetic newspaper furniture; anchor it to a fixed epoch so
# the number is stable and monotonic across days without any stored counter.
_EDITION_EPOCH = date_cls(2026, 1, 1)
_EDITION_WIDTH = 1180
_PAPER = "#f7f5ef"
_PUBLIC_APP_URL = "https://heygaia.io"


def _public_app_url() -> str:
    """The app URL to link to from email — never localhost. An email is always
    opened away from the dev host, so a localhost FRONTEND_URL must fall back to
    the public origin or every link in the mail is dead."""
    url = (settings.FRONTEND_URL or "").rstrip("/")
    if not url or "localhost" in url or "127.0.0.1" in url:
        return _PUBLIC_APP_URL
    return url


def _edition_no(iso_date: str) -> int:
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
    if link.startswith("http://") or link.startswith("https://"):
        return link
    base = _public_app_url()
    return f"{base}/{link.lstrip('/')}"


def _action_strip(payload: dict, unsubscribe_url: str) -> str:
    """Email-safe (table + inline-styled) strip under the image: primary CTA,
    per-proposal review links, unsubscribe. Deep-links only — never approves."""
    app_url = _public_app_url()
    actions = _action_items(payload)

    rows = [
        '<tr><td align="center" style="padding:22px 24px 8px 24px;">'
        f'<a href="{escape(app_url)}" '
        'style="display:inline-block;background:#8a1c1c;color:#ffffff;'
        "text-decoration:none;font:600 15px/1.2 -apple-system,Helvetica,Arial,sans-serif;"
        'letter-spacing:.02em;padding:13px 28px;border-radius:2px;">'
        "Open today&#39;s brief in GAIA</a></td></tr>"
    ]

    if actions:
        links = []
        for item in actions:
            href = _resolve_link(item.get("link")) or app_url
            text = escape((item.get("text") or "").strip())
            links.append(
                f'<div style="margin:6px 0;font:400 13px/1.5 -apple-system,Helvetica,Arial,sans-serif;color:#333;">'
                f"&#8226;&nbsp;{text} &nbsp;"
                f'<a href="{escape(href)}" style="color:#8a1c1c;text-decoration:none;font-weight:600;">Review</a>'
                f"</div>"
            )
        rows.append(
            '<tr><td style="padding:6px 32px 4px 32px;">'
            '<div style="font:600 11px/1.4 -apple-system,Helvetica,Arial,sans-serif;'
            "letter-spacing:.12em;text-transform:uppercase;color:#8a1c1c;"
            'border-top:1px solid #ddd;padding-top:12px;">Waiting on your call</div>'
            + "".join(links)
            + "</td></tr>"
        )

    rows.append(
        '<tr><td align="center" style="padding:18px 24px 26px 24px;">'
        '<div style="font:400 11px/1.5 -apple-system,Helvetica,Arial,sans-serif;color:#999;">'
        "You&#39;re getting this because GAIA works your day. "
        f'<a href="{escape(unsubscribe_url)}" style="color:#999;">Unsubscribe</a>.'
        "</div></td></tr>"
    )

    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="max-width:640px;margin:0 auto;background:{_PAPER};">' + "".join(rows) + "</table>"
    )


async def render_edition_email(
    payload: dict,
    *,
    kind: str,
    generated_local: str = "",
    tz_label: str = "",
    unsubscribe_url: str,
) -> str:
    """Render the edition to an inline PNG and wrap it with the action strip.

    Returns the full email HTML. Raises on render failure so the caller can fall
    back to the plain HTML briefing template.
    """
    edition_no = _edition_no(payload.get("date", ""))
    edition_html = render_edition(
        payload,
        edition_no=edition_no,
        generated_local=generated_local,
        tz_label=tz_label,
    )
    # JPEG at 1x keeps the inlined base64 under Gmail's ~102KB clip; at a 640px
    # display the 1180px source is downscaled ~1.8x so the compression is unseen.
    # TODO: host the full-res PNG (R2 / signed API route) and reference by URL.
    image = await render_html_to_image(
        edition_html,
        width=_EDITION_WIDTH,
        device_scale_factor=1,
        image_format="jpeg",
        quality=_EMAIL_JPEG_QUALITY,
    )
    b64 = base64.b64encode(image).decode("ascii")
    log.debug(
        "briefing.edition_email.rendered", kind=kind, edition_no=edition_no, image_bytes=len(image)
    )

    alt = escape(
        f"{payload.get('headline', 'Your GAIA brief')} — {payload.get('lede', '')}".strip(" —")
    )
    app_url = _public_app_url()

    return (
        f'<div style="margin:0;padding:0;background:{_PAPER};">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_PAPER};">'
        '<tr><td align="center" style="padding:0;">'
        f'<a href="{escape(app_url)}" style="text-decoration:none;">'
        f'<img src="data:image/jpeg;base64,{b64}" alt="{alt}" width="640" '
        'style="display:block;width:100%;max-width:640px;height:auto;border:0;" /></a>'
        "</td></tr></table>" + _action_strip(payload, unsubscribe_url) + "</div>"
    )


def is_edition_kind(kind: str | None) -> bool:
    """Both daily and weekly briefings render as editions."""

    return kind in (NOTIFICATION_KIND_BRIEFING_DAILY, NOTIFICATION_KIND_BRIEFING_WEEKLY)
