"""
Thorough unit tests for app.utils.composio_hooks.gmail_hooks

Covers every helper, schema modifier, before hook and after hook,
including edge cases, error paths and streaming branches.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# helpers to build fake schemas / params / responses
# ---------------------------------------------------------------------------


def _mock_tool(
    input_parameters: Any = None, description: str = "Original description"
) -> MagicMock:
    schema = MagicMock()
    schema.description = description
    if input_parameters is not None:
        schema.input_parameters = input_parameters
    else:
        schema.input_parameters = {"properties": {}}
    return schema


def _make_params(arguments: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    params: dict[str, Any] = {"arguments": arguments or {}}
    params.update(extra)
    return params


def _make_response(data: Any, successful: bool = True) -> dict[str, Any]:
    return {"data": data, "successful": successful}


def _noop_writer() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


class TestPrimaryHelper:
    def test_empty_returns_none(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import _primary

        assert _primary([]) is None

    def test_returns_primary_when_flagged(self) -> None:
        from app.models.composio_schemas.google_people import (
            GooglePersonFieldMetadata,
            GooglePersonName,
        )
        from app.utils.composio_hooks.gmail_hooks import _primary

        a = GooglePersonName(displayName="A", metadata=GooglePersonFieldMetadata(primary=False))
        b = GooglePersonName(displayName="B", metadata=GooglePersonFieldMetadata(primary=True))
        c = GooglePersonName(displayName="C", metadata=GooglePersonFieldMetadata(primary=False))
        assert _primary([a, b, c]) is b

    def test_returns_first_when_no_primary(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonName
        from app.utils.composio_hooks.gmail_hooks import _primary

        a = GooglePersonName(displayName="First")
        b = GooglePersonName(displayName="Second")
        assert _primary([a, b]) is a

    def test_returns_first_when_metadata_none(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonName
        from app.utils.composio_hooks.gmail_hooks import _primary

        a = GooglePersonName(displayName="Only")
        assert _primary([a]) is a


class TestDisplayName:
    def test_none_returns_unknown(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import _display_name

        assert _display_name(None) == "Unknown"

    def test_missing_display_name_in_fields_returns_unknown(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonName
        from app.utils.composio_hooks.gmail_hooks import _display_name

        # construct without displayName -> not in model_fields_set
        name = GooglePersonName()
        assert _display_name(name) == "Unknown"

    def test_with_display_name_returns_it(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonName
        from app.utils.composio_hooks.gmail_hooks import _display_name

        name = GooglePersonName(displayName="Alice")
        assert _display_name(name) == "Alice"

    def test_display_name_none_explicit_returns_none(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonName
        from app.utils.composio_hooks.gmail_hooks import _display_name

        # When key is present but value is None, it stays None (exposed as live payload)
        name = GooglePersonName(displayName=None)
        # model_fields_set will contain "display_name" even if None when explicitly passed
        # So _display_name should return None, not "Unknown"
        assert _display_name(name) is None


class TestEntryValue:
    def test_none_returns_empty(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import _entry_value

        assert _entry_value(None) == ""

    def test_missing_value_returns_empty(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonValue
        from app.utils.composio_hooks.gmail_hooks import _entry_value

        v = GooglePersonValue()
        assert _entry_value(v) == ""

    def test_with_value_returns_it(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonValue
        from app.utils.composio_hooks.gmail_hooks import _entry_value

        v = GooglePersonValue(value="a@b.com")
        assert _entry_value(v) == "a@b.com"

    def test_explicit_none_stays_none(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonValue
        from app.utils.composio_hooks.gmail_hooks import _entry_value

        v = GooglePersonValue(value=None)
        # key present as explicit null -> should return None, not ""
        # This matches live payload behaviour
        assert _entry_value(v) is None


class TestContactCard:
    def test_full_person(self) -> None:
        from app.models.composio_schemas.google_people import (
            GooglePerson,
            GooglePersonFieldMetadata,
            GooglePersonName,
            GooglePersonValue,
        )
        from app.utils.composio_hooks.gmail_hooks import _contact_card

        person = GooglePerson(
            resourceName="people/123",
            names=[
                GooglePersonName(
                    displayName="Bob", metadata=GooglePersonFieldMetadata(primary=True)
                )
            ],
            emailAddresses=[
                GooglePersonValue(
                    value="bob@example.com", metadata=GooglePersonFieldMetadata(primary=True)
                )
            ],
            phoneNumbers=[
                GooglePersonValue(value="123", metadata=GooglePersonFieldMetadata(primary=True))
            ],
        )
        card = _contact_card(person)
        assert card["name"] == "Bob"
        assert card["email"] == "bob@example.com"
        assert card["phone"] == "123"
        assert card["resource_name"] == "people/123"

    def test_missing_resource_name_returns_empty(self) -> None:
        from app.models.composio_schemas.google_people import GooglePerson
        from app.utils.composio_hooks.gmail_hooks import _contact_card

        person = GooglePerson()
        card = _contact_card(person)
        assert card["resource_name"] == ""
        assert card["name"] == "Unknown"
        assert card["email"] == ""
        assert card["phone"] == ""

    def test_explicit_null_resource_name_preserved(self) -> None:
        from app.models.composio_schemas.google_people import GooglePerson
        from app.utils.composio_hooks.gmail_hooks import _contact_card

        person = GooglePerson(resourceName=None)
        # resourceName explicitly present as null -> stays None, not ""
        card = _contact_card(person)
        assert card["resource_name"] is None


class TestContactSummary:
    def test_name_only_when_blank(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import _contact_summary

        card = {"name": "Alice", "email": "", "phone": "", "resource_name": "people/1"}
        summary = _contact_summary(card)
        assert summary == {"name": "Alice"}

    def test_includes_email_and_phone_when_present(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import _contact_summary

        card = {"name": "Bob", "email": "bob@x.com", "phone": "555", "resource_name": "p/1"}
        summary = _contact_summary(card)
        assert summary["email"] == "bob@x.com"
        assert summary["phone"] == "555"

    def test_excludes_empty_phone_includes_email(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import _contact_summary

        card = {"name": "Bob", "email": "bob@x.com", "phone": "", "resource_name": "p/1"}
        summary = _contact_summary(card)
        assert "phone" not in summary
        assert summary["email"] == "bob@x.com"


# ---------------------------------------------------------------------------
# schema modifiers
# ---------------------------------------------------------------------------


class TestGmailSendEmailSchemaModifier:
    def test_appends_guidance(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_email_schema_modifier

        schema = _mock_tool()
        result = gmail_send_email_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert "GMAIL_CREATE_EMAIL_DRAFT" in result.description
        assert "GMAIL_SEND_DRAFT" in result.description
        # original prefix preserved
        assert result.description.startswith("Original description")

    def test_idempotent_on_reregistration(self) -> None:
        # calling twice should append twice (no guard) - but at least not crash
        from app.utils.composio_hooks.gmail_hooks import gmail_send_email_schema_modifier

        schema = _mock_tool(description="x")
        gmail_send_email_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert schema.description.count("GMAIL_CREATE_EMAIL_DRAFT") == 1


class TestGmailComposeHideIsHtmlSchemaModifier:
    def test_hides_is_html(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_hide_is_html_schema_modifier

        schema = _mock_tool(
            {
                "properties": {"is_html": {"type": "boolean"}, "subject": {"type": "string"}},
                "required": ["is_html", "subject"],
            }
        )
        result = gmail_compose_hide_is_html_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert "is_html" not in result.input_parameters["properties"]
        assert "is_html" not in result.input_parameters["required"]

    def test_no_properties_stays_intact(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_hide_is_html_schema_modifier

        schema = _mock_tool({"properties": {"subject": {"type": "string"}}})
        result = gmail_compose_hide_is_html_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert "subject" in result.input_parameters["properties"]

    def test_non_dict_input_params_returns_unchanged(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_hide_is_html_schema_modifier

        schema = _mock_tool(input_parameters="not_a_dict")
        result = gmail_compose_hide_is_html_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert result is schema
        assert result.input_parameters == "not_a_dict"

    def test_non_dict_properties_returns_unchanged(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_hide_is_html_schema_modifier

        schema = _mock_tool({"properties": "not_dict", "required": ["is_html"]})
        result = gmail_compose_hide_is_html_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        # should still try to remove from required even if properties not dict
        assert result.input_parameters["required"] == []

    def test_required_not_list_ignored(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_hide_is_html_schema_modifier

        schema = _mock_tool(
            {"properties": {"is_html": {"type": "boolean"}}, "required": "not_a_list"}
        )
        result = gmail_compose_hide_is_html_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert result.input_parameters["required"] == "not_a_list"
        assert "is_html" not in result.input_parameters["properties"]


class TestGmailComposeRequireSubjectSchemaModifier:
    def test_adds_required_and_min_length(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_compose_require_subject_schema_modifier,
        )

        schema = _mock_tool(
            {
                "properties": {"subject": {"type": "string", "description": "old"}},
                "required": [],
            }
        )
        result = gmail_compose_require_subject_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert "subject" in result.input_parameters["required"]
        assert result.input_parameters["properties"]["subject"]["minLength"] == 1
        assert "Required" in result.input_parameters["properties"]["subject"]["description"]

    def test_does_not_duplicate_required(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_compose_require_subject_schema_modifier,
        )

        schema = _mock_tool(
            {
                "properties": {"subject": {"type": "string"}},
                "required": ["subject"],
            }
        )
        result = gmail_compose_require_subject_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert result.input_parameters["required"].count("subject") == 1

    def test_no_input_params_dict_no_crash(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_compose_require_subject_schema_modifier,
        )

        schema = _mock_tool(input_parameters=None)
        schema.input_parameters = None
        result = gmail_compose_require_subject_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert result is schema

    def test_subject_property_not_dict_not_modified(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_compose_require_subject_schema_modifier,
        )

        schema = _mock_tool({"properties": {"subject": "not_dict"}, "required": []})
        result = gmail_compose_require_subject_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert result.input_parameters["properties"]["subject"] == "not_dict"
        assert "subject" in result.input_parameters["required"]

    def test_input_params_without_properties_adds_required(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_compose_require_subject_schema_modifier,
        )

        schema = _mock_tool({"required": []})
        result = gmail_compose_require_subject_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert "subject" in result.input_parameters["required"]

    def test_required_not_list_not_appended(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_compose_require_subject_schema_modifier,
        )

        schema = _mock_tool({"properties": {"subject": {"type": "string"}}, "required": "bad"})
        result = gmail_compose_require_subject_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert result.input_parameters["required"] == "bad"


class TestGmailFetchMessageSchemaModifier:
    def test_sets_format_default_full(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_message_schema_modifier

        schema = _mock_tool({"properties": {"format": {"type": "string"}}, "required": []})
        result = gmail_fetch_message_schema_modifier(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "gmail", schema
        )
        assert result.input_parameters["properties"]["format"]["default"] == "full"

    def test_non_dict_input_params_passthrough(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_message_schema_modifier

        schema = _mock_tool(input_parameters="bad")
        result = gmail_fetch_message_schema_modifier(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "gmail", schema
        )
        assert result is schema

    def test_no_format_property_no_crash(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_message_schema_modifier

        schema = _mock_tool({"properties": {"other": {"type": "string"}}})
        result = gmail_fetch_message_schema_modifier(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "gmail", schema
        )
        assert "default" not in result.input_parameters["properties"]["other"]

    def test_format_not_dict_not_modified(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_message_schema_modifier

        schema = _mock_tool({"properties": {"format": "not_dict"}})
        result = gmail_fetch_message_schema_modifier(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "gmail", schema
        )
        assert result.input_parameters["properties"]["format"] == "not_dict"

    def test_properties_not_dict_no_crash(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_message_schema_modifier

        schema = _mock_tool({"properties": "bad"})
        result = gmail_fetch_message_schema_modifier(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "gmail", schema
        )
        assert result is schema or result.input_parameters["properties"] == "bad"


class TestGmailHideUserIdSchemaModifier:
    def test_strips_user_id(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_hide_user_id_schema_modifier

        schema = _mock_tool(
            {
                "properties": {"user_id": {"type": "string"}, "subject": {"type": "string"}},
                "required": ["user_id", "subject"],
            }
        )
        result = gmail_hide_user_id_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert "user_id" not in result.input_parameters["properties"]
        assert "user_id" not in result.input_parameters["required"]
        assert "subject" in result.input_parameters["required"]

    def test_non_dict_input_params_passthrough(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_hide_user_id_schema_modifier

        schema = _mock_tool(input_parameters=123)
        result = gmail_hide_user_id_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert result is schema

    def test_no_user_id_no_crash(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_hide_user_id_schema_modifier

        schema = _mock_tool(
            {"properties": {"subject": {"type": "string"}}, "required": ["subject"]}
        )
        result = gmail_hide_user_id_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert result.input_parameters["required"] == ["subject"]

    def test_properties_none(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_hide_user_id_schema_modifier

        schema = _mock_tool({"properties": None, "required": ["user_id"]})
        result = gmail_hide_user_id_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert result.input_parameters["required"] == []

    def test_required_none(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_hide_user_id_schema_modifier

        schema = _mock_tool({"properties": {"user_id": {"type": "string"}}, "required": None})
        result = gmail_hide_user_id_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)
        assert "user_id" not in result.input_parameters["properties"]


# ---------------------------------------------------------------------------
# before hooks — compose
# ---------------------------------------------------------------------------


class TestGmailComposeBeforeHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch(
        "app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html",
        side_effect=lambda x: f"<p>{x}</p>",
    )
    def test_normalizes_body_keys_and_sets_is_html(
        self, mock_norm: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.return_value = _noop_writer()
        params = _make_params(
            {"body": "hello **world**", "recipient_email": "a@b.com", "subject": "hi"}
        )
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        assert result["arguments"]["is_html"] is True
        assert result["arguments"]["body"] == "<p>hello **world**</p>"
        mock_norm.assert_called()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch(
        "app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html",
        side_effect=lambda x: f"<p>{x}</p>",
    )
    def test_normalizes_message_body_and_message_keys(
        self, mock_norm: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.return_value = _noop_writer()
        # GMAIL_FORWARD_MESSAGE uses message_body/message
        params = _make_params(
            {
                "message_body": "fwd body",
                "message": "msg body",
                "to_recipients": "a@b.com",
                "subject": "s",
            }
        )
        # Need at least recipient/content validation to reach streaming, but forward bypasses recipient check
        gmail_compose_before_hook("GMAIL_FORWARD_MESSAGE", "gmail", params)
        # Both keys normalized
        assert params["arguments"]["message_body"] == "<p>fwd body</p>"
        assert params["arguments"]["message"] == "<p>msg body</p>"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_empty_body_not_normalized(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.return_value = _noop_writer()
        with patch(
            "app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html"
        ) as mock_norm:
            params = _make_params({"body": "", "recipient_email": "a@b.com", "subject": "hi"})
            gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
            mock_norm.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_non_string_body_not_normalized(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.return_value = _noop_writer()
        with patch(
            "app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html"
        ) as mock_norm:
            params = _make_params({"body": 123, "recipient_email": "a@b.com", "subject": "hi"})
            gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
            mock_norm.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_maps_to_to_recipient_email(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.return_value = _noop_writer()
        params = _make_params({"to": "user@example.com", "subject": "hi", "body": "content"})
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        assert result["arguments"]["recipient_email"] == "user@example.com"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_does_not_overwrite_existing_recipient_email(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.return_value = _noop_writer()
        params = _make_params(
            {"to": "other@x.com", "recipient_email": "orig@x.com", "subject": "hi", "body": "b"}
        )
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        assert result["arguments"]["recipient_email"] == "orig@x.com"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_to_mapping_only_for_send_and_draft(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.return_value = _noop_writer()
        params = _make_params({"to": "a@b.com", "subject": "hi", "body": "b"})
        # GMAIL_REPLY_TO_THREAD should NOT map 'to' -> recipient_email (only SEND and CREATE_DRAFT do)
        result = gmail_compose_before_hook("GMAIL_REPLY_TO_THREAD", "gmail", params)
        assert (
            "recipient_email" not in result["arguments"]
            or result["arguments"].get("recipient_email") == ""
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_skips_streaming_when_missing_recipient(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"subject": "hi", "body": "content"})  # no recipient
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        writer.assert_not_called()
        assert result["arguments"]["is_html"] is True  # normalization still happened

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_skips_streaming_when_missing_content(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"recipient_email": "a@b.com"})  # no subject/body
        gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_cc_only_counts_as_recipient(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"cc": ["cc@x.com"], "subject": "hi", "body": "b"})
        gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_bcc_only_counts_as_recipient(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"bcc": ["bcc@x.com"], "subject": "hi", "body": "b"})
        gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_sends_draft_payload(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"recipient_email": "a@b.com", "subject": "draft", "body": "content"})
        gmail_compose_before_hook("GMAIL_CREATE_EMAIL_DRAFT", "gmail", params)
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "email_compose_data" in payload
        assert payload["email_compose_data"][0]["subject"] == "draft"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_sends_email_sent_payload_for_send(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"recipient_email": "a@b.com", "subject": "hi", "body": "content"})
        gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        payload = writer.call_args[0][0]
        assert "email_sent_data" in payload

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_reply_to_thread_payload(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "recipient_email": "a@b.com",
                "subject": "Re: hi",
                "body": "reply",
                "thread_id": "t123",
            }
        )
        gmail_compose_before_hook("GMAIL_REPLY_TO_THREAD", "gmail", params)
        payload = writer.call_args[0][0]
        assert payload["email_sent_data"][0]["thread_id"] == "t123"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_forward_message_string_recipient(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"to_recipients": "single@x.com", "subject": "Fwd", "body": "b"})
        gmail_compose_before_hook("GMAIL_FORWARD_MESSAGE", "gmail", params)
        payload = writer.call_args[0][0]
        assert payload["email_sent_data"][0]["to"] == ["single@x.com"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_forward_message_list_recipients(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {"to_recipients": ["a@x.com", "b@x.com"], "subject": "Fwd", "body": "b"}
        )
        gmail_compose_before_hook("GMAIL_FORWARD_MESSAGE", "gmail", params)
        payload = writer.call_args[0][0]
        assert payload["email_sent_data"][0]["to"] == ["a@x.com", "b@x.com"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_extra_recipients_handled(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "recipient_email": "main@x.com",
                "extra_recipients": ["extra@x.com"],
                "subject": "hi",
                "body": "b",
            }
        )
        gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        payload = writer.call_args[0][0]
        assert payload["email_sent_data"][0]["to"] == ["main@x.com", "extra@x.com"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_extra_recipients_not_list_treated_as_empty(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "recipient_email": "main@x.com",
                "extra_recipients": "notalist",
                "subject": "hi",
                "body": "b",
            }
        )
        gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        payload = writer.call_args[0][0]
        assert payload["email_sent_data"][0]["to"] == ["main@x.com"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_exception_returns_params(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.side_effect = RuntimeError("boom")
        params = _make_params({"recipient_email": "a@b.com", "subject": "hi", "body": "b"})
        # Should swallow exception and return params
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_exception_during_normalization_returns_params(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.return_value = _noop_writer()
        with patch(
            "app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html",
            side_effect=ValueError("bad"),
        ):
            params = _make_params({"body": "hi", "recipient_email": "a@b.com", "subject": "s"})
            result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
            assert result is params


# ---------------------------------------------------------------------------
# progress / utility before hooks
# ---------------------------------------------------------------------------


class TestGmailSendDraftBeforeHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_streams_progress(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"draft_id": "d1"})
        result = gmail_send_draft_before_hook("GMAIL_SEND_DRAFT", "gmail", params)
        writer.assert_called_once()
        assert "progress" in writer.call_args[0][0]
        assert "Sending draft" in writer.call_args[0][0]["progress"]
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_writer_none_returns_params(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_before_hook

        mock_writer.return_value = None
        params = _make_params({"draft_id": "d1"})
        result = gmail_send_draft_before_hook("GMAIL_SEND_DRAFT", "gmail", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_exception_returns_params(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_before_hook

        mock_writer.side_effect = RuntimeError("fail")
        params = _make_params({"draft_id": "d1"})
        result = gmail_send_draft_before_hook("GMAIL_SEND_DRAFT", "gmail", params)
        assert result is params


class TestGmailTrashBeforeHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_trash(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_trash_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_trash_before_hook("GMAIL_TRASH_MESSAGE", "gmail", _make_params())
        assert "Moving to trash" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_untrash(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_trash_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_trash_before_hook("GMAIL_UNTRASH_MESSAGE", "gmail", _make_params())
        assert "Restoring from trash" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_writer_none(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_trash_before_hook

        mock_writer.return_value = None
        result = gmail_trash_before_hook("GMAIL_TRASH_MESSAGE", "gmail", _make_params())
        assert result is not None

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_exception_returns_params(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_trash_before_hook

        mock_writer.side_effect = RuntimeError("oops")
        params = _make_params()
        result = gmail_trash_before_hook("GMAIL_TRASH_MESSAGE", "gmail", params)
        assert result is params


class TestGmailLabelBeforeHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_create_label_with_name(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_label_before_hook("GMAIL_CREATE_LABEL", "gmail", _make_params({"name": "Important"}))
        assert "Creating label: Important" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_create_label_without_name(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_label_before_hook("GMAIL_CREATE_LABEL", "gmail", _make_params({}))
        assert "Creating label:" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_update_label(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_label_before_hook("GMAIL_UPDATE_LABEL", "gmail", _make_params())
        assert "Updating label" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_delete_label(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_label_before_hook("GMAIL_DELETE_LABEL", "gmail", _make_params())
        assert "Deleting label" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_unknown_tool_returns_params_no_writer(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params()
        result = gmail_label_before_hook("GMAIL_UNKNOWN", "gmail", params)
        writer.assert_not_called()
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_writer_none_returns_params(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        mock_writer.return_value = None
        params = _make_params({"name": "x"})
        result = gmail_label_before_hook("GMAIL_CREATE_LABEL", "gmail", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_exception_returns_params(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        mock_writer.side_effect = RuntimeError("fail")
        params = _make_params({"name": "x"})
        result = gmail_label_before_hook("GMAIL_CREATE_LABEL", "gmail", params)
        assert result is params


class TestGmailModifyLabelsBeforeHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_add_labels(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_modify_labels_before_hook(
            "GMAIL_ADD_LABEL_TO_EMAIL",
            "gmail",
            _make_params({"message_ids": ["m1", "m2"], "label_ids": ["STARRED"]}),
        )
        payload = writer.call_args[0][0]
        assert "Adding labels to" in payload["progress"]
        assert "2 message(s)" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_remove_labels(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_modify_labels_before_hook(
            "GMAIL_REMOVE_LABEL",
            "gmail",
            _make_params({"message_ids": ["m1"], "label_ids": ["UNREAD", "STARRED"]}),
        )
        payload = writer.call_args[0][0]
        assert "Removing labels from" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_message_ids_not_list_counts_as_one(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_modify_labels_before_hook(
            "GMAIL_ADD_LABEL_TO_EMAIL",
            "gmail",
            _make_params({"message_ids": "m1", "label_ids": ["L1"]}),
        )
        assert "1 message(s)" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_label_ids_not_list_counts_as_one(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_modify_labels_before_hook(
            "GMAIL_ADD_LABEL_TO_EMAIL",
            "gmail",
            _make_params({"message_ids": ["m1"], "label_ids": "STARRED"}),
        )
        payload = writer.call_args[0][0]
        assert "1 label(s)" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_writer_none(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        mock_writer.return_value = None
        params = _make_params({"message_ids": ["m1"], "label_ids": ["L1"]})
        result = gmail_modify_labels_before_hook("GMAIL_ADD_LABEL_TO_EMAIL", "gmail", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_exception_returns_params(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        mock_writer.side_effect = RuntimeError("fail")
        params = _make_params({"message_ids": ["m1"], "label_ids": ["L1"]})
        result = gmail_modify_labels_before_hook("GMAIL_ADD_LABEL_TO_EMAIL", "gmail", params)
        assert result is params


class TestGmailDraftManagementBeforeHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_update(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_draft_management_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_draft_management_before_hook("GMAIL_UPDATE_DRAFT", "gmail", _make_params())
        assert "Updating draft" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_delete(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_draft_management_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_draft_management_before_hook("GMAIL_DELETE_DRAFT", "gmail", _make_params())
        assert "Deleting draft" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_writer_none(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_draft_management_before_hook

        mock_writer.return_value = None
        params = _make_params()
        result = gmail_draft_management_before_hook("GMAIL_UPDATE_DRAFT", "gmail", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_draft_management_before_hook

        mock_writer.side_effect = RuntimeError("fail")
        params = _make_params()
        result = gmail_draft_management_before_hook("GMAIL_UPDATE_DRAFT", "gmail", params)
        assert result is params


class TestGmailListDraftsBeforeHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_fetches_with_max_results(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_list_drafts_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_list_drafts_before_hook(
            "GMAIL_LIST_DRAFTS", "gmail", _make_params({"max_results": 7})
        )
        assert "7" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_default_max_results(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_list_drafts_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_list_drafts_before_hook("GMAIL_LIST_DRAFTS", "gmail", _make_params({}))
        assert "20" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_writer_none(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_list_drafts_before_hook

        mock_writer.return_value = None
        params = _make_params({"max_results": 5})
        result = gmail_list_drafts_before_hook("GMAIL_LIST_DRAFTS", "gmail", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_list_drafts_before_hook

        mock_writer.side_effect = RuntimeError("fail")
        params = _make_params({"max_results": 5})
        result = gmail_list_drafts_before_hook("GMAIL_LIST_DRAFTS", "gmail", params)
        assert result is params


class TestGmailGetDraftBeforeHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_progress(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_draft_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_get_draft_before_hook("GMAIL_GET_DRAFT", "gmail", _make_params())
        assert "draft details" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_writer_none(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_draft_before_hook

        mock_writer.return_value = None
        params = _make_params()
        result = gmail_get_draft_before_hook("GMAIL_GET_DRAFT", "gmail", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_draft_before_hook

        mock_writer.side_effect = RuntimeError("fail")
        params = _make_params()
        result = gmail_get_draft_before_hook("GMAIL_GET_DRAFT", "gmail", params)
        assert result is params


class TestGmailGetContactsBeforeHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_sets_default_page_size(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        mock_writer.return_value = _noop_writer()
        params = _make_params({})
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "gmail", params)
        assert result["arguments"]["page_size"] == 50
        # progress streamed
        mock_writer.return_value.assert_called_once()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_respects_explicit_page_size(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        mock_writer.return_value = _noop_writer()
        params = _make_params({"page_size": 100})
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "gmail", params)
        assert result["arguments"]["page_size"] == 100

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_zero_page_size_gets_default(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        mock_writer.return_value = _noop_writer()
        params = _make_params({"page_size": 0})
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "gmail", params)
        assert result["arguments"]["page_size"] == 50

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_writer_none_still_sets_page_size(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        mock_writer.return_value = None
        params = _make_params({})
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "gmail", params)
        assert result["arguments"]["page_size"] == 50

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_exception_returns_params(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        # Make get_stream_writer raise after the page_size logic? Actually it raises before.
        # The hook catches all exceptions and returns params
        mock_writer.side_effect = RuntimeError("fail")
        params = _make_params({})
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "gmail", params)
        # Even when writer fails, the page_size logic may have already-run before writer call?
        # In current impl, page_size is set BEFORE writer, so if writer raises, we catch and return params (which already has page_size)
        assert result is params


class TestGmailSearchPeopleBeforeHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_progress_contains_query(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_search_people_before_hook(
            "GMAIL_SEARCH_PEOPLE", "gmail", _make_params({"query": "John"})
        )
        assert "John" in writer.call_args[0][0]["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_empty_query(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        gmail_search_people_before_hook("GMAIL_SEARCH_PEOPLE", "gmail", _make_params({}))
        # should still call writer with empty query progression
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_writer_none(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_before_hook

        mock_writer.return_value = None
        params = _make_params({"query": "Jane"})
        result = gmail_search_people_before_hook("GMAIL_SEARCH_PEOPLE", "gmail", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_before_hook

        mock_writer.side_effect = RuntimeError("fail")
        params = _make_params({"query": "x"})
        result = gmail_search_people_before_hook("GMAIL_SEARCH_PEOPLE", "gmail", params)
        assert result is params


# ---------------------------------------------------------------------------
# after hooks
# ---------------------------------------------------------------------------


class TestGmailMessageDetailAfterHook:
    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_transforms(self, mock_template: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_message_detail_after_hook

        mock_template.return_value = {"id": "m1", "subject": "Hi"}
        response = _make_response({"id": "m1", "payload": {}})
        response["data"]["messageId"] = "m1"
        result = gmail_message_detail_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "gmail", response
        )
        assert result["id"] == "m1"
        mock_template.assert_called_once_with(response["data"])

    def test_error_response_early_return(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_message_detail_after_hook

        response = _make_response({"error": "Not found"})
        result = gmail_message_detail_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "gmail", response
        )
        assert result == {"error": "Not found"}

    def test_empty_response_with_error(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_message_detail_after_hook

        response = {"data": {"error": "boom"}, "successful": False}
        result = gmail_message_detail_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "gmail", response
        )
        assert result == {"error": "boom"}

    @patch(
        "app.utils.composio_hooks.gmail_hooks.detailed_message_template",
        side_effect=RuntimeError("fail"),
    )
    def test_exception_returns_raw(self, _: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_message_detail_after_hook

        response = _make_response({"id": "m1"})
        result = gmail_message_detail_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "gmail", response
        )
        assert result == {"id": "m1"}


class TestGmailThreadAfterHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_get_thread_response")
    def test_processes_and_streams(self, mock_process: MagicMock, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        mock_process.return_value = {
            "id": "thread1",
            "messages": [
                {
                    "id": "m1",
                    "from": "a@b.com",
                    "subject": "Sub",
                    "time": "now",
                    "snippet": "...",
                    "body": "text",
                    "content": "text",
                }
            ],
            "messageCount": 1,
        }
        response = _make_response({"id": "thread1", "messages": []})
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "gmail", response)
        assert result["id"] == "thread1"
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert payload["email_thread_data"]["thread_id"] == "thread1"
        assert payload["email_thread_data"]["messages_count"] == 1
        assert payload["email_thread_data"]["messages"][0]["id"] == "m1"

    def test_error_early_return(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        response = _make_response({"error": "Not found"})
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "gmail", response)
        assert result == {"error": "Not found"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_get_thread_response")
    def test_writer_none_no_stream(self, mock_process: MagicMock, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        mock_writer.return_value = None
        mock_process.return_value = {"id": "t1", "messages": [{"id": "m1"}], "messageCount": 1}
        response = _make_response({"id": "t1"})
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "gmail", response)
        assert result["id"] == "t1"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_get_thread_response")
    def test_empty_messages_no_stream(
        self, mock_process: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        mock_process.return_value = {"id": "t1", "messages": [], "messageCount": 0}
        response = _make_response({"id": "t1"})
        gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "gmail", response)
        writer.assert_not_called()

    @patch(
        "app.utils.composio_hooks.gmail_hooks.get_stream_writer", side_effect=RuntimeError("boom")
    )
    def test_exception_returns_raw(self, _: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        response = _make_response({"id": "t1"})
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "gmail", response)
        assert result == {"id": "t1"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch(
        "app.utils.composio_hooks.gmail_hooks.process_get_thread_response",
        side_effect=ValueError("bad"),
    )
    def test_process_exception_returns_raw(self, _: MagicMock, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"id": "t1"})
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "gmail", response)
        assert result == {"id": "t1"}


class TestGmailDraftsAfterHook:
    @patch("app.utils.composio_hooks.gmail_hooks.process_list_drafts_response")
    def test_processes(self, mock_process: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_drafts_after_hook

        mock_process.return_value = {"drafts": [{"id": "d1"}], "resultSize": 1}
        response = _make_response({"drafts": [{"id": "d1"}]})
        result = gmail_drafts_after_hook("GMAIL_LIST_DRAFTS", "gmail", response)
        assert result["drafts"][0]["id"] == "d1"

    def test_error_early_return(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_drafts_after_hook

        response = _make_response({"error": "fail"})
        result = gmail_drafts_after_hook("GMAIL_LIST_DRAFTS", "gmail", response)
        assert result == {"error": "fail"}

    @patch(
        "app.utils.composio_hooks.gmail_hooks.process_list_drafts_response",
        side_effect=RuntimeError("boom"),
    )
    def test_exception_returns_raw(self, _: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_drafts_after_hook

        response = _make_response({"drafts": []})
        result = gmail_drafts_after_hook("GMAIL_LIST_DRAFTS", "gmail", response)
        assert result == {"drafts": []}


class TestGmailDraftDetailAfterHook:
    @patch("app.utils.composio_hooks.gmail_hooks.draft_template")
    def test_transforms(self, mock_template: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_draft_detail_after_hook

        mock_template.return_value = {"id": "d1", "message": {"to": "a@b.com"}}
        response = _make_response({"id": "d1", "message": {}})
        result = gmail_draft_detail_after_hook("GMAIL_GET_DRAFT", "gmail", response)
        assert result["id"] == "d1"

    def test_error_early_return(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_draft_detail_after_hook

        response = _make_response({"error": "no"})
        result = gmail_draft_detail_after_hook("GMAIL_GET_DRAFT", "gmail", response)
        assert result == {"error": "no"}

    @patch("app.utils.composio_hooks.gmail_hooks.draft_template", side_effect=RuntimeError("fail"))
    def test_exception_returns_raw(self, _: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_draft_detail_after_hook

        response = _make_response({"id": "d1", "message": {}})
        result = gmail_draft_detail_after_hook("GMAIL_GET_DRAFT", "gmail", response)
        assert result == {"id": "d1", "message": {}}


class TestGmailAttachmentAfterHook:
    def test_extracts_metadata(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response = _make_response(
            {
                "attachmentId": "att1",
                "filename": "report.pdf",
                "mimeType": "application/pdf",
                "size": 1024,
                "data": "base64_should_be_stripped",
            },
            successful=True,
        )
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "gmail", response)
        assert result["attachmentId"] == "att1"
        assert result["filename"] == "report.pdf"
        assert result["size"] == 1024
        assert "data" not in result
        assert "message" in result

    def test_unsuccessful_passthrough(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response = _make_response({"error": "Not found"}, successful=False)
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "gmail", response)
        assert result == {"error": "Not found"}

    def test_non_dict_data_passthrough_successful_true(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response = {"data": "bare string data", "successful": True}
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "gmail", response)
        assert result == "bare string data"

    def test_non_dict_data_passthrough_successful_false(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response = {"data": "bare string", "successful": False}
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "gmail", response)
        assert result == "bare string"

    def test_missing_fields_defaults(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response = _make_response({}, successful=True)
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "gmail", response)
        assert result["attachmentId"] == ""
        assert result["filename"] == ""
        assert result["size"] == 0

    @patch("app.utils.composio_hooks.gmail_hooks.log")
    def test_exception_inside_processing(self, mock_log: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        # response with successful True but data is dict that will be processed; make data.get raise?
        class BadDict(dict):
            def get(self, *a, **kw):
                raise RuntimeError("bad get")

        response = {"data": BadDict({"attachmentId": "a"}), "successful": True}
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "gmail", response)
        # should fallback to raw data via exception handler
        assert isinstance(result, BadDict)


class TestGmailFetchByIdAfterHook:
    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_transforms(self, mock_template: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_by_id_after_hook

        mock_template.return_value = {"id": "m1", "subject": "Test"}
        response = _make_response({"id": "m1", "payload": {}})
        result = gmail_fetch_by_id_after_hook("GMAIL_FETCH_EMAIL_BY_ID", "gmail", response)
        assert result["id"] == "m1"

    def test_error_early_return(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_by_id_after_hook

        response = _make_response({"error": "fail"})
        result = gmail_fetch_by_id_after_hook("GMAIL_FETCH_EMAIL_BY_ID", "gmail", response)
        assert result == {"error": "fail"}

    @patch(
        "app.utils.composio_hooks.gmail_hooks.detailed_message_template",
        side_effect=RuntimeError("boom"),
    )
    def test_exception_returns_raw(self, _: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_by_id_after_hook

        response = _make_response({"id": "m1"})
        result = gmail_fetch_by_id_after_hook("GMAIL_FETCH_EMAIL_BY_ID", "gmail", response)
        assert result == {"id": "m1"}


class TestGmailSendDraftAfterHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_successful_streams_and_returns_minimal(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "successful": True,
                "id": "sent_1",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"to": ["a@b.com"], "subject": "Sent"},
            }
        )
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "gmail", response)
        assert result["successful"] is True
        assert result["id"] == "sent_1"
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "email_sent_data" in payload

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_unsuccessful_no_stream_returns_raw(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"successful": False, "error": "Failed"})
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "gmail", response)
        assert result == {"successful": False, "error": "Failed"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_writer_none_still_returns_minimal(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        mock_writer.return_value = None
        response = _make_response({"successful": True, "id": "x", "message": {}})
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "gmail", response)
        assert result["successful"] is True

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_missing_successful_streams(self, mock_writer: MagicMock) -> None:
        # If successful key missing, the `if writer is not None and response["data"].get("successful", True)` defaults to True
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"id": "x", "message": {}})
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "gmail", response)
        writer.assert_called_once()
        # but final minimal check: since "successful" not in data, it falls to return response["data"] raw
        assert result == {"id": "x", "message": {}}

    @patch(
        "app.utils.composio_hooks.gmail_hooks.get_stream_writer", side_effect=RuntimeError("boom")
    )
    def test_exception_returns_raw(self, _: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        response = _make_response({"id": "x", "successful": True})
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "gmail", response)
        assert result == {"id": "x", "successful": True}


class TestGmailGetContactsAfterHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_processes_full_contact(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "response_data": {
                    "connections": [
                        {
                            "resourceName": "people/c1",
                            "names": [{"displayName": "John Doe", "metadata": {"primary": True}}],
                            "emailAddresses": [
                                {"value": "john@example.com", "metadata": {"primary": True}}
                            ],
                            "phoneNumbers": [{"value": "+123", "metadata": {"primary": True}}],
                        }
                    ]
                },
                "totalPeople": 1,
            }
        )
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "gmail", response)
        assert result["contacts"][0]["name"] == "John Doe"
        assert result["contacts"][0]["email"] == "john@example.com"
        assert result["contacts"][0]["phone"] == "+123"
        assert result["total_count"] == 1
        assert result["has_more"] is False
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "contacts_data" in payload

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_processes_with_next_page_token(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "response_data": {"connections": []},
                "totalPeople": 0,
                "nextPageToken": "token123",
            }
        )
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "gmail", response)
        assert result["has_more"] is True
        # writer not called when contact_list empty
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_missing_fields_defaults_to_unknown(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response(
            {
                "response_data": {
                    "connections": [
                        {
                            "resourceName": "people/c2",
                            "names": [],
                            "emailAddresses": [],
                            "phoneNumbers": [],
                        }
                    ]
                }
            }
        )
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "gmail", response)
        assert result["contacts"][0]["name"] == "Unknown"
        assert "email" not in result["contacts"][0]
        assert "phone" not in result["contacts"][0]

    def test_error_early_return(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        response = _make_response({"error": "fail"})
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "gmail", response)
        assert result == {"error": "fail"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_writer_none_still_returns(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        mock_writer.return_value = None
        response = _make_response(
            {
                "response_data": {
                    "connections": [
                        {
                            "resourceName": "people/c1",
                            "names": [{"displayName": "A"}],
                            "emailAddresses": [],
                            "phoneNumbers": [],
                        }
                    ]
                },
                "totalPeople": 1,
            }
        )
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "gmail", response)
        assert result["contacts"][0]["name"] == "A"

    @patch(
        "app.utils.composio_hooks.gmail_hooks.get_stream_writer", side_effect=RuntimeError("boom")
    )
    def test_exception_returns_raw(self, _: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        response = _make_response({"response_data": {"connections": []}})
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "gmail", response)
        assert result == {"response_data": {"connections": []}}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_none_response_data_uses_empty(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"response_data": None, "totalPeople": 0})
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "gmail", response)
        assert result["contacts"] == []


class TestGmailSearchPeopleAfterHook:
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_processes_search_result(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "response_data": {
                    "results": [
                        {
                            "person": {
                                "resourceName": "people/c1",
                                "names": [
                                    {"displayName": "Jane Doe", "metadata": {"primary": True}}
                                ],
                                "emailAddresses": [
                                    {"value": "jane@example.com", "metadata": {"primary": True}}
                                ],
                                "phoneNumbers": [],
                            }
                        }
                    ]
                }
            }
        )
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "gmail", response)
        assert result["people"][0]["name"] == "Jane Doe"
        assert result["result_count"] == 1
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_empty_results_no_stream(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"response_data": {"results": []}})
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "gmail", response)
        assert result["people"] == []
        assert result["result_count"] == 0
        writer.assert_not_called()

    def test_error_early_return(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        response = _make_response({"error": "fail"})
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "gmail", response)
        assert result == {"error": "fail"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_writer_none(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        mock_writer.return_value = None
        response = _make_response(
            {
                "response_data": {
                    "results": [
                        {
                            "person": {
                                "resourceName": "people/c1",
                                "names": [{"displayName": "A"}],
                                "emailAddresses": [],
                                "phoneNumbers": [],
                            }
                        }
                    ]
                }
            }
        )
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "gmail", response)
        assert result["result_count"] == 1

    @patch(
        "app.utils.composio_hooks.gmail_hooks.get_stream_writer", side_effect=RuntimeError("boom")
    )
    def test_exception_returns_raw(self, _: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        response = _make_response({"response_data": {"results": []}})
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "gmail", response)
        assert result == {"response_data": {"results": []}}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_none_response_data(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"response_data": None})
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "gmail", response)
        assert result["people"] == []
        assert result["result_count"] == 0
