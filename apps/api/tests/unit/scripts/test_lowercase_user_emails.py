"""Unit tests for the email-lowercasing plan: rewrite single rows, never touch case-duplicates."""

from scripts.lowercase_user_emails import StoredEmail, build_plan


def test_a_mixed_case_row_alone_is_lowercased() -> None:
    row = StoredEmail(user_id="u1", email="Aryan@X.com")

    plan = build_plan([row, StoredEmail(user_id="u2", email="b@x.com")])

    assert plan.lowercase == [row]
    assert plan.collisions == {}


def test_addresses_differing_only_in_case_are_reported_not_rewritten() -> None:
    upper = StoredEmail(user_id="u1", email="Aryan@X.com")
    lower = StoredEmail(user_id="u2", email="aryan@x.com")

    plan = build_plan([upper, lower])

    assert plan.lowercase == []
    assert plan.collisions == {"aryan@x.com": [upper, lower]}


def test_a_padded_address_is_rewritten_trimmed() -> None:
    row = StoredEmail(user_id="u1", email=" c@x.com ")

    assert build_plan([row]).lowercase == [row]
