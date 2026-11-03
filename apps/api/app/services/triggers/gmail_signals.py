"""Signals derived once from a new Gmail message, before any workflow or todo sees it.

Free and deterministic: read off the payload and its headers, no network. A signal
the payload cannot back is left out rather than set false, so a condition on it
does not match and JEV does not read a guess.
"""

from collections.abc import Mapping

from pydantic import BaseModel, ValidationError

from app.constants.log_tags import LogTag
from app.constants.todos import INBOX_DESK_AUTOMATED_SENDERS
from shared.py.wide_events import log

_GMAIL_CATEGORY_PREFIX = "CATEGORY_"
_BULK_PRECEDENCE = frozenset({"bulk", "list", "junk"})
_NOT_AUTO_SUBMITTED = frozenset({"", "no"})


class _Header(BaseModel):
    name: str
    value: str


class _MessagePart(BaseModel):
    headers: list[_Header] | None = None


class _SignalSource(BaseModel):
    """The slice of a GMAIL_NEW_GMAIL_MESSAGE payload the signals read."""

    thread_id: str | None = None
    message_id: str | None = None
    id: str | None = None
    label_ids: list[str] | None = None
    sender: str | None = None
    payload: _MessagePart | None = None


def gmail_message_signals(data: Mapping[str, object]) -> dict[str, object]:
    """Return the derived fields GmailNewMessageEvent declares, for those the payload backs."""
    try:
        source = _SignalSource.model_validate(data)
    except ValidationError as e:
        log.warning(
            f"{LogTag.TRIGGER} Gmail payload unreadable for signals; none derived",
            error=str(e)[:300],
        )
        return {}
    signals: dict[str, object] = {}
    message_ids = {source.message_id, source.id} - {None, ""}
    if source.thread_id and message_ids:
        # Gmail names a thread after its first message.
        signals["continues_thread"] = source.thread_id not in message_ids
    category = next(
        (lbl for lbl in source.label_ids or () if lbl.startswith(_GMAIL_CATEGORY_PREFIX)), None
    )
    if category is not None:
        signals["gmail_category"] = category
    if source.sender:
        sender = source.sender.lower()
        signals["sender_looks_automated"] = any(t in sender for t in INBOX_DESK_AUTOMATED_SENDERS)
    if source.payload is not None and source.payload.headers is not None:
        headers = source.payload.headers
        signals["has_list_unsubscribe"] = any(h.name.lower() == "list-unsubscribe" for h in headers)
        signals["bulk_or_auto_submitted"] = (
            _header(headers, "precedence") in _BULK_PRECEDENCE
            or _header(headers, "auto-submitted") not in _NOT_AUTO_SUBMITTED
        )
    return signals


def _header(headers: list[_Header], name: str) -> str:
    """Return a header's value, trimmed and lowercased; empty when the message has none."""
    return next((h.value.strip().lower() for h in headers if h.name.lower() == name), "")
