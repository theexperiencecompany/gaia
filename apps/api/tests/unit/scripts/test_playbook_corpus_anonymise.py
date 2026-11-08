"""The corpus anonymiser keeps what the playbook checks read and nothing that names a person."""

import re

import pytest
from scripts.playbook_corpus.anonymise import Anonymiser

ANONYMISER = Anonymiser(salt=b"0" * 16, kept=frozenset({"GMAIL_FETCH_EMAILS"}))


@pytest.mark.parametrize(
    "secret",
    [
        "+1 219-243-0834",
        "(219) 243 0834",
        "10.1.14.25",
        "192.168.0.1:8080",
        "Apt 12-34",
        "+447911123456",
    ],
)
def test_a_number_run_loses_every_digit_and_its_shape(secret: str) -> None:
    out = ANONYMISER.text(secret)

    assert not [group for group in re.findall(r"\d{2,}", secret) if group in out]
    assert re.search(r"\+|\d[ ().:/-]+\d", out) is None


@pytest.mark.parametrize("secret", ["田中 星耀", "交通機械工学科", "José Müller", "नमस्ते"])
def test_text_in_any_script_becomes_ascii(secret: str) -> None:
    out = ANONYMISER.text(secret)

    assert out.isascii()
    assert len(out) == len(secret)


@pytest.mark.parametrize(
    "kept",
    [
        "2026-11-05",
        "2026-11-05T10:00:00+05:30",
        "10:30",
        "10:00-11:00",
        "11/05/2026",
        "Monday, 5 May, 3 PM UTC",
        "$steps.fetch.messages",
        "GMAIL_FETCH_EMAILS",
        "%Y-%m-%d",
        "10, 25",
    ],
)
def test_dates_counts_and_vocabulary_survive(kept: str) -> None:
    assert ANONYMISER.text(kept) == kept


def test_words_and_emails_are_replaced_consistently() -> None:
    out = ANONYMISER.text("Ping aryan.r@gaia.io about Aryan")

    assert "aryan" not in out.lower()
    assert "user@example.com" in out
    assert ANONYMISER.text("Aryan") == out.split()[-1]
