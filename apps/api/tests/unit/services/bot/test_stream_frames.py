"""Unit tests for the bot SSE frame builders.

The point of this module is byte identity: every builder is pinned against the
literal it replaced in ``app/api/v1/endpoints/bot.py``, character for
character. A bot adapter parses these bytes, so a stray space or a reordered
key is a production break that no route test would notice.
"""

import json

from app.services.bot.stream_frames import (
    approval_frame,
    comment_keepalive_frame,
    done_frame,
    error_frame,
    keepalive_frame,
    message_boundary_frame,
    notice_frame,
    session_token_frame,
    sse_frame,
    stream_error_frame,
    text_frame,
)


class TestByteIdentityWithTheOldLiterals:
    """Each builder renders exactly what the hand-built frame used to render."""

    def test_session_token_frame(self):
        session_token = "tok-123"
        assert session_token_frame(session_token) == (
            f"data: {json.dumps({'session_token': session_token})}\n\n"
        )

    def test_comment_keepalive_frame(self):
        assert comment_keepalive_frame() == ": keepalive\n\n"

    def test_keepalive_frame(self):
        assert keepalive_frame() == f"data: {json.dumps({'keepalive': True})}\n\n"

    def test_text_frame(self):
        data = {"response": "hello there"}
        assert text_frame(data["response"]) == f"data: {json.dumps({'text': data['response']})}\n\n"

    def test_notice_frame_for_the_paywall(self):
        notice_text = "GAIA is paid only. Subscribe to GAIA Pro to keep chatting: https://x/y"
        assert notice_frame(notice_text) == (
            f"data: {json.dumps({'notice': {'text': notice_text}})}\n\n"
        )

    def test_notice_frame_for_a_rate_limit_card(self):
        rate_limit_notice = "⏳ You've reached your chat messages limit. Please try again later."
        payload = json.dumps({"notice": {"text": rate_limit_notice}})
        assert notice_frame(rate_limit_notice) == f"data: {payload}\n\n"

    def test_approval_frame(self):
        approval_payload = {"tool": "send_email", "args": {"to": "a@b.c"}}
        assert approval_frame(approval_payload) == (
            f"data: {json.dumps({'approval': approval_payload})}\n\n"
        )

    def test_message_boundary_frame(self):
        data = {"message_boundary": {"discarded": True}}
        payload = json.dumps({"message_boundary": data["message_boundary"]})
        assert message_boundary_frame(data["message_boundary"]) == f"data: {payload}\n\n"

    def test_error_frame_for_a_refusal_code(self):
        error_code = "not_authenticated"
        assert error_frame(error_code) == f"data: {json.dumps({'error': error_code})}\n\n"

    def test_error_frame_for_a_forwarded_upstream_error(self):
        data = {"error": "boom"}
        assert error_frame(data["error"]) == f"data: {json.dumps({'error': data['error']})}\n\n"

    def test_done_frame_with_a_conversation_id(self):
        conversation_id = "conv-1"
        done = json.dumps({"done": True, "conversation_id": conversation_id})
        assert done_frame(conversation_id) == f"data: {done}\n\n"

    def test_done_frame_for_the_notice_only_stream(self):
        assert done_frame("") == f"data: {json.dumps({'done': True, 'conversation_id': ''})}\n\n"

    def test_stream_error_frame(self):
        assert stream_error_frame() == (
            f"data: {json.dumps({'error': 'Stream error occurred'})}\n\n"
        )


class TestSseFrame:
    """The shared serializer the named builders are all thin wrappers over."""

    def test_it_wraps_json_in_the_sse_data_envelope(self):
        assert sse_frame({"a": 1, "b": "two"}) == 'data: {"a": 1, "b": "two"}\n\n'

    def test_key_order_is_insertion_order_not_sorted(self):
        # `done` before `conversation_id` is the shape bots have always seen.
        assert sse_frame({"done": True, "conversation_id": "c"}) == (
            'data: {"done": true, "conversation_id": "c"}\n\n'
        )

    def test_non_ascii_is_escaped_exactly_as_json_dumps_does(self):
        # json.dumps defaults to ensure_ascii=True; the hourglass in the rate
        # limit notice therefore travels as \u231b, and must keep doing so.
        assert sse_frame({"notice": "⏳"}) == 'data: {"notice": "\\u23f3"}\n\n'
