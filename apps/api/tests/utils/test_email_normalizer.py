from app.utils.email_normalizer import normalize_email_text


def test_normalize_email_text_parses_html_and_removes_invisible_chars():
    raw = "<div>Hello\u200c<br>World</div><script>alert('x')</script>"

    result = normalize_email_text(raw, max_chars=300, preview_chars=40)

    assert result["was_html"] is True
    assert "alert" not in result["text"]
    assert "\u200c" not in result["text"]
    assert "Hello" in result["text"]
    assert "World" in result["text"]
    assert result["preview"]


def test_normalize_email_text_trims_reply_chain():
    raw = (
        "Please review this today.\n"
        "\n"
        "On Tue, Jan 9, Jane Doe <jane@example.com> wrote:\n"
        "> Older quoted reply content"
    )

    result = normalize_email_text(raw, max_chars=500, strip_reply_chain=True)

    assert "Please review this today." in result["text"]
    assert "On Tue, Jan 9" not in result["text"]
    assert "Older quoted reply content" not in result["text"]


def test_normalize_email_text_keeps_reply_chain_by_default():
    raw = (
        "Please review this today.\n"
        "\n"
        "On Tue, Jan 9, Jane Doe <jane@example.com> wrote:\n"
        "> Older quoted reply content"
    )

    result = normalize_email_text(raw)

    assert "Please review this today." in result["text"]
    assert "On Tue, Jan 9" in result["text"]


def test_normalize_email_text_adds_truncation_notice():
    raw = "A" * 800

    result = normalize_email_text(raw, max_chars=120)

    assert result["truncated"] is True
    assert len(result["text"]) <= 120
    assert "[truncated" in result["text"]


def test_normalize_email_text_has_no_default_char_cap():
    raw = "Z" * 9000

    result = normalize_email_text(raw)

    assert result["truncated"] is False
    assert len(result["text"]) == 9000
