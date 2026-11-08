"""Signals derived once from a new Gmail message, and the message as a trigger gate shows it to JEV.

Free and deterministic: read off the payload and its headers, no network. A signal
the payload cannot back is left out of the matchable fields rather than set false,
so a condition on it does not match; the gate view sends it as null.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from email.utils import parseaddr

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.constants.log_tags import LogTag
from app.constants.todos import INBOX_DESK_AUTOMATED_SENDERS
from app.constants.trigger_gates import TRIGGER_GATE_FIELD_MAX_CHARS
from app.models.composio_schemas.gmail import GmailHeader, GmailMessageView
from shared.py.wide_events import log

_GMAIL_CATEGORY_PREFIX = "CATEGORY_"
_BULK_PRECEDENCE = frozenset({"bulk", "list", "junk"})
_NOT_AUTO_SUBMITTED = frozenset({"", "no"})
_GMAIL_SENT_LABEL = "SENT"


class _MessagePart(BaseModel):
    headers: list[GmailHeader] | None = None


class _GmailMessage(BaseModel):
    """The slice of a GMAIL_NEW_GMAIL_MESSAGE payload the signals and the gate view read."""

    thread_id: str | None = None
    message_id: str | None = None
    id: str | None = None
    label_ids: list[str] | None = None
    sender: str | None = None
    to: str | None = None
    subject: str | None = None
    message_text: str | None = None
    attachment_list: list[object] | None = None
    payload: _MessagePart | None = None

    @property
    def headers(self) -> list[GmailHeader] | None:
        return self.payload.headers if self.payload is not None else None

    def header(self, name: str) -> str:
        """Return a header's trimmed value, name given in lower case; empty when absent or null."""
        return next(
            ((h.value or "").strip() for h in self.headers or () if h.name.lower() == name),
            "",
        )


@dataclass(frozen=True, slots=True)
class _Signals:
    continues_thread: bool | None
    gmail_category: str | None
    sender_looks_automated: bool | None
    has_list_unsubscribe: bool | None
    bulk_or_auto_submitted: bool | None


class GmailGateView(BaseModel):
    """A new message as a trigger gate's JEV request reads it: the eval's V4 event, field for field.

    continues_thread drives the free run rule by day; it and the raw header values feed
    the email verdict's own state and are never sent here.
    """

    model_config = ConfigDict(frozen=True)

    sender: str = Field(serialization_alias="from")
    to: str
    cc: str
    subject: str
    snippet: str
    gmail_labels: list[str]
    attachments: int
    is_reply: bool | None
    gmail_category: str | None
    has_list_unsubscribe: bool | None
    bulk_or_auto_submitted: bool | None
    sender_looks_automated: bool | None
    continues_thread: bool | None = Field(exclude=True)
    # Gmail's own id for the message, the key its verdict is kept under: id first, then message_id.
    gmail_id: str | None = Field(default=None, exclude=True)
    precedence: str = Field(default="", exclude=True)
    auto_submitted: str = Field(default="", exclude=True)

    def as_event(self) -> dict[str, object]:
        """Return the event JEV reads, keyed and ordered as the eval sent it."""
        return self.model_dump(by_alias=True)

    @property
    def latest_from_other(self) -> bool:
        """Whether the message is someone else's, not one the user sent."""
        return _GMAIL_SENT_LABEL not in self.gmail_labels

    def as_email(self) -> dict[str, object]:
        """Return the message as a person sees it in their inbox, for the email verdict; no empty field."""
        name, address = parseaddr(self.sender)
        sender = {"name": name, "address": address or self.sender}
        email: dict[str, object] = {"from": {k: v for k, v in sender.items() if v}}
        fields = (("to", self.to), ("cc", self.cc), ("subject", self.subject))
        email |= {k: v for k, v in (*fields, ("snippet", self.snippet)) if v}
        if self.attachments:
            email["attachments"] = self.attachments
        headers: dict[str, object] = {}
        if self.has_list_unsubscribe:
            headers["list_unsubscribe"] = True
        if self.precedence:
            headers["precedence"] = self.precedence
        if self.auto_submitted.lower() not in _NOT_AUTO_SUBMITTED:
            headers["auto_submitted"] = self.auto_submitted
        if headers:
            email["headers"] = headers
        if self.gmail_category:
            email["gmail_category"] = self.gmail_category.removeprefix(
                _GMAIL_CATEGORY_PREFIX
            ).lower()
        return email


def _read(data: Mapping[str, object]) -> _GmailMessage | None:
    try:
        return _GmailMessage.model_validate(data)
    except ValidationError as e:
        log.warning(
            f"{LogTag.TRIGGER} Gmail payload unreadable for signals; none derived",
            error=str(e)[:300],
        )
        return None


def _derive(message: _GmailMessage) -> _Signals:
    message_ids = {message.message_id, message.id} - {None, ""}
    # Gmail names a thread after its first message.
    continues = message.thread_id not in message_ids if message.thread_id and message_ids else None
    sender = message.sender
    address = (parseaddr(sender)[1] or sender).lower() if sender else None
    has_headers = message.headers is not None
    return _Signals(
        continues_thread=continues,
        gmail_category=next(
            (lbl for lbl in message.label_ids or () if lbl.startswith(_GMAIL_CATEGORY_PREFIX)),
            None,
        ),
        sender_looks_automated=(
            any(t in address for t in INBOX_DESK_AUTOMATED_SENDERS) if address else None
        ),
        has_list_unsubscribe=(
            any(h.name.lower() == "list-unsubscribe" for h in message.headers or ())
            if has_headers
            else None
        ),
        bulk_or_auto_submitted=(
            message.header("precedence").lower() in _BULK_PRECEDENCE
            or message.header("auto-submitted").lower() not in _NOT_AUTO_SUBMITTED
            if has_headers
            else None
        ),
    )


def gmail_message_signals(data: Mapping[str, object]) -> dict[str, object]:
    """Return the derived fields GmailNewMessageEvent declares, for those the payload backs."""
    message = _read(data)
    if message is None:
        return {}
    return {k: v for k, v in asdict(_derive(message)).items() if v is not None}


def gmail_gate_view(data: Mapping[str, object]) -> GmailGateView | None:
    """Return the message as a gate shows it to JEV; None when the payload cannot be read."""
    message = _read(data)
    if message is None:
        return None
    signals = _derive(message)
    return GmailGateView(
        sender=message.sender or "",
        to=message.to or "",
        cc=message.header("cc"),
        subject=message.subject or "",
        snippet=" ".join((message.message_text or "").split())[:TRIGGER_GATE_FIELD_MAX_CHARS],
        gmail_labels=message.label_ids or [],
        attachments=len(message.attachment_list or ()),
        is_reply=bool(message.header("in-reply-to")) if message.headers is not None else None,
        gmail_category=signals.gmail_category,
        has_list_unsubscribe=signals.has_list_unsubscribe,
        bulk_or_auto_submitted=signals.bulk_or_auto_submitted,
        sender_looks_automated=signals.sender_looks_automated,
        continues_thread=signals.continues_thread,
        gmail_id=message.id or message.message_id or None,
        precedence=message.header("precedence"),
        auto_submitted=message.header("auto-submitted"),
    )


def fetched_message_payload(view: GmailMessageView) -> dict[str, object]:
    """Return a message a run fetched in the new-message payload shape the gate view reads."""
    return {
        "thread_id": view.thread_id,
        "message_id": view.id,
        "label_ids": view.labels,
        "sender": view.sender,
        "to": view.to,
        "subject": view.subject,
        "message_text": view.body or view.snippet,
        "attachment_list": view.attachments,
        "payload": {"headers": [header.model_dump() for header in view.headers]},
    }
