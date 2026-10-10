"""Unit tests for app/models/composio_schemas/gmail.py."""

from app.models.composio_schemas.gmail import GmailNewMessagePayload


class TestGmailNewMessagePayload:
    # Field set verified against Composio triggers_types API (2026-08).
    def test_valid_thread_fields(self):
        m = GmailNewMessagePayload(
            id="msg-raw-id",
            message_id="18a1b2c3",
            thread_id="thd-123",
            sender="acme@x.com",
            to="me@gmail.com",
            subject="Re: Invoice",
            message_text="Paid today",
            label_ids=["INBOX", "IMPORTANT"],
            attachment_list=[{"filename": "receipt.pdf"}],
        )
        assert m.thread_id == "thd-123"
        assert m.id == "msg-raw-id"
        assert m.label_ids == ["INBOX", "IMPORTANT"]
        assert m.to == "me@gmail.com"

    def test_valid_minimal(self):
        m = GmailNewMessagePayload()
        assert m.thread_id is None
        assert m.preview is None


# ---------------------------------------------------------------------------
# notion trigger payloads
# ---------------------------------------------------------------------------
