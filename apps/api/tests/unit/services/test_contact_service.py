"""Unit tests for contact_service.build_contact_index.

The helper is pure (no deps): validated Gmail messages in, deduped/sorted
contacts out. A header missing its name or value must be skipped, never crash
the list.
"""

from app.models.integrations.gmail_messages import GmailApiMessage
from app.services.contact_service import build_contact_index


def _message(headers: list[dict[str, str]]) -> GmailApiMessage:
    return GmailApiMessage.model_validate({"payload": {"headers": headers}})


class TestBuildContactIndex:
    def test_extracts_unique_contacts_across_fields(self):
        messages = [
            _message(
                [
                    {"name": "From", "value": "Alice <alice@example.com>"},
                    {"name": "To", "value": "Bob <bob@example.com>, Carol <carol@example.com>"},
                    {"name": "Cc", "value": '"Doe, John" <john@example.com>'},
                ]
            ),
            _message([{"name": "From", "value": "Alice <alice@example.com>"}]),
        ]

        result = build_contact_index(messages)

        assert result["success"] is True
        assert result["count"] == 4
        emails = {c["email"] for c in result["contacts"]}
        assert emails == {
            "alice@example.com",
            "bob@example.com",
            "carol@example.com",
            "john@example.com",
        }

    def test_handles_quoted_name_with_comma(self):
        messages = [_message([{"name": "From", "value": '"Doe, John" <john@example.com>'}])]

        result = build_contact_index(messages)

        assert result["contacts"][0]["name"] == "Doe, John"
        assert result["contacts"][0]["email"] == "john@example.com"

    def test_skips_emails_without_at_or_dot(self):
        messages = [
            _message(
                [
                    {"name": "From", "value": "Nope <no-at-sign>"},
                    {"name": "To", "value": "Bare <bare@example>", "value2": "x"},
                    {"name": "Cc", "value": "Good <good@example.com>"},
                ]
            ),
        ]

        result = build_contact_index(messages)

        assert result["count"] == 1
        assert result["contacts"][0]["email"] == "good@example.com"

    def test_skips_headers_missing_a_name_or_value(self) -> None:
        messages = [
            _message([{"name": "From"}]),  # header without "value"
            _message([{"value": "NoName <x@example.com>"}]),  # header without "name"
        ]

        result = build_contact_index(messages)

        assert result["success"] is True
        assert result["contacts"] == []
        assert result["count"] == 0

    def test_empty_messages(self):
        result = build_contact_index([])

        assert result == {"success": True, "contacts": [], "count": 0}

    def test_keeps_first_name_for_repeated_email(self):
        messages = [
            _message([{"name": "From", "value": "Alice <alice@example.com>"}]),
            _message([{"name": "From", "value": "<alice@example.com>"}]),
        ]

        result = build_contact_index(messages)

        assert result["contacts"][0]["name"] == "Alice"

    def test_named_contact_wins_over_nameless(self):
        messages = [
            _message([{"name": "From", "value": "<alice@example.com>"}]),
            _message([{"name": "From", "value": "Alice <alice@example.com>"}]),
        ]

        result = build_contact_index(messages)

        assert result["contacts"][0]["name"] == "Alice"

    def test_a_second_name_does_not_replace_the_first(self) -> None:
        # Both headers name the person, so there is nothing to fill in: the address
        # was already known with a name and the second message must not churn it.
        messages = [
            _message([{"name": "From", "value": "Alice Smith <alice@example.com>"}]),
            _message([{"name": "From", "value": "Alice S <alice@example.com>"}]),
        ]

        result = build_contact_index(messages)

        assert result["contacts"] == [{"name": "Alice Smith", "email": "alice@example.com"}]

    def test_sorted_by_name_then_email(self):
        messages = [
            _message(
                [
                    {"name": "To", "value": "zeta@example.com, Alpha <alpha@example.com>"},
                    {"name": "From", "value": "mid <mid@example.com>"},
                ]
            ),
        ]

        result = build_contact_index(messages)

        emails = [c["email"] for c in result["contacts"]]
        assert emails == ["alpha@example.com", "mid@example.com", "zeta@example.com"]

    def test_filter_query_matches_name_or_email_case_insensitively(self):
        messages = [
            _message([{"name": "To", "value": "Alice <alice@example.com>"}]),
            _message([{"name": "To", "value": "Bob <bob@example.com>"}]),
            _message([{"name": "To", "value": "Carol <carol@example.net>"}]),
        ]

        by_name = build_contact_index(messages, filter_query="ALICE")
        by_email = build_contact_index(messages, filter_query="example.net")

        assert by_name["count"] == 1
        assert by_name["contacts"][0]["email"] == "alice@example.com"
        assert by_email["count"] == 1
        assert by_email["contacts"][0]["email"] == "carol@example.net"

    def test_filter_query_no_match(self):
        messages = [_message([{"name": "To", "value": "Alice <alice@example.com>"}])]

        result = build_contact_index(messages, filter_query="zzz")

        assert result["contacts"] == []
        assert result["count"] == 0

    def test_headers_without_payload_are_skipped(self):
        messages = [GmailApiMessage.model_validate({"no_payload": True})]

        result = build_contact_index(messages)

        assert result["contacts"] == []
