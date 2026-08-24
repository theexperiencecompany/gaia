"""``_parse_complete_message`` — pulling ``(complete_message, cancelled)`` out of a
``nostream: {...}`` marker chunk.
"""

import json

import pytest

from app.services.chat.stream import _parse_complete_message

pytestmark = pytest.mark.unit


class TestParseCompleteMessage:
    def test_extracts_complete_message_verbatim(self) -> None:
        chunk = 'nostream: {"complete_message": "the full reply"}'

        message, cancelled = _parse_complete_message(chunk)

        assert message == "the full reply"
        assert cancelled is False

    def test_missing_complete_message_key_yields_empty_string(self) -> None:
        """No key at all — must come back as ``""``, never the literal string
        ``"None"`` and never a sentinel default."""
        chunk = json.dumps({"cancelled": False})

        message, _ = _parse_complete_message(f"nostream: {chunk}")

        assert message == ""

    def test_cancelled_true_is_reported(self) -> None:
        chunk = 'nostream: {"complete_message": "stopped mid", "cancelled": true}'

        _, cancelled = _parse_complete_message(chunk)

        assert cancelled is True

    def test_cancelled_absent_defaults_to_false(self) -> None:
        chunk = 'nostream: {"complete_message": "all good"}'

        _, cancelled = _parse_complete_message(chunk)

        assert cancelled is False

    def test_a_truncated_trailing_sentinel_is_stripped(self) -> None:
        """A run cut short mid-sentinel must never reach the persisted turn as
        literal text — see ``strip_partial_message_break``."""
        chunk = json.dumps({"complete_message": "numbers<NEW_MESSAGE_B"})

        message, _ = _parse_complete_message(f"nostream: {chunk}")

        assert message == "numbers"
