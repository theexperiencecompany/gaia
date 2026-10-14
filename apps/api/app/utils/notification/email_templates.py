"""Hand-designed HTML email templates for GAIA notification emails.

Table-based layout, inline styles only, for email-client compatibility. Three
templates, selected by the email channel adapter off metadata["kind"]: daily brief,
weekly digest, and a plain-notification fallback. The briefing templates render from
the BriefingPayload with plain, hand-escaped string composition.
"""

from __future__ import annotations

from html import escape

from app.models.briefing_models import BriefingPayload, BriefingSection, BriefingStat

_ROMAN_NUMERALS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")

_BG = "#0a0a0a"
_CARD_BG = "#141414"
_BORDER = "#262626"
_TEXT = "#f4f4f5"
_MUTED = "#a1a1aa"
_SERIF_STACK = "'Playfair Display', Georgia, 'Times New Roman', serif"
_SANS_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

# Degree offsets and lightness for the 6 gradient stops, relative to the payload's
# hue: the hue varies per day, the template does not.
_GRADIENT_OFFSETS = (-40, -15, 0, 20, 45, 70)
_GRADIENT_LIGHTNESS = (58, 50, 46, 50, 58, 64)


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


def _stat_row(stats: list[BriefingStat]) -> str:
    if not stats:
        return ""
    cells = []
    for stat in stats:
        value = escape(stat.value)
        label = escape(stat.label)
        delta_html = (
            f'<div style="font-size: 11px; color: {_MUTED}; margin-top: 2px;">{escape(stat.delta)}</div>'
            if stat.delta
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


def _sections_block(sections: list[BriefingSection]) -> str:
    if not sections:
        return ""
    blocks = []
    for i, section in enumerate(sections):
        numeral = escape(section.numeral or _ROMAN_NUMERALS[min(i, len(_ROMAN_NUMERALS) - 1)])
        title = escape(section.title.upper())
        item_rows = "".join(
            f'<div style="padding: 8px 0; border-bottom: 1px solid {_BORDER}; font-size: 14px; color: {_TEXT};">'
            f"{escape(item.text)}</div>"
            for item in section.items
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
    payload: BriefingPayload, default_kicker: str, unsubscribe_url: str
) -> str:
    rows = (
        _masthead(payload.kicker or default_kicker, payload.date)
        + _gradient_band(payload.hue)
        + _headline_block(payload.headline, payload.lede)
        + _stat_row(payload.stats)
        + _sections_block(payload.sections)
        + _caption_block(payload.caption)
        + _unsubscribe_footer(unsubscribe_url)
    )
    return _wrap(rows)


def render_daily_brief_email(payload: BriefingPayload, unsubscribe_url: str) -> str:
    """Render the daily brief email from a BriefingPayload."""
    return _render_briefing_email(payload, "Daily Brief", unsubscribe_url)


def render_weekly_digest_email(payload: BriefingPayload, unsubscribe_url: str) -> str:
    """Render the weekly digest email — same editorial shape as the daily brief."""
    return _render_briefing_email(payload, "Weekly Digest", unsubscribe_url)


def render_plain_notification_email(title: str, body: str, unsubscribe_url: str) -> str:
    """Render a plain (non-briefing) notification email: title + body."""
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
