"""Tests for platform-specific Markdown converters.

Mirrors the TypeScript formatter tests at
``apps/bots/__tests__/shared/utils/formatters.test.ts`` so the two
implementations stay in sync. When changing behavior here, update the TS
converter in ``libs/shared/ts/src/bots/utils/formatters.ts`` too (and vice
versa).
"""

from __future__ import annotations

import pytest

from app.utils.platform_markdown import (
    convert_to_slack_mrkdwn,
    convert_to_whatsapp_markdown,
)


class TestConvertToWhatsAppMarkdown:
    def test_empty_string_is_passthrough(self) -> None:
        assert convert_to_whatsapp_markdown("") == ""

    def test_double_asterisk_bold_becomes_single(self) -> None:
        assert convert_to_whatsapp_markdown("**bold**") == "*bold*"

    def test_triple_asterisk_bold_italic_collapses_to_bold(self) -> None:
        assert convert_to_whatsapp_markdown("***emph***") == "*emph*"

    def test_headings_become_bold(self) -> None:
        assert convert_to_whatsapp_markdown("# Title") == "*Title*"
        assert convert_to_whatsapp_markdown("### Sub") == "*Sub*"
        assert convert_to_whatsapp_markdown("###### Deep") == "*Deep*"

    def test_links_become_label_with_trailing_url(self) -> None:
        result = convert_to_whatsapp_markdown("[Gaia](https://heygaia.io)")
        assert result == "Gaia (https://heygaia.io)"

    def test_blockquote_prefix_is_stripped(self) -> None:
        assert convert_to_whatsapp_markdown("> quoted") == "quoted"

    def test_horizontal_rule_is_removed(self) -> None:
        assert convert_to_whatsapp_markdown("a\n---\nb") == "a\n\nb"

    def test_fenced_code_block_is_preserved_verbatim(self) -> None:
        src = "prose **bold**\n```\n**keep me**\n### keep me\n```\nmore **bold**"
        out = convert_to_whatsapp_markdown(src)
        assert "```\n**keep me**\n### keep me\n```" in out
        # Bold outside the fence is still converted.
        assert "*bold*" in out
        assert "**bold**" not in out.replace("**keep me**", "")

    def test_multiline_with_mixed_formatting(self) -> None:
        src = "### Heading\n**bold** and [link](https://x.com)\n> quote"
        out = convert_to_whatsapp_markdown(src)
        assert out == "*Heading*\n*bold* and link (https://x.com)\nquote"


class TestConvertToSlackMrkdwn:
    def test_empty_string_is_passthrough(self) -> None:
        assert convert_to_slack_mrkdwn("") == ""

    def test_double_asterisk_bold_becomes_single(self) -> None:
        assert convert_to_slack_mrkdwn("**bold**") == "*bold*"

    def test_links_use_angle_bracket_syntax(self) -> None:
        assert (
            convert_to_slack_mrkdwn("[Gaia](https://heygaia.io)")
            == "<https://heygaia.io|Gaia>"
        )

    def test_headings_become_bold(self) -> None:
        assert convert_to_slack_mrkdwn("## Section") == "*Section*"

    def test_fenced_code_block_preserved(self) -> None:
        src = "text **bold**\n```\n**keep**\n```\nafter"
        out = convert_to_slack_mrkdwn(src)
        assert "```\n**keep**\n```" in out
        assert out.startswith("text *bold*")


@pytest.mark.parametrize(
    ("converter", "given", "expected"),
    [
        (convert_to_whatsapp_markdown, "plain text", "plain text"),
        (convert_to_slack_mrkdwn, "plain text", "plain text"),
        (convert_to_whatsapp_markdown, "a **b** c", "a *b* c"),
        (convert_to_slack_mrkdwn, "a **b** c", "a *b* c"),
    ],
)
def test_converters_handle_plain_and_simple_bold(
    converter, given: str, expected: str
) -> None:
    assert converter(given) == expected
