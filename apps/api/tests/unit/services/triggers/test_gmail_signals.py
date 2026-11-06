"""Gmail signals derived at dispatch: what the gate and every condition read off a new message.

The absent cases matter as much as the set ones: a payload with no headers must
not claim the mail is free of List-Unsubscribe, or a todo condition would act on
a fact the event never carried.
"""

import base64
import json
from typing import ClassVar

import pytest

from app.agents.templates.mail_templates import build_message_view, project_message_view
from app.models.composio_schemas.gmail import GmailMessageView
from app.models.integrations.gmail_messages import RelayedGmailMessage
from app.services.triggers.gmail_signals import (
    fetched_message_payload,
    gmail_gate_view,
    gmail_message_signals,
)
from app.services.triggers.handlers.gmail import gmail_trigger_handler
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit


async def test_an_unreadable_payload_derives_nothing_and_warns_with_the_error_clipped() -> None:
    unreadable = {"label_ids": "INBOX", "thread_id": 5, "subject": 7, "attachment_list": "x"}

    async with captured_wide_event() as event:
        assert gmail_message_signals(unreadable) == {}

    (warning,) = event["warnings"]
    assert warning["msg"] == "[TRIGGER] Gmail payload unreadable for signals; none derived"
    assert warning["error"].startswith("4 validation errors for _GmailMessage")
    assert len(warning["error"]) == 300


def _headers(**values: str) -> dict[str, object]:
    return {
        "payload": {
            "headers": [{"name": k.replace("_", "-"), "value": v} for k, v in values.items()]
        }
    }


class TestThread:
    def test_the_first_message_of_a_thread_does_not_continue_it(self) -> None:
        assert (
            gmail_message_signals({"thread_id": "a1", "message_id": "a1"})["continues_thread"]
            is False
        )

    def test_a_later_message_continues_its_thread(self) -> None:
        assert (
            gmail_message_signals({"thread_id": "a1", "message_id": "b2"})["continues_thread"]
            is True
        )

    def test_either_message_id_naming_the_thread_marks_it_first(self) -> None:
        signals = gmail_message_signals({"thread_id": "a1", "message_id": "<x@mail>", "id": "a1"})
        assert signals["continues_thread"] is False

    def test_no_thread_id_leaves_the_signal_out(self) -> None:
        assert "continues_thread" not in gmail_message_signals({"message_id": "b2"})

    def test_an_empty_message_id_names_no_thread(self) -> None:
        assert "continues_thread" not in gmail_message_signals(
            {"thread_id": "a1", "message_id": ""}
        )


class TestHeaders:
    def test_list_unsubscribe_is_read_case_blind(self) -> None:
        signals = gmail_message_signals(
            {"payload": {"headers": [{"name": "LIST-UNSUBSCRIBE", "value": "<mailto:x>"}]}}
        )
        assert signals["has_list_unsubscribe"] is True

    @pytest.mark.parametrize(
        ("headers", "expected"),
        [
            ({"Precedence": "bulk"}, True),
            ({"Precedence": "List"}, True),
            ({"Auto_Submitted": "auto-generated"}, True),
            ({"Auto_Submitted": "no"}, False),
            ({"Precedence": "first-class"}, False),
            ({}, False),
        ],
    )
    def test_bulk_or_auto_submitted(self, headers: dict[str, str], expected: bool) -> None:
        assert gmail_message_signals(_headers(**headers))["bulk_or_auto_submitted"] is expected

    def test_no_headers_leaves_every_header_signal_out(self) -> None:
        signals = gmail_message_signals({"sender": "a@b.com"})
        assert "has_list_unsubscribe" not in signals
        assert "bulk_or_auto_submitted" not in signals

    def test_one_null_header_value_still_yields_every_signal(self) -> None:
        signals = gmail_message_signals(
            {
                "thread_id": "a1",
                "message_id": "a1",
                "sender": "Priya <priya@acme.com>",
                "label_ids": ["INBOX", "CATEGORY_PERSONAL"],
                "payload": {
                    "headers": [
                        {"name": "X-Relay", "value": None},
                        {"name": "Precedence", "value": "bulk"},
                    ]
                },
            }
        )
        assert signals == {
            "continues_thread": False,
            "gmail_category": "CATEGORY_PERSONAL",
            "sender_looks_automated": False,
            "has_list_unsubscribe": False,
            "bulk_or_auto_submitted": True,
        }


class TestSenderAndLabels:
    @pytest.mark.parametrize(
        ("sender", "expected"),
        [
            ("Stripe <notifications@stripe.com>", True),
            ("NoReply <NOREPLY@x.io>", True),
            ("noreply@x.io", True),
            ("Priya <priya@acme.com>", False),
            # The eval read the address, never the display name.
            ("Notifications Team <priya@acme.com>", False),
        ],
    )
    def test_sender_looks_automated(self, sender: str, expected: bool) -> None:
        assert gmail_message_signals({"sender": sender})["sender_looks_automated"] is expected

    def test_the_category_label_is_picked_out(self) -> None:
        signals = gmail_message_signals({"label_ids": ["UNREAD", "CATEGORY_UPDATES", "INBOX"]})
        assert signals["gmail_category"] == "CATEGORY_UPDATES"

    def test_no_category_label_leaves_it_out(self) -> None:
        assert "gmail_category" not in gmail_message_signals({"label_ids": ["INBOX"]})


def _message(**overrides: object) -> dict[str, object]:
    return {
        "thread_id": "a1",
        "message_id": "b2",
        "sender": "Priya Raman <priya@northwind.dev>",
        "to": "user@acme.com",
        "subject": "Re: pilot",
        "message_text": "Hi,\n\n  are we   still on\tfor 4pm?",
        "label_ids": ["UNREAD", "CATEGORY_PERSONAL", "INBOX"],
        "attachment_list": [{"filename": "a.pdf"}, {"filename": "b.png"}],
        "payload": {
            "headers": [
                {"name": "Cc", "value": "sam@northwind.dev"},
                {"name": "In-Reply-To", "value": "<x@mail>"},
            ]
        },
        **overrides,
    }


class TestGateView:
    def test_the_view_is_the_evals_v4_event_field_for_field(self) -> None:
        view = gmail_gate_view(_message())

        assert view is not None
        assert json.dumps(view.as_event()) == json.dumps(
            {
                "from": "Priya Raman <priya@northwind.dev>",
                "to": "user@acme.com",
                "cc": "sam@northwind.dev",
                "subject": "Re: pilot",
                "snippet": "Hi, are we still on for 4pm?",
                "gmail_labels": ["UNREAD", "CATEGORY_PERSONAL", "INBOX"],
                "attachments": 2,
                "is_reply": True,
                "gmail_category": "CATEGORY_PERSONAL",
                "has_list_unsubscribe": False,
                "bulk_or_auto_submitted": False,
                "sender_looks_automated": False,
            }
        )
        assert view.continues_thread is True

    def test_the_snippet_is_the_first_300_characters_of_the_text(self) -> None:
        view = gmail_gate_view(_message(message_text="word " * 200))

        assert view is not None
        assert view.snippet == ("word " * 60)[:300]

    def test_no_in_reply_to_is_not_a_reply_and_no_cc_is_empty(self) -> None:
        view = gmail_gate_view(_message(payload={"headers": [{"name": "Subject", "value": "x"}]}))

        assert view is not None
        assert (view.is_reply, view.cc) == (False, "")

    def test_a_null_header_value_reads_empty(self) -> None:
        view = gmail_gate_view(_message(payload={"headers": [{"name": "Cc", "value": None}]}))

        assert view is not None
        assert view.cc == ""

    def test_a_missing_field_reads_empty_and_an_unknown_signal_reads_null(self) -> None:
        view = gmail_gate_view({"thread_id": "a1", "message_id": "a1"})

        assert view is not None
        event = view.as_event()
        assert (
            event["from"],
            event["to"],
            event["subject"],
            event["snippet"],
            event["attachments"],
        ) == ("", "", "", "", 0)
        assert (event["is_reply"], event["has_list_unsubscribe"], event["gmail_category"]) == (
            None,
            None,
            None,
        )
        assert view.continues_thread is False

    def test_an_unreadable_payload_has_no_view(self) -> None:
        assert gmail_gate_view({"label_ids": "INBOX"}) is None


class TestAFetchedMessage:
    """A message a run fetched itself reads to the gate as the same mail's webhook would."""

    RAW: ClassVar[dict[str, object]] = {
        "id": "m2",
        "threadId": "t1",
        "labelIds": ["INBOX", "CATEGORY_UPDATES"],
        "snippet": "the snippet",
        "payload": {
            "headers": [
                {"name": "From", "value": "Infisical <team@infisical.com>"},
                {"name": "To", "value": "aryan@heygaia.io"},
                {"name": "Cc", "value": "ops@heygaia.io"},
                {"name": "Subject", "value": "Successful login from new device"},
                {"name": "In-Reply-To", "value": "<m1@infisical.com>"},
                {"name": "List-Unsubscribe", "value": "<mailto:u@infisical.com>"},
            ],
            "body": {"data": base64.urlsafe_b64encode(b"We noticed a  new\nlogin.").decode()},
        },
    }

    def _view(self) -> GmailMessageView:
        return build_message_view(RelayedGmailMessage.model_validate(self.RAW), "normalize")

    def test_its_gate_view_carries_the_headers_and_the_body(self) -> None:
        attachment = {"filename": "a.pdf", "mimeType": None, "size": 1, "attachmentId": "x"}
        fetched = self._view().model_copy(update={"attachments": [attachment]})
        view = gmail_gate_view(fetched_message_payload(fetched))

        assert view is not None
        event = view.as_event()
        assert event["from"] == "Infisical <team@infisical.com>"
        assert event["to"] == "aryan@heygaia.io"
        assert event["attachments"] == 1
        assert event["cc"] == "ops@heygaia.io"
        assert event["subject"] == "Successful login from new device"
        assert event["snippet"] == "We noticed a new login."
        assert event["gmail_category"] == "CATEGORY_UPDATES"
        assert event["has_list_unsubscribe"] is True
        assert event["is_reply"] is True
        assert view.continues_thread is True

    def test_the_headers_never_reach_the_agent(self) -> None:
        assert "headers" not in project_message_view(self._view(), None)


class TestHandler:
    def test_inbound_mail_gets_the_signals(self) -> None:
        signals = gmail_trigger_handler.event_signals(
            "GMAIL_NEW_GMAIL_MESSAGE", {"thread_id": "a1", "message_id": "b2"}
        )
        assert signals["continues_thread"] is True

    def test_sent_mail_gets_none(self) -> None:
        signals = gmail_trigger_handler.event_signals(
            "GMAIL_EMAIL_SENT_TRIGGER", {"thread_id": "a1", "message_id": "b2"}
        )
        assert signals == {}
