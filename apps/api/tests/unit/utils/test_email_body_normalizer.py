"""Unit tests for the email body normalizer.

Each rule gets at least one test. The deliberate non-stripping of quoted
replies has an explicit guardrail test (test_quoted_replies_are_kept) that
will fail loudly if anyone "fixes" the normalizer by stripping them.
"""

from app.utils.email_body_normalizer import (
    collapse_whitespace,
    html_to_text,
    normalize_email_body,
    strip_disclaimers,
    strip_signature,
    strip_tracking_params,
    strip_unsubscribe_footers,
)


class TestStripSignature:
    def test_strips_after_delimiter(self) -> None:
        body = "Hello there.\n\n-- \nDhruv Maradiya\nFounder\n+91 9999999999"
        result = strip_signature(body)
        assert result == "Hello there."

    def test_no_delimiter_leaves_body_unchanged(self) -> None:
        body = "Hello there. No signature here."
        assert strip_signature(body) == body

    def test_keeps_short_dash_lines(self) -> None:
        # Two dashes mid-sentence should not trigger the signature strip.
        body = "Use -- to separate options in the CLI."
        assert strip_signature(body) == body

    def test_keeps_quoted_reply_block(self) -> None:
        body = (
            "Sure, let me check.\n\n"
            "> On Tue, 5 Mar 2024, alice@example.com wrote:\n"
            "> Can you confirm?\n\n"
            "-- \nDhruv\n"
        )
        # The signature delimiter is still detected and removed, but the
        # quoted reply above it is untouched.
        result = strip_signature(body)
        assert "> On Tue, 5 Mar 2024" in result
        assert "Can you confirm?" in result
        assert "Dhruv" not in result


class TestStripDisclaimers:
    def test_strips_disclaimer_block(self) -> None:
        body = (
            "Your transaction is complete.\n\n"
            "DISCLAIMER: This communication is confidential and privileged..."
        )
        result = strip_disclaimers(body)
        assert "transaction is complete" in result
        assert "DISCLAIMER" not in result

    def test_strips_confidentiality_notice(self) -> None:
        body = "Done.\n\nCONFIDENTIALITY NOTICE: The information in this email..."
        result = strip_disclaimers(body)
        assert "CONFIDENTIALITY" not in result
        assert "Done." in result

    def test_strips_please_do_not_reply(self) -> None:
        body = "Your card was charged.\n\nPlease do not reply to this email."
        result = strip_disclaimers(body)
        assert "Please do not reply" not in result
        assert "card was charged" in result

    def test_no_disclaimer_unchanged(self) -> None:
        body = "Just a regular email with no disclaimers."
        assert strip_disclaimers(body) == body


class TestStripUnsubscribeFooters:
    def test_strips_unsubscribe_paragraph(self) -> None:
        body = "Newsletter content here.\n\nClick here to unsubscribe from future emails."
        result = strip_unsubscribe_footers(body)
        assert "Newsletter content" in result
        assert "unsubscribe" not in result

    def test_strips_manage_preferences(self) -> None:
        body = "Hi!\n\nManage preferences or unsubscribe."
        result = strip_unsubscribe_footers(body)
        assert "Manage preferences" not in result
        assert "unsubscribe" not in result

    def test_strips_us_postal_address(self) -> None:
        body = "Newsletter body.\n\nMercury Technologies, Inc.\n2261 Market Street, Suite 86807, San Francisco, CA 94114"
        result = strip_unsubscribe_footers(body)
        assert "Newsletter body" in result
        assert "Market Street" not in result
        assert "94114" not in result

    def test_keeps_inline_postal_mentions(self) -> None:
        # Only standalone paragraphs that look like address blocks get dropped;
        # an inline mention ("ship to 2261 Market Street, ...") is not enough.
        body = "Please ship to 2261 Market Street, Suite 86807, San Francisco, CA 94114 tomorrow."
        # The address is in-line (no blank-line paragraph break), so it stays.
        result = strip_unsubscribe_footers(body)
        assert "Market Street" in result


class TestStripTrackingParams:
    def test_strips_utm_params(self) -> None:
        text = "https://example.com/?utm_source=fb&utm_medium=email&id=42"
        result = strip_tracking_params(text)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "id=42" in result
        assert "?" in result

    def test_strips_mc_eid(self) -> None:
        text = "https://example.com/?mc_eid=abc&id=1"
        assert "mc_eid" not in strip_tracking_params(text)
        assert "id=1" in strip_tracking_params(text)

    def test_strips_hubspot_params(self) -> None:
        text = "https://example.com/?_hsenc=xyz&_hsmi=123&keep=1"
        result = strip_tracking_params(text)
        assert "_hsenc" not in result
        assert "_hsmi" not in result
        assert "keep=1" in result

    def test_handles_ampersand_terminator(self) -> None:
        text = "https://example.com/?keep=1&utm_source=fb"
        result = strip_tracking_params(text)
        assert "utm_source" not in result
        # No trailing '?' or '&' should remain.
        assert not result.endswith("?")
        assert not result.endswith("&")

    def test_preserves_clean_url(self) -> None:
        text = "https://example.com/page"
        assert strip_tracking_params(text) == text


class TestCollapseWhitespace:
    def test_collapses_multiple_blank_lines(self) -> None:
        body = "Para 1.\n\n\n\n\nPara 2."
        assert collapse_whitespace(body) == "Para 1.\n\nPara 2."

    def test_strips_trailing_whitespace(self) -> None:
        body = "Line 1.   \nLine 2.\t\n"
        result = collapse_whitespace(body)
        assert result == "Line 1.\nLine 2."

    def test_removes_invisible_chars(self) -> None:
        body = "Hello\u200b\u200cworld\u200d."
        result = collapse_whitespace(body)
        assert result == "Helloworld."

    def test_strips_outer_whitespace(self) -> None:
        body = "   \n\nHello.\n\n   "
        assert collapse_whitespace(body) == "Hello."


class TestHtmlToText:
    def test_extracts_text_from_simple_html(self) -> None:
        html = "<p>Hello <strong>world</strong>.</p>"
        result = html_to_text(html)
        assert "Hello" in result
        assert "world" in result
        assert "<" not in result

    def test_drops_script_and_style(self) -> None:
        html = (
            "<p>Visible text.</p><script>alert('xss')</script><style>body { color: red; }</style>"
        )
        result = html_to_text(html)
        assert "Visible text" in result
        assert "alert" not in result
        assert "color" not in result

    def test_preserves_paragraph_breaks(self) -> None:
        html = "<p>First paragraph.</p><p>Second paragraph.</p>"
        result = html_to_text(html)
        assert "First paragraph" in result
        assert "Second paragraph" in result

    def test_unescapes_entities(self) -> None:
        html = "<p>Tom &amp; Jerry &lt;3</p>"
        result = html_to_text(html)
        assert "Tom & Jerry" in result
        assert "<3" in result

    def test_plain_text_passthrough(self) -> None:
        assert html_to_text("just plain text") == "just plain text"


class TestQuotedRepliesAreKept:
    """Explicit guardrail: the normalizer must NOT strip quoted replies.

    Lines starting with `>` and the `On <date>, <sender> wrote:` attribution
    line give the agent context into the older conversation. Anyone adding a
    "strip quoted replies" rule will break this test.
    """

    def test_keeps_quoted_block(self) -> None:
        body = (
            "Sure, I'll take a look.\n\n"
            "> On Tue, 5 Mar 2024 at 10:00, alice@example.com wrote:\n"
            "> Hey, can you confirm the Q3 numbers?\n"
            "> Thanks!\n"
        )
        result = normalize_email_body(body)
        assert "I'll take a look" in result
        assert "> On Tue, 5 Mar 2024" in result
        assert "> Hey, can you confirm the Q3 numbers?" in result
        assert "> Thanks!" in result

    def test_keeps_quoted_block_with_signature_below(self) -> None:
        body = (
            "Yep, all set.\n\n"
            "> On Wed, 6 Mar 2024, bob@example.com wrote:\n"
            "> Did you see the latest report?\n\n"
            "-- \nDhruv Maradiya\nFounder & CEO\n"
        )
        result = normalize_email_body(body)
        assert "Yep, all set" in result
        assert "> Did you see the latest report?" in result
        # Signature IS stripped (it's not quoted reply).
        assert "Founder" not in result

    def test_quoted_block_with_disclaimer_around_it(self) -> None:
        # Disclaimer comes BEFORE the quoted block — should be stripped.
        body = (
            "Got it.\n\n"
            "DISCLAIMER: Confidential and privileged.\n\n"
            "> alice wrote:\n"
            "> Where are we on this?\n"
        )
        result = normalize_email_body(body)
        assert "Got it" in result
        assert "DISCLAIMER" not in result
        assert "> alice wrote:" in result
        assert "> Where are we on this?" in result


class TestNormalizeEndToEnd:
    def test_full_normalize_strips_all_boilerplate(self) -> None:
        body = (
            "Hi there,\n\n"
            "Your transaction of Rs.133.27 on COMMANDCODE.AI has been processed.\n\n"
            "> On Mon, alice wrote:\n"
            "> Was the card charged?\n\n"
            "DISCLAIMER: This communication is confidential and privileged. "
            "The recipient if not the addressee should not use this message.\n\n"
            "Please do not reply to this email.\n\n"
            "Important: Please do not reply to this email. For any queries, "
            "please call our Customer Contact Centre.\n\n"
            "-- \nKotak Mahindra Bank\n"
        )
        result = normalize_email_body(body)
        # Meaningful content kept
        assert "transaction of Rs.133.27" in result
        assert "COMMANDCODE.AI" in result
        # Quoted reply kept
        assert "> On Mon, alice wrote:" in result
        assert "> Was the card charged?" in result
        # Boilerplate stripped
        assert "DISCLAIMER" not in result
        assert "Please do not reply" not in result
        # Signature stripped
        assert "Kotak Mahindra Bank" not in result
        # No signature delimiter should remain
        assert "-- " not in result

    def test_idempotent(self) -> None:
        body = "Hello there.\n\n-- \nSignature\nDISCLAIMER: Confidential.\n\nSome content here.\n"
        once = normalize_email_body(body)
        twice = normalize_email_body(once)
        assert once == twice

    def test_empty_string(self) -> None:
        assert normalize_email_body("") == ""

    def test_plain_text_without_boilerplate(self) -> None:
        body = "Just a simple message with nothing to strip."
        assert normalize_email_body(body) == body

    def test_html_input_is_extracted_then_normalized(self) -> None:
        html = (
            "<p>Order confirmed.</p>"
            "<p>DISCLAIMER: This is confidential.</p>"
            "<p>-- <br>Dhruv<br>Founder</p>"
        )
        result = normalize_email_body(html)
        assert "Order confirmed" in result
        assert "DISCLAIMER" not in result
        assert "Founder" not in result

    def test_strips_utm_tracking_in_links(self) -> None:
        body = (
            "Check this out: https://blog.example.com/post?utm_source=newsletter&id=42\n\n"
            "-- \nUnsubscribe me"
        )
        result = normalize_email_body(body)
        assert "utm_source" not in result
        assert "id=42" in result
