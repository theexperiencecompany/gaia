import base64
import json
from typing import Any

from app.agents.templates.mail_templates import detailed_message_template
from app.services.chat_service import extract_tool_data
from app.utils.composio_hooks.gmail_hooks import (
    gmail_fetch_after_hook,
    gmail_thread_after_hook,
)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _gmail_message(message_id: str, body_html: str) -> dict[str, Any]:
    return {
        "id": message_id,
        "threadId": "thread-1",
        "snippet": "sample snippet",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": "text/html",
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "Project Update"},
                {"name": "Date", "value": "Tue, 16 Mar 2026 10:00:00 +0000"},
            ],
            "body": {"data": _b64(body_html)},
        },
    }


def test_detailed_message_template_returns_clean_text_only() -> None:
    message = _gmail_message(
        "msg-1",
        "<div>Hello\u200c<br>World</div><script>alert('x')</script>",
    )

    result = detailed_message_template(message)

    assert "Hello" in result["body"]
    assert "World" in result["body"]
    assert "alert" not in result["body"]
    assert "html" not in result["content"]
    assert result["body_meta"]["truncated"] is False


def test_gmail_thread_after_hook_streams_frontend_safe_text_payload(
    monkeypatch,
) -> None:
    streamed: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "app.utils.composio_hooks.gmail_hooks.get_stream_writer",
        lambda: lambda payload: streamed.append(payload),
    )

    message_html = (
        "<div>Primary update</div>"
        "<div>On Tue, Jan 9, Jane Doe &lt;jane@example.com&gt; wrote:</div>"
        "<div>&gt; Previous context</div>"
    )

    response = {
        "data": {
            "id": "thread-1",
            "messages": [_gmail_message("msg-1", message_html)],
        }
    }

    result = gmail_thread_after_hook(
        "GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
        "gmail",
        response,
    )

    assert streamed
    thread_payload = streamed[0]["email_thread_data"]
    first = thread_payload["messages"][0]

    assert first["content"]["text"]
    assert "html" not in first["content"]
    assert "On Tue, Jan 9" in first["body"]

    # LLM projection should stay compact and text-focused.
    llm_first = result["messages"][0]
    assert "content" not in llm_first
    assert "body" in llm_first


def test_gmail_fetch_after_hook_streams_email_list_card_shape(monkeypatch) -> None:
    streamed: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "app.utils.composio_hooks.gmail_hooks.get_stream_writer",
        lambda: lambda payload: streamed.append(payload),
    )

    response = {
        "data": {
            "messages": [
                _gmail_message(
                    "msg-2",
                    "<div>Status update</div><div>Thanks!</div>",
                )
            ],
            "nextPageToken": "next-1",
        }
    }

    result = gmail_fetch_after_hook("GMAIL_FETCH_EMAILS", "gmail", response)

    assert streamed
    list_payload = streamed[0]
    assert "email_fetch_data" in list_payload
    assert list_payload["email_fetch_data"][0]["id"] == "msg-2"
    assert list_payload["nextPageToken"] == "next-1"

    # LLM-facing response keeps cleaned text for reasoning.
    assert "messages" in result
    assert "body" in result["messages"][0]
    assert "Status update" in result["messages"][0]["body"]


def test_extract_tool_data_converts_email_thread_payload_to_tool_data() -> None:
    payload = {
        "email_thread_data": {
            "thread_id": "thread-1",
            "messages": [
                {
                    "id": "msg-1",
                    "from": "Alice <alice@example.com>",
                    "subject": "Project Update",
                    "time": "Tue, 16 Mar 2026 10:00:00 +0000",
                    "snippet": "sample snippet",
                    "body": "Primary update",
                    "content": {"text": "Primary update"},
                }
            ],
            "messages_count": 1,
        }
    }

    extracted = extract_tool_data(json.dumps(payload))

    assert "tool_data" in extracted
    assert extracted["tool_data"][0]["tool_name"] == "email_thread_data"
    assert extracted["tool_data"][0]["data"]["thread_id"] == "thread-1"
