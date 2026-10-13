"""Unit tests for the hand-written notification email templates.

These templates are plain string composition with hand-escaping, so the only
thing that can be asserted is the exact bytes they emit: every style constant,
every optional block's presence/absence, and every escape. The expected HTML is
written out as literals rather than rebuilt from the module's own constants — a
test that recomposes the template from the same private constants passes no
matter what those constants say.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.utils.notification.email_templates import (
    render_daily_brief_email,
    render_plain_notification_email,
    render_weekly_digest_email,
)

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


def _rich_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kicker": "Morning <Brief>",
        "date": "2026-09-02",
        "hue": 350,
        "headline": "A & B",
        "lede": "it's fine",
        "stats": [
            {"value": 3, "label": "todos", "delta": "+2"},
            {"value": "0", "label": "mail"},
        ],
        "sections": [{"title": "agenda & more", "items": [{"text": "x < y"}]}],
        "caption": "the end",
    }
    payload.update(overrides)
    return payload


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

    def test_has_no_briefing_furniture(self) -> None:
        html = render_plain_notification_email("t", "b", "https://u")

        assert "linear-gradient" not in html
        assert "text-transform: uppercase" not in html


# ========================================================================
# Briefing templates — shared editorial shape, different default kicker
# ========================================================================


class TestBriefingKicker:
    def test_daily_default_kicker(self) -> None:
        assert "\n          Daily Brief\n" in render_daily_brief_email({}, "https://u")

    def test_weekly_default_kicker(self) -> None:
        assert "\n          Weekly Digest\n" in render_weekly_digest_email({}, "https://u")

    def test_payload_kicker_overrides_default_and_is_escaped(self) -> None:
        daily = render_daily_brief_email({"kicker": "Morning <Brief>"}, "https://u")
        weekly = render_weekly_digest_email({"kicker": "Morning <Brief>"}, "https://u")

        assert "\n          Morning &lt;Brief&gt;\n" in daily
        assert "Daily Brief" not in daily
        assert "\n          Morning &lt;Brief&gt;\n" in weekly
        assert "Weekly Digest" not in weekly

    def test_empty_kicker_falls_back_to_default(self) -> None:
        assert "\n          Daily Brief\n" in render_daily_brief_email({"kicker": ""}, "https://u")

    def test_daily_and_weekly_differ_only_in_kicker(self) -> None:
        payload = _rich_payload(kicker=None)

        daily = render_daily_brief_email(payload, _UNSUB)
        weekly = render_weekly_digest_email(payload, _UNSUB)

        assert daily.replace("Daily Brief", "Weekly Digest") == weekly


class TestBriefingMasthead:
    def test_date_is_rendered_and_escaped(self) -> None:
        html = render_daily_brief_email({"date": "2026-09-02 <b>"}, "https://u")

        assert (
            '        <div style="font-size: 12px; color: #a1a1aa; margin-top: 4px;">'
            "2026-09-02 &lt;b&gt;</div>" in html
        )

    def test_missing_date_renders_empty_div(self) -> None:
        html = render_daily_brief_email({}, "https://u")

        assert (
            '        <div style="font-size: 12px; color: #a1a1aa; margin-top: 4px;"></div>' in html
        )


class TestBriefingGradientBand:
    def test_hue_offsets_and_lightness(self) -> None:
        html = render_daily_brief_email({"hue": 210}, "https://u")

        assert (
            '        <div style="height: 6px; border-radius: 3px; background:'
            " linear-gradient(90deg, hsl(170, 70%, 58%), hsl(195, 70%, 50%),"
            " hsl(210, 70%, 46%), hsl(230, 70%, 50%), hsl(255, 70%, 58%),"
            ' hsl(280, 70%, 64%));"></div>' in html
        )

    def test_hue_wraps_around_the_colour_wheel(self) -> None:
        html = render_daily_brief_email({"hue": 350}, "https://u")

        assert (
            "linear-gradient(90deg, hsl(310, 70%, 58%), hsl(335, 70%, 50%),"
            " hsl(350, 70%, 46%), hsl(10, 70%, 50%), hsl(35, 70%, 58%),"
            " hsl(60, 70%, 64%));" in html
        )

    def test_missing_hue_defaults_to_210(self) -> None:
        assert render_daily_brief_email({}, "https://u") == render_daily_brief_email(
            {"hue": 210}, "https://u"
        )

    def test_hue_zero_is_red_not_the_default(self) -> None:
        html = render_daily_brief_email({"hue": 0}, "https://u")

        assert (
            "linear-gradient(90deg, hsl(320, 70%, 58%), hsl(345, 70%, 50%),"
            " hsl(0, 70%, 46%), hsl(20, 70%, 50%), hsl(45, 70%, 58%),"
            " hsl(70, 70%, 64%));" in html
        )

    def test_a_stop_is_never_silently_dropped_when_the_tables_disagree(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.utils.notification.email_templates._GRADIENT_OFFSETS", (-40, -15, 0)
        )

        with pytest.raises(ValueError, match="zip"):
            render_daily_brief_email({"hue": 210}, "https://u")

    def test_string_hue_is_coerced_to_int(self) -> None:
        assert render_daily_brief_email({"hue": "350"}, "https://u") == render_daily_brief_email(
            {"hue": 350}, "https://u"
        )


class TestBriefingHeadlineBlock:
    def test_headline_and_lede_escaped(self) -> None:
        html = render_daily_brief_email({"headline": "A & B", "lede": "it's fine"}, "https://u")

        assert (
            f'        <div style="font-family: {_SERIF}; font-style: italic;'
            ' font-size: 28px; line-height: 1.25; color: #f4f4f5;">\n'
            "          A &amp; B\n"
            "        </div>\n"
            '        <div style="font-size: 15px; line-height: 1.6; color: #a1a1aa;'
            ' margin-top: 12px;">\n'
            "          it&#x27;s fine\n"
            "        </div>" in html
        )

    def test_missing_headline_and_lede_render_empty(self) -> None:
        html = render_daily_brief_email({}, "https://u")

        assert (
            f'        <div style="font-family: {_SERIF}; font-style: italic;'
            ' font-size: 28px; line-height: 1.25; color: #f4f4f5;">\n'
            "          \n"
            "        </div>" in html
        )


class TestBriefingStatRow:
    def test_no_stats_key_omits_the_row(self) -> None:
        assert 'style="border-collapse: collapse;"' not in render_daily_brief_email({}, "https://u")

    def test_empty_stats_list_omits_the_row(self) -> None:
        assert 'style="border-collapse: collapse;"' not in render_daily_brief_email(
            {"stats": []}, "https://u"
        )

    def test_stat_cell_with_delta(self) -> None:
        html = render_daily_brief_email(
            {"stats": [{"value": 3, "label": "todos", "delta": "+2"}]}, "https://u"
        )

        assert (
            '        <td style="padding: 16px 20px; border: 1px solid #262626;'
            ' text-align: center;">\n'
            f'          <div style="font-family: {_SERIF}; font-size: 22px;'
            ' color: #f4f4f5;">3</div>\n'
            '          <div style="font-size: 11px; text-transform: uppercase;'
            ' letter-spacing: 1px; color: #a1a1aa; margin-top: 4px;">todos</div>\n'
            '          <div style="font-size: 11px; color: #a1a1aa; margin-top: 2px;">'
            "+2</div>\n"
            "        </td>" in html
        )

    def test_stat_cell_without_delta_leaves_the_slot_blank(self) -> None:
        html = render_daily_brief_email({"stats": [{"value": "0", "label": "mail"}]}, "https://u")

        assert (
            '          <div style="font-size: 11px; text-transform: uppercase;'
            ' letter-spacing: 1px; color: #a1a1aa; margin-top: 4px;">mail</div>\n'
            "          \n"
            "        </td>" in html
        )
        assert "margin-top: 2px;" not in html

    def test_empty_string_delta_is_omitted(self) -> None:
        html = render_daily_brief_email(
            {"stats": [{"value": 1, "label": "l", "delta": ""}]}, "https://u"
        )

        assert "margin-top: 2px;" not in html

    def test_missing_value_and_label_render_as_empty(self) -> None:
        html = render_daily_brief_email({"stats": [{}]}, "https://u")

        assert (
            f'<div style="font-family: {_SERIF}; font-size: 22px; color: #f4f4f5;"></div>' in html
        )
        assert (
            '<div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px;'
            ' color: #a1a1aa; margin-top: 4px;"></div>' in html
        )

    def test_value_label_and_delta_are_escaped(self) -> None:
        html = render_daily_brief_email(
            {"stats": [{"value": "<v>", "label": "a&b", "delta": "<d>"}]}, "https://u"
        )

        assert "&lt;v&gt;" in html
        assert "a&amp;b" in html
        assert "&lt;d&gt;" in html
        assert "<v>" not in html

    def test_cells_sit_directly_next_to_each_other(self) -> None:
        html = render_daily_brief_email(
            {"stats": [{"value": 1, "label": "a"}, {"value": 2, "label": "b"}]}, "https://u"
        )

        assert (
            "        </td>\n"
            "        \n"
            '        <td style="padding: 16px 20px; border: 1px solid #262626;'
            ' text-align: center;">\n' in html
        )

    def test_every_stat_gets_its_own_cell(self) -> None:
        html = render_daily_brief_email(
            {"stats": [{"value": i, "label": "l"} for i in range(4)]}, "https://u"
        )

        assert html.count('<td style="padding: 16px 20px; border: 1px solid #262626;') == 4


class TestBriefingSections:
    def test_no_sections_omits_the_block(self) -> None:
        assert "margin-top: 28px;" not in render_daily_brief_email({}, "https://u")

    def test_empty_sections_list_omits_the_block(self) -> None:
        assert "margin-top: 28px;" not in render_daily_brief_email({"sections": []}, "https://u")

    def test_section_title_is_uppercased_and_numbered_in_roman(self) -> None:
        html = render_daily_brief_email(
            {"sections": [{"title": "agenda", "items": []}, {"title": "mail", "items": []}]},
            "https://u",
        )

        assert "\n            I. AGENDA\n" in html
        assert "\n            II. MAIL\n" in html

    def test_section_blocks_sit_directly_next_to_each_other(self) -> None:
        html = render_daily_brief_email(
            {"sections": [{"title": "one", "items": []}, {"title": "two", "items": []}]},
            "https://u",
        )

        assert '        </div>\n        \n        <div style="margin-top: 28px;">\n' in html

    def test_section_without_a_title_renders_the_numeral_alone(self) -> None:
        html = render_daily_brief_email({"sections": [{"items": []}]}, "https://u")

        assert "\n            I. \n" in html

    def test_explicit_numeral_overrides_the_positional_one(self) -> None:
        html = render_daily_brief_email(
            {"sections": [{"numeral": "XIV", "title": "late", "items": []}]}, "https://u"
        )

        assert "\n            XIV. LATE\n" in html
        assert "I. LATE" not in html

    def test_numerals_clamp_at_the_tenth_section(self) -> None:
        html = render_daily_brief_email(
            {"sections": [{"title": f"s{i}", "items": []} for i in range(12)]}, "https://u"
        )

        assert "\n            X. S9\n" in html
        assert "\n            X. S10\n" in html
        assert "\n            X. S11\n" in html
        assert "XI." not in html

    def test_items_render_as_rows(self) -> None:
        html = render_daily_brief_email(
            {"sections": [{"title": "t", "items": [{"text": "one"}, {"text": "two"}]}]},
            "https://u",
        )

        assert (
            '          <div style="margin-top: 8px;">'
            '<div style="padding: 8px 0; border-bottom: 1px solid #262626;'
            ' font-size: 14px; color: #f4f4f5;">one</div>'
            '<div style="padding: 8px 0; border-bottom: 1px solid #262626;'
            ' font-size: 14px; color: #f4f4f5;">two</div></div>' in html
        )

    def test_section_without_items_renders_an_empty_row_container(self) -> None:
        html = render_daily_brief_email({"sections": [{"title": "t"}]}, "https://u")

        assert '          <div style="margin-top: 8px;"></div>' in html

    def test_item_text_and_title_are_escaped(self) -> None:
        html = render_daily_brief_email(
            {"sections": [{"title": "a & b", "items": [{"text": "x < y"}]}]}, "https://u"
        )

        assert "\n            I. A &amp; B\n" in html
        assert "x &lt; y</div>" in html

    def test_item_without_text_renders_empty(self) -> None:
        html = render_daily_brief_email({"sections": [{"title": "t", "items": [{}]}]}, "https://u")

        assert (
            '<div style="padding: 8px 0; border-bottom: 1px solid #262626;'
            ' font-size: 14px; color: #f4f4f5;"></div>' in html
        )


class TestBriefingCaption:
    def test_caption_is_rendered_and_escaped(self) -> None:
        html = render_daily_brief_email({"caption": "the <end>"}, "https://u")

        assert (
            f'      <td style="padding: 32px 40px 0; font-family: {_SERIF};'
            ' font-style: italic; font-size: 13px; color: #a1a1aa;">\n'
            "        the &lt;end&gt;\n"
            "      </td>" in html
        )

    def test_missing_caption_omits_the_block(self) -> None:
        assert 'font-size: 13px; color: #a1a1aa;">' not in render_daily_brief_email({}, "https://u")

    def test_empty_caption_omits_the_block(self) -> None:
        assert 'font-size: 13px; color: #a1a1aa;">' not in render_daily_brief_email(
            {"caption": ""}, "https://u"
        )


class TestBriefingDocumentShape:
    def test_wrapper_and_footer_bracket_every_briefing(self) -> None:
        html = render_daily_brief_email(_rich_payload(), _UNSUB)

        assert html.startswith(_DOC_OPEN)
        assert html.endswith(_DOC_CLOSE)
        assert _ESCAPED_UNSUB_FOOTER in html

    def test_blocks_appear_in_editorial_order(self) -> None:
        html = render_daily_brief_email(_rich_payload(), _UNSUB)

        order = [
            html.index("Morning &lt;Brief&gt;"),
            html.index("linear-gradient"),
            html.index("A &amp; B"),
            html.index("border-collapse: collapse;"),
            html.index("I. AGENDA"),
            html.index("the end"),
            html.index("Unsubscribe from these emails"),
        ]
        assert order == sorted(order)

    def test_empty_payload_document_is_exactly_this(self) -> None:
        """An absent block contributes nothing at all — not a stray character.

        Every optional block returns "" when its payload key is missing, and
        the required ones fall back to empty text nodes. Pinning the whole
        document is the only assertion that proves both.
        """
        html = render_daily_brief_email({}, "https://u")

        assert html == (
            _DOC_OPEN + "            \n"
            "    <tr>\n"
            f'      <td style="padding: 32px 40px 0; font-family: {_SANS};">\n'
            '        <div style="font-size: 11px; letter-spacing: 3px;'
            ' text-transform: uppercase; color: #a1a1aa;">\n'
            "          Daily Brief\n"
            "        </div>\n"
            '        <div style="font-size: 12px; color: #a1a1aa; margin-top: 4px;"></div>\n'
            "      </td>\n"
            "    </tr>\n"
            "    \n"
            "    <tr>\n"
            '      <td style="padding: 16px 40px 0;">\n'
            '        <div style="height: 6px; border-radius: 3px; background:'
            " linear-gradient(90deg, hsl(170, 70%, 58%), hsl(195, 70%, 50%),"
            " hsl(210, 70%, 46%), hsl(230, 70%, 50%), hsl(255, 70%, 58%),"
            ' hsl(280, 70%, 64%));"></div>\n'
            "      </td>\n"
            "    </tr>\n"
            "    \n"
            "    <tr>\n"
            f'      <td style="padding: 24px 40px 0; font-family: {_SANS};">\n'
            f'        <div style="font-family: {_SERIF}; font-style: italic;'
            ' font-size: 28px; line-height: 1.25; color: #f4f4f5;">\n'
            "          \n"
            "        </div>\n"
            '        <div style="font-size: 15px; line-height: 1.6; color: #a1a1aa;'
            ' margin-top: 12px;">\n'
            "          \n"
            "        </div>\n"
            "      </td>\n"
            "    </tr>\n"
            "    \n"
            "    <tr>\n"
            f'      <td style="padding: 32px 40px 40px; font-family: {_SANS};'
            " font-size: 11px; color: #a1a1aa; border-top: 1px solid #262626;"
            ' margin-top: 24px;">\n'
            '        GAIA &middot; <a href="https://u" style="color: #a1a1aa;">'
            "Unsubscribe from these emails</a>\n"
            "      </td>\n"
            "    </tr>\n"
            "    \n" + _DOC_CLOSE
        )

    def test_rich_payload_adds_the_stat_section_and_caption_rows(self) -> None:
        html = render_daily_brief_email(_rich_payload(), _UNSUB)

        # The 5 always-present rows, plus stats, sections, caption, and the
        # stat table's own inner row.
        assert html.count("<tr>") == 9
