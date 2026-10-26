"""Presence rules: absolute UTC rendering and which runs are due a note."""

from collections.abc import Iterator
from datetime import UTC, datetime
import time

import pytest

from app.models.presence_models import PresenceSnapshot
from app.utils.presence_utils import format_utc, note_is_due
from shared.py.analytics.catalog.attribution import EntrySurface

pytestmark = pytest.mark.unit

EPOCH = int(datetime(2026, 10, 24, 16, 55, tzinfo=UTC).timestamp())
SAME_SURFACE: PresenceSnapshot = {"captured_at": EPOCH, "last_seen": {"telegram": EPOCH - 60}}


@pytest.fixture
def kolkata_clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


class TestFormatUtc:
    def test_renders_utc_whatever_the_host_timezone(self, kolkata_clock: None) -> None:
        assert format_utc(EPOCH) == "2026-10-24 16:55 UTC"


class TestNoteIsDue:
    def test_a_background_run_is_due_a_note_even_on_the_users_last_surface(self) -> None:
        assert (
            note_is_due(
                SAME_SURFACE, "telegram", "background", False, entry_surface=EntrySurface.WEB
            )
            is True
        )

    def test_a_live_turn_on_the_users_last_surface_is_not(self) -> None:
        assert (
            note_is_due(
                SAME_SURFACE, "telegram", "interactive", False, entry_surface=EntrySurface.WEB
            )
            is False
        )

    @pytest.mark.regression
    def test_a_voice_turn_is_never_due_a_note_even_opening_a_thread(self) -> None:
        """A call arrives as a web turn and was told the user had switched to Web every time."""
        assert (
            note_is_due(SAME_SURFACE, "web", "interactive", True, entry_surface=EntrySurface.VOICE)
            is False
        )

    def test_a_background_run_started_from_a_call_is_still_due_a_note(self) -> None:
        assert (
            note_is_due(SAME_SURFACE, None, "background", False, entry_surface=EntrySurface.VOICE)
            is True
        )
