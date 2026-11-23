"""Unit tests for the hand-written plain-notification email template.

The template is plain string composition with hand-escaping, so the only thing
that can be asserted is the exact bytes it emits: every style constant and every
escape. The expected HTML is
written out as literals rather than rebuilt from the module's own constants — a
test that recomposes the template from the same private constants passes no
matter what those constants say.
"""

from __future__ import annotations

from app.utils.notification.email_templates import render_plain_notification_email

_UNSUB = "https://api.example.test/unsub?token=t0k&x=1"

_ESCAPED_UNSUB_FOOTER = (
    '        GAIA &middot; <a href="https://api.example.test/unsub?token=t0k&amp;x=1"'
    ' style="color: #a1a1aa;">Unsubscribe from these emails</a>'
)

_SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
_SERIF = "'Playfair Display', Georgia, 'Times New Roman', serif"

_DOC_OPEN = (
    "<!doctype html>\n"
    "<html>\n"
    '  <body style="margin: 0; padding: 0; background: #0a0a0a;">\n'
    '    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
    ' style="background: #0a0a0a;">\n'
    "      <tr>\n"
    '        <td align="center" style="padding: 40px 16px;">\n'
    '          <table role="presentation" width="600" cellpadding="0" cellspacing="0"'
    ' style="max-width: 600px; width: 100%; background: #141414; border: 1px solid #262626;'
    ' border-radius: 16px; overflow: hidden;">\n'
)

_DOC_CLOSE = "          </table>\n        </td>\n      </tr>\n    </table>\n  </body>\n</html>"


# ========================================================================
# render_plain_notification_email — pinned byte-for-byte
# ========================================================================


class TestRenderPlainNotificationEmail:
    def test_exact_document(self) -> None:
        html = render_plain_notification_email("T & <b>", 'body "x"', _UNSUB)

        assert html == (
            _DOC_OPEN + "            \n"
            "    <tr>\n"
            f'      <td style="padding: 40px 40px 0; font-family: {_SANS};">\n'
            f'        <div style="font-family: {_SERIF}; font-style: italic;'
            ' font-size: 22px; color: #f4f4f5;">\n'
            "          T &amp; &lt;b&gt;\n"
            "        </div>\n"
            '        <div style="font-size: 15px; line-height: 1.6; color: #a1a1aa;'
            ' margin-top: 12px;">\n'
            "          body &quot;x&quot;\n"
            "        </div>\n"
            "      </td>\n"
            "    </tr>\n"
            "    \n"
            "    <tr>\n"
            f'      <td style="padding: 32px 40px 40px; font-family: {_SANS};'
            " font-size: 11px; color: #a1a1aa; border-top: 1px solid #262626;"
            ' margin-top: 24px;">\n' + _ESCAPED_UNSUB_FOOTER + "\n"
            "      </td>\n"
            "    </tr>\n"
            "    \n" + _DOC_CLOSE
        )

    def test_empty_title_and_body_render_as_empty_text_nodes(self) -> None:
        html = render_plain_notification_email("", "", "https://u")

        assert (
            f'        <div style="font-family: {_SERIF}; font-style: italic;'
            ' font-size: 22px; color: #f4f4f5;">\n'
            "          \n"
            "        </div>\n" in html
        )
        assert "&" not in html.replace("&middot;", "")

    def test_single_quote_in_body_is_escaped(self) -> None:
        html = render_plain_notification_email("t", "it's", "https://u")

        assert "it&#x27;s" in html
        assert "it's" not in html
