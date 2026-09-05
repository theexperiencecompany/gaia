"""Hand-designed HTML email templates for GAIA notification emails.

Table-based layout, inline styles only — required for email-client
compatibility (most clients strip <style> blocks and all JavaScript). Three
templates, selected by the email channel adapter off a notification's
``metadata["kind"]``: daily brief, weekly digest, and a plain-notification
fallback. The briefing templates render straight from the same
``BriefingPayload`` dict the OpenUI dashboard card renders — no LLM
reformatting, no Jinja: the payload is already a validated dict of
primitives, so plain string composition (with everything hand-escaped) is
enough.
"""

from __future__ import annotations

from html import escape
from typing import Any

_ROMAN_NUMERALS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")

_BG = "#0a0a0a"
_CARD_BG = "#141414"
_BORDER = "#262626"
_TEXT = "#f4f4f5"
_MUTED = "#a1a1aa"
_SERIF_STACK = "'Playfair Display', Georgia, 'Times New Roman', serif"
_SANS_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

# Degree offsets and lightness for the 6 gradient stops, relative to the
# payload's hue — gives every day's masthead band a distinct identity while
# keeping the same editorial layout (per the "hue varies, template doesn't"
# design requirement).
_GRADIENT_OFFSETS = (-40, -15, 0, 20, 45, 70)
_GRADIENT_LIGHTNESS = (58, 50, 46, 50, 58, 64)


_DEFAULT_HUE = 210


def _gradient_stops(hue: int) -> str:
    return ", ".join(
        f"hsl({(hue + offset) % 360}, 70%, {lightness}%)"
        for offset, lightness in zip(_GRADIENT_OFFSETS, _GRADIENT_LIGHTNESS, strict=True)
    )


def _masthead(kicker: str, date: str) -> str:
    return f"""
    <tr>
      <td style="padding: 32px 40px 0; font-family: {_SANS_STACK};">
        <div style="font-size: 11px; letter-spacing: 3px; text-transform: uppercase; color: {_MUTED};">
          {escape(kicker)}
        </div>
        <div style="font-size: 12px; color: {_MUTED}; margin-top: 4px;">{escape(date)}</div>
      </td>
    </tr>
    """


def _gradient_band(hue: int) -> str:
    return f"""
    <tr>
      <td style="padding: 16px 40px 0;">
        <div style="height: 6px; border-radius: 3px; background: linear-gradient(90deg, {_gradient_stops(hue)});"></div>
      </td>
    </tr>
    """


def _headline_block(headline: str, lede: str) -> str:
    return f"""
    <tr>
      <td style="padding: 24px 40px 0; font-family: {_SANS_STACK};">
        <div style="font-family: {_SERIF_STACK}; font-style: italic; font-size: 28px; line-height: 1.25; color: {_TEXT};">
          {escape(headline)}
        </div>
        <div style="font-size: 15px; line-height: 1.6; color: {_MUTED}; margin-top: 12px;">
          {escape(lede)}
        </div>
      </td>
    </tr>
    """


def _stat_row(stats: list[dict[str, Any]]) -> str:
    if not stats:
        return ""
    cells = []
    for stat in stats:
        value = escape(str(stat.get("value", "")))
        label = escape(str(stat.get("label", "")))
        delta = stat.get("delta")
        delta_html = (
            f'<div style="font-size: 11px; color: {_MUTED}; margin-top: 2px;">{escape(str(delta))}</div>'
            if delta
            else ""
        )
        cells.append(
            f"""
        <td style="padding: 16px 20px; border: 1px solid {_BORDER}; text-align: center;">
          <div style="font-family: {_SERIF_STACK}; font-size: 22px; color: {_TEXT};">{value}</div>
          <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: {_MUTED}; margin-top: 4px;">{label}</div>
          {delta_html}
        </td>
        """
        )
    return f"""
    <tr>
      <td style="padding: 24px 40px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
          <tr>{"".join(cells)}</tr>
        </table>
      </td>
    </tr>
    """


def _sections_block(sections: list[dict[str, Any]]) -> str:
    if not sections:
        return ""
    blocks = []
    for i, section in enumerate(sections):
        numeral = escape(
            str(section.get("numeral") or _ROMAN_NUMERALS[min(i, len(_ROMAN_NUMERALS) - 1)])
        )
        title = escape(str(section.get("title", "")).upper())
        items = section.get("items") or []
        item_rows = "".join(
            f'<div style="padding: 8px 0; border-bottom: 1px solid {_BORDER}; font-size: 14px; color: {_TEXT};">'
            f"{escape(str(item.get('text', '')))}</div>"
            for item in items
        )
        blocks.append(
            f"""
        <div style="margin-top: 28px;">
          <div style="font-family: {_SERIF_STACK}; font-size: 13px; color: {_MUTED}; letter-spacing: 2px;">
            {numeral}. {title}
          </div>
          <div style="margin-top: 8px;">{item_rows}</div>
        </div>
        """
        )
    return f"""
    <tr>
      <td style="padding: 8px 40px 0; font-family: {_SANS_STACK};">
        {"".join(blocks)}
      </td>
    </tr>
    """


def _caption_block(caption: str) -> str:
    if not caption:
        return ""
    return f"""
    <tr>
      <td style="padding: 32px 40px 0; font-family: {_SERIF_STACK}; font-style: italic; font-size: 13px; color: {_MUTED};">
        {escape(caption)}
      </td>
    </tr>
    """


def _unsubscribe_footer(unsubscribe_url: str) -> str:
    return f"""
    <tr>
      <td style="padding: 32px 40px 40px; font-family: {_SANS_STACK}; font-size: 11px; color: {_MUTED}; border-top: 1px solid {_BORDER}; margin-top: 24px;">
        GAIA &middot; <a href="{escape(unsubscribe_url)}" style="color: {_MUTED};">Unsubscribe from these emails</a>
      </td>
    </tr>
    """


def _wrap(body_rows: str) -> str:
    return f"""<!doctype html>
<html>
  <body style="margin: 0; padding: 0; background: {_BG};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background: {_BG};">
      <tr>
        <td align="center" style="padding: 40px 16px;">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; width: 100%; background: {_CARD_BG}; border: 1px solid {_BORDER}; border-radius: 16px; overflow: hidden;">
            {body_rows}
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _render_briefing_email(
    payload: dict[str, Any], default_kicker: str, unsubscribe_url: str
) -> str:
    hue = payload.get("hue")
    rows = (
        _masthead(payload.get("kicker") or default_kicker, str(payload.get("date", "")))
        + _gradient_band(int(hue) if hue is not None else _DEFAULT_HUE)
        + _headline_block(str(payload.get("headline", "")), str(payload.get("lede", "")))
        + _stat_row(payload.get("stats") or [])
        + _sections_block(payload.get("sections") or [])
        + _caption_block(str(payload.get("caption", "")))
        + _unsubscribe_footer(unsubscribe_url)
    )
    return _wrap(rows)


def render_daily_brief_email(payload: dict[str, Any], unsubscribe_url: str) -> str:
    """Renders the daily brief email from a validated BriefingPayload dict."""
    return _render_briefing_email(payload, "Daily Brief", unsubscribe_url)


def render_weekly_digest_email(payload: dict[str, Any], unsubscribe_url: str) -> str:
    """Renders the weekly digest email — same editorial shape as the daily brief."""
    return _render_briefing_email(payload, "Weekly Digest", unsubscribe_url)


def render_plain_notification_email(title: str, body: str, unsubscribe_url: str) -> str:
    """Renders a plain (non-briefing) notification email: title + body."""
    rows = f"""
    <tr>
      <td style="padding: 40px 40px 0; font-family: {_SANS_STACK};">
        <div style="font-family: {_SERIF_STACK}; font-style: italic; font-size: 22px; color: {_TEXT};">
          {escape(title)}
        </div>
        <div style="font-size: 15px; line-height: 1.6; color: {_MUTED}; margin-top: 12px;">
          {escape(body)}
        </div>
      </td>
    </tr>
    """ + _unsubscribe_footer(unsubscribe_url)
    return _wrap(rows)
