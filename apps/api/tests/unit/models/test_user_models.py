"""Unit tests for user Pydantic models."""

from pydantic import ValidationError
import pytest

from app.models.user_models import OnboardingRequest


# ---------------------------------------------------------------------------
# OnboardingRequest.validate_timezone
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestOnboardingRequestTimezone:
    """The ``timezone`` field validator now delegates to the canonical
    ``is_valid_timezone`` — it accepts IANA names, ±HH:MM offsets and UTC,
    rejects junk, and passes None/empty through."""

    def _build(self, timezone) -> OnboardingRequest:
        return OnboardingRequest(
            name="Aryan",
            profession="Engineer",
            timezone=timezone,
        )

    @pytest.mark.parametrize(
        "tz",
        ["Asia/Kolkata", "America/New_York", "+05:30", "-08:00", "UTC", "utc"],
    )
    def test_valid_timezone_preserved(self, tz):
        m = self._build(tz)
        assert m.timezone == tz

    def test_valid_timezone_is_stripped(self):
        m = self._build("  Asia/Kolkata  ")
        assert m.timezone == "Asia/Kolkata"

    @pytest.mark.parametrize(
        "tz",
        ["Not/AZone", "Mars/Phobos", "+5:30"],
    )
    def test_invalid_timezone_raises(self, tz):
        with pytest.raises(ValidationError):
            self._build(tz)

    def test_none_timezone_allowed(self):
        m = self._build(None)
        assert m.timezone is None

    def test_empty_timezone_allowed(self):
        m = self._build("")
        assert m.timezone == ""
