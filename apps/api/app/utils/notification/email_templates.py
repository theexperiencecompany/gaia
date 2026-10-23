"""Hand-designed HTML email template for plain GAIA notification emails.

Table-based layout, inline styles only, for email-client compatibility. The email
channel adapter renders every non-briefing notification with it; briefings are sent
as their hosted edition image (app/services/briefing/edition_email.py).
"""

from __future__ import annotations

from html import escape

_BG = "#0a0a0a"
_CARD_BG = "#141414"
_BORDER = "#262626"
_TEXT = "#f4f4f5"
_MUTED = "#a1a1aa"
_SERIF_STACK = "'Playfair Display', Georgia, 'Times New Roman', serif"
_SANS_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


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
