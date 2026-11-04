"""Gmail signals derived at dispatch: what the gate and every condition read off a new message.

The absent cases matter as much as the set ones: a payload with no headers must
not claim the mail is free of List-Unsubscribe, or a run_when/skip_when rule would
act on a fact the event never carried.
"""

import json

import pytest

from app.services.triggers.gmail_signals import gmail_gate_view, gmail_message_signals
from app.services.triggers.handlers.gmail import gmail_trigger_handler

pytestmark = pytest.mark.unit


def test_an_unreadable_payload_derives_nothing() -> None:
    assert (
        gmail_message_signals({"label_ids": "INBOX", "thread_id": "a1", "message_id": "b2"}) == {}
    )


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

    def test_a_missing_field_reads_empty_and_an_unknown_signal_reads_null(self) -> None:
        view = gmail_gate_view({"thread_id": "a1", "message_id": "a1"})

        assert view is not None
        event = view.as_event()
        assert (event["from"], event["to"], event["snippet"], event["attachments"]) == (
            "",
            "",
            "",
            0,
        )
        assert (event["is_reply"], event["has_list_unsubscribe"], event["gmail_category"]) == (
            None,
            None,
            None,
        )
        assert view.continues_thread is False

    def test_an_unreadable_payload_has_no_view(self) -> None:
        assert gmail_gate_view({"label_ids": "INBOX"}) is None


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
