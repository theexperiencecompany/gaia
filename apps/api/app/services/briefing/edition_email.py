"""Render and host the briefing edition image, and wrap it as an email.

The edition targets a real browser, so it is rasterized to an image (render.py),
hosted on the CDN once when the brief is generated, and referenced by URL (Gmail
blocks base64 data: images). The email embeds that stored image, linked to the
brief's heygaia.link, above the brief's written message as real text and a deep link
into the app; the email can never approve or send on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls
from html import escape

import cloudinary.utils

from app.constants.briefing import (
    EDITION_DELIVERY_MAX_WIDTH_PX,
    EDITION_JPG_BACKGROUND,
    WEEKLY_FAMILY,
    EditionDeliveryFormat,
)
from app.constants.files import BlobKind
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.models.briefing_models import BriefingPayload
from app.services.blob_store import CloudinaryBlobStore
from app.services.briefing.editions import EXPLORER_RENDERER, edition_frame
from app.services.briefing.message import MESSAGE_LINK_RE, delivered_message, preheader
from app.services.briefing.render import ImageRenderOptions, render_html_to_image
from shared.py.wide_events import log

# Edition numbering is cosmetic furniture; anchor it to a fixed epoch so the
# number is stable and monotonic across days without any stored counter.
_EDITION_EPOCH = date_cls(2026, 1, 1)

EDITION_IMAGE_STORE = CloudinaryBlobStore()

# GAIA email palette: dark-first, single cyan accent (matches DESIGN.md).
_BG = "#000000"
_ACCENT = "#00bbff"
_ACCENT_FG = "#000000"
_TEXT = "#f4f4f5"
_MUTED = "#a1a1aa"
_SANS = "Inter,-apple-system,Helvetica,Arial,sans-serif"

# What the footer says is switched on, so the reader knows which setting sends the mail.
_DAILY_SUBSCRIPTION = "daily briefs"
_WEEKLY_SUBSCRIPTION = "weekly digests"


def _edition_no(iso_date: str) -> int:
    """Return the edition number: days since the epoch; an unparseable date raises."""
    return (date_cls.fromisoformat(iso_date) - _EDITION_EPOCH).days + 1


def _line_html(line: str) -> str:
    """Escape one message line, setting each linked phrase as an anchor on the phrase."""
    out, end = [], 0
    for match in MESSAGE_LINK_RE.finditer(line):
        out.append(escape(line[end : match.start()]))
        out.append(
            f'<a href="{escape(match.group(2))}" style="color:{_ACCENT};">'
            f"{escape(match.group(1))}</a>"
        )
        end = match.end()
    out.append(escape(line[end:]))
    return "".join(out)


def _message_html(message: str) -> str:
    """Set the written message as email text: a paragraph per blank-line block, breaks kept."""
    paragraphs = [block.strip() for block in message.split("\n\n") if block.strip()]
    return "".join(
        f'<p style="margin:0 0 14px 0;font:400 15px/1.6 {_SANS};color:{_TEXT};">'
        + "<br>".join(_line_html(line.strip()) for line in block.splitlines())
        + "</p>"
        for block in paragraphs
    )


def _text_strip(message: str, brief_url: str, unsubscribe_url: str, subscription: str) -> str:
    """Build the email-safe (table + inline-styled) strip under the image.

    It holds the written message as real text, so the email reads with images off, then
    the CTA into the brief's page and unsubscribe. Deep-links only, never approves.
    """
    rows = [
        f'<tr><td style="padding:24px 32px 4px 32px;">{_message_html(message)}</td></tr>',
        (
            f'<tr><td align="center" style="padding:12px 24px 8px 24px;">'
            f'<a href="{escape(brief_url)}" '
            f'style="display:inline-block;background:{_ACCENT};color:{_ACCENT_FG};'
            f"text-decoration:none;font:600 15px/1.2 {_SANS};"
            'padding:13px 30px;border-radius:10px;">'
            "Open today&#39;s brief in GAIA</a></td></tr>"
        ),
        (
            f'<tr><td align="center" style="padding:20px 24px 28px 24px;">'
            f'<div style="font:400 11px/1.5 {_SANS};color:{_MUTED};">'
            f"You get this because {subscription} are on in GAIA. "
            f'<a href="{escape(unsubscribe_url)}" style="color:{_MUTED};">Unsubscribe</a>.'
            "</div></td></tr>"
        ),
    ]
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="max-width:600px;margin:0 auto;background:{_BG};">' + "".join(rows) + "</table>"
    )


async def render_edition_png(payload: BriefingPayload) -> bytes:
    """Render the edition as a PNG cropped tight to its paper (editions.edition_frame)."""
    family = payload.template_family
    render = EXPLORER_RENDERER[family]
    edition_html = render(payload, edition_no=_edition_no(payload.date), generated_local="")
    frame = edition_frame(family)
    # The image is hosted and referenced by URL (Gmail blocks base64 data: URIs),
    # so its size has no ceiling.
    return await render_html_to_image(
        edition_html,
        ImageRenderOptions(
            width=frame.width,
            device_scale_factor=frame.device_scale_factor,
            clip_selector=frame.clip_selector,
            trim_margin_px=frame.trim_margin_px,
            omit_background=frame.transparent_desk,
        ),
    )


@dataclass(frozen=True)
class HostedEditionImage:
    """Delivery URLs for one hosted edition; the original upload stays untouched."""

    display_url: str
    chat_url: str


def edition_delivery_url(public_id: str, fetch_format: EditionDeliveryFormat) -> str:
    """Build the CDN URL serving the edition at display size instead of the full original."""
    # The SDK is untyped; it returns (url, options left after building the URL).
    delivery: tuple[str, dict[str, object]] = cloudinary.utils.cloudinary_url(
        public_id,
        secure=True,
        fetch_format=fetch_format.value,
        quality="auto",
        width=EDITION_DELIVERY_MAX_WIDTH_PX,
        crop="limit",
        background=EDITION_JPG_BACKGROUND if fetch_format is EditionDeliveryFormat.JPG else None,
    )
    return delivery[0]


async def host_edition_image(
    payload: BriefingPayload, *, owner_id: str, render_key: str
) -> HostedEditionImage:
    """Render the edition, host it on the CDN under render_key, and return its delivery URLs.

    The display URL serves the in-app page and the email, the chat URL the chat post.
    The URL goes out in emails and on public brief links, so its path is the caller's
    random key alone, never the user, kind or date.
    """
    image = await render_edition_png(payload)
    public_id = f"briefing/editions/{render_key}"
    # The delivery URLs are Cloudinary transformations, so the edition lives there.
    original_url = await EDITION_IMAGE_STORE.put(
        owner_id,
        public_id,
        image,
        resource_type="image",
        kind=BlobKind.GENERATED_IMAGE,
        content_type="image/png",
    )
    log.debug("briefing.edition_image.hosted", image_bytes=len(image), url=original_url)
    return HostedEditionImage(
        display_url=edition_delivery_url(public_id, EditionDeliveryFormat.AUTO),
        chat_url=edition_delivery_url(public_id, EditionDeliveryFormat.JPG),
    )


def render_edition_email(
    payload: BriefingPayload,
    *,
    image_url: str,
    brief_url: str,
    unsubscribe_url: str,
) -> str:
    """Wrap the already-hosted edition image, linked to the brief's heygaia.link, above the message."""
    alt = escape(f"{payload.headline} — {payload.lede}".strip(" —"))

    # The inbox preview line, hidden in the body so clients show it under the
    # subject instead of image alt text.
    preheader_html = (
        '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">'
        f"{escape(preheader(payload))}</div>"
    )
    return (
        f'<div style="margin:0;padding:0;background:{_BG};">{preheader_html}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BG};">'
        '<tr><td align="center" style="padding:0;">'
        f'<a href="{escape(brief_url)}" style="text-decoration:none;">'
        f'<img src="{escape(image_url)}" alt="{alt}" width="600" '
        'style="display:block;width:100%;max-width:600px;height:auto;border:0;" /></a>'
        "</td></tr></table>"
        + _text_strip(
            delivered_message(payload),
            brief_url,
            unsubscribe_url,
            _WEEKLY_SUBSCRIPTION
            if payload.template_family == WEEKLY_FAMILY
            else _DAILY_SUBSCRIPTION,
        )
        + "</div>"
    )


def is_edition_kind(kind: str | None) -> bool:
    """Both daily and weekly briefings render as editions."""

    return kind in (NOTIFICATION_KIND_BRIEFING_DAILY, NOTIFICATION_KIND_BRIEFING_WEEKLY)
