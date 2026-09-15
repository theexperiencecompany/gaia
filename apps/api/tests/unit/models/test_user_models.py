"""Unit tests for user Pydantic models."""

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from app.models.user_models import (
    BioStatus,
    OnboardingNeed,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
    UserDocument,
)

# ---------------------------------------------------------------------------
# OnboardingRequest.validate_timezone
# ---------------------------------------------------------------------------


class TestOnboardingRequestTimezone:
    """The ``timezone`` field validator now delegates to the canonical
    ``is_valid_timezone`` — it accepts IANA names, ±HH:MM offsets and UTC,
    rejects junk, and passes None/empty through."""

    def _build(self, timezone) -> OnboardingRequest:
        return OnboardingRequest(
            profession="Engineer",
            needs=["inbox"],
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


@pytest.mark.unit
class TestStoredPreferencesFromBeforeTheQ2Rewrite:
    """Users who onboarded before the pain-based Q2 hold need values that no
    longer exist ("todos", "briefings", "reach") and up to seven picks. Their
    document is read back on every /user/me, at seeding, in the activation
    context and by account_fs, so it must always load; strictness belongs to
    the request model, not the stored one."""

    def test_unknown_need_values_are_dropped_in_order(self) -> None:
        prefs = OnboardingPreferences.model_validate(
            {"profession": "founder", "needs": ["todos", "inbox", "briefings", "calendar"]}
        )

        assert prefs.needs == [OnboardingNeed.INBOX, OnboardingNeed.CALENDAR]

    def test_more_picks_than_the_cap_keep_the_first_ones(self) -> None:
        prefs = OnboardingPreferences.model_validate(
            {"profession": "founder", "needs": ["inbox", "calendar", "reminders", "tools"]}
        )

        assert prefs.needs == [
            OnboardingNeed.INBOX,
            OnboardingNeed.CALENDAR,
            OnboardingNeed.REMINDERS,
        ]

    def test_only_unknown_values_leaves_no_picks(self) -> None:
        prefs = OnboardingPreferences.model_validate({"profession": "founder", "needs": ["memory"]})

        assert prefs.needs == []

    def test_the_request_model_still_rejects_an_unknown_need(self) -> None:
        with pytest.raises(ValidationError):
            OnboardingRequest(profession="founder", needs=["todos"])


# ---------------------------------------------------------------------------
# OnboardingSubdocument
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOnboardingSubdocument:
    """``users.onboarding`` typed but still open: declared keys are coerced to
    real types, and keys written by onboarding flows that no longer exist have
    to survive a load/dump round trip untouched."""

    def test_unknown_historical_keys_round_trip(self) -> None:
        doc = UserDocument.model_validate(
            {
                "_id": "user-1",
                "onboarding": {
                    "completed": True,
                    "retired_wizard_step": 4,
                    "clarify_questions": [{"id": "q1"}],
                },
            }
        )

        assert doc.onboarding is not None
        dumped = doc.onboarding.model_dump()
        assert dumped["retired_wizard_step"] == 4
        assert dumped["clarify_questions"] == [{"id": "q1"}]

    def test_declared_keys_are_coerced_to_their_real_types(self) -> None:
        doc = UserDocument.model_validate(
            {
                "_id": "user-1",
                "onboarding": {
                    "phase": "getting_started",
                    "bio_status": "processing",
                    "completed_at": "2026-01-02T03:04:05Z",
                    "gmail_personalization_at": "2026-01-02T03:04:06Z",
                    "preferences": {"profession": "Engineer", "needs": ["inbox"]},
                },
            }
        )

        onboarding = doc.onboarding
        assert onboarding is not None
        assert onboarding.phase is OnboardingPhase.GETTING_STARTED
        assert onboarding.bio_status is BioStatus.PROCESSING
        assert onboarding.completed_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        assert onboarding.gmail_personalization_at == datetime(2026, 1, 2, 3, 4, 6, tzinfo=UTC)
        assert onboarding.preferences is not None
        assert onboarding.preferences.needs == [OnboardingNeed.INBOX]

    def test_a_missing_subdocument_stays_none(self) -> None:
        assert UserDocument.model_validate({"_id": "user-1"}).onboarding is None


class TestOnboardingSubdocumentToleratesOldRows:
    def test_an_unknown_phase_or_bio_status_reads_as_unset(self) -> None:
        doc = UserDocument.model_validate(
            {
                "id": "507f1f77bcf86cd799439011",
                "email": "old@example.com",
                "onboarding": {"phase": "retired_phase", "bio_status": "weird"},
            }
        )
        assert doc.onboarding is not None
        assert doc.onboarding.phase is None
        assert doc.onboarding.bio_status is None

    def test_a_value_from_the_other_enum_reads_as_unset_instead_of_failing(self) -> None:
        """Each field is guarded against its OWN enum, not the union of both.

        ``"pending"`` is a real ``BioStatus`` and no ``OnboardingPhase`` at all
        (and ``"initial"`` the reverse). Checked against one merged set of every
        known value they both pass the guard untouched and then fail Pydantic's
        coercion for the field's real type — a failed user read, which is a
        silent permanent logout, from a row this guard promises to tolerate.
        """
        doc = UserDocument.model_validate(
            {
                "id": "507f1f77bcf86cd799439011",
                "email": "old@example.com",
                "onboarding": {"phase": "pending", "bio_status": "initial"},
            }
        )
        assert doc.onboarding is not None
        assert doc.onboarding.phase is None
        assert doc.onboarding.bio_status is None

    def test_the_value_the_two_enums_share_still_coerces_on_both_fields(self) -> None:
        """``"completed"`` is a genuine member of each — splitting must not drop it."""
        doc = UserDocument.model_validate(
            {
                "id": "507f1f77bcf86cd799439011",
                "email": "old@example.com",
                "onboarding": {"phase": "completed", "bio_status": "completed"},
            }
        )
        assert doc.onboarding is not None
        assert doc.onboarding.phase is OnboardingPhase.COMPLETED
        assert doc.onboarding.bio_status is BioStatus.COMPLETED

    def test_a_non_string_phase_reads_as_unset_instead_of_failing(self) -> None:
        doc = UserDocument.model_validate(
            {
                "id": "507f1f77bcf86cd799439011",
                "email": "old@example.com",
                "onboarding": {"phase": {"step": 3}, "bio_status": 7},
            }
        )
        assert doc.onboarding is not None
        assert doc.onboarding.phase is None
        assert doc.onboarding.bio_status is None

    def test_a_known_phase_still_coerces_to_the_enum(self) -> None:
        doc = UserDocument.model_validate(
            {
                "id": "507f1f77bcf86cd799439011",
                "email": "new@example.com",
                "onboarding": {"phase": OnboardingPhase.COMPLETED.value},
            }
        )
        assert doc.onboarding is not None
        assert doc.onboarding.phase is OnboardingPhase.COMPLETED

    def test_a_non_mapping_preferences_blob_reads_as_unset(self) -> None:
        """``onboarding.preferences`` is an untyped blob in stored rows. Typing
        it put every authenticated read behind its validation, so a string or a
        list there has to read as "no preferences" instead of failing the load."""
        for blob in ("brief", ["brief"], 7):
            doc = UserDocument.model_validate(
                {
                    "id": "507f1f77bcf86cd799439011",
                    "email": "old@example.com",
                    "onboarding": {"completed": True, "preferences": blob},
                }
            )
            assert doc.onboarding is not None
            assert doc.onboarding.preferences is None
            assert doc.onboarding.completed is True
