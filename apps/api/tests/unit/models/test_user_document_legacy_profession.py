"""A stored profession today's input rules refuse must not fail the user read.

``OnboardingPreferences`` is both the type of ``users.onboarding.preferences``
and the request body of ``PATCH /preferences``, so tightening
``clean_profession`` re-judges rows the older validator already accepted. The
read path has no lenient guard for that — ``base.py`` only skips malformed
documents on *list* reads — so a refused value raises inside the single-document
read that ``authenticate_workos_session`` performs, and that broad handler turns
it into an empty ``user_info``. The account is then 401'd on every request while
WorkOS keeps reporting a valid session: a silent, permanent logout with no
self-service fix.

The sibling guards (``unknown_enum_values_read_as_unset``,
``a_non_mapping_preferences_blob_reads_as_unset``) exist for exactly this shape.
"""

import pytest

from app.models.user_models import OnboardingPreferences, OnboardingRequest, UserDocument

pytestmark = pytest.mark.unit

# Values the previous PATCH validator accepted — it enforced only strip and
# length — and that clean_profession now refuses: nothing alphabetic, or an
# embedded newline/tab.
LEGACY_PROFESSIONS = ("12345", "---", "3.14", "Founder\nCEO", "Data\tScientist", "🚀")


def _user_row(profession: object) -> dict[str, object]:
    return {
        "_id": "507f1f77bcf86cd799439011",
        "email": "someone@example.com",
        "onboarding": {"preferences": {"profession": profession, "response_style": "warm"}},
    }


class TestLegacyProfessionDoesNotBreakTheRead:
    @pytest.mark.parametrize("profession", LEGACY_PROFESSIONS)
    def test_the_user_document_still_reads(self, profession: str) -> None:
        """The read is what auth depends on; it must survive the stored value."""
        document = UserDocument.model_validate(_user_row(profession))

        assert document.email == "someone@example.com"

    @pytest.mark.parametrize("profession", LEGACY_PROFESSIONS)
    def test_the_refused_value_reads_as_unset(self, profession: str) -> None:
        """Unset, not passed through: nothing downstream should speak it back."""
        document = UserDocument.model_validate(_user_row(profession))

        assert document.onboarding is not None
        assert document.onboarding.preferences is not None
        assert document.onboarding.preferences.profession is None

    @pytest.mark.parametrize("profession", LEGACY_PROFESSIONS)
    def test_the_write_path_still_refuses_it(self, profession: str) -> None:
        """Leniency is for stored rows only — nobody may type one of these in."""
        with pytest.raises(ValueError):
            OnboardingRequest(profession=profession, needs=[])

        with pytest.raises(ValueError):
            OnboardingPreferences(profession=profession)

    def test_a_valid_stored_profession_is_untouched(self) -> None:
        """The guard must not eat good data on its way past."""
        document = UserDocument.model_validate(_user_row("Software Engineer"))

        assert document.onboarding is not None
        assert document.onboarding.preferences is not None
        assert document.onboarding.preferences.profession == "Software Engineer"

    @pytest.mark.parametrize("stored", ["", 12345, 3.14, [], {}])
    def test_a_profession_that_is_not_usable_text_reads_as_unset(self, stored: object) -> None:
        """Empty and non-string stored values both read as unset.

        Neither reaches ``clean_profession``: a number has no ``.strip()``, and
        "" is read as unset by the field validator regardless of this guard, so
        the guard hands both straight through. This pins that they end up unset
        rather than raising — the mutation gate found the branch untested when it
        was written as a special case, which is what showed the case was dead.
        """
        document = UserDocument.model_validate(_user_row(stored))

        assert document.onboarding is not None
        assert document.onboarding.preferences is not None
        assert document.onboarding.preferences.profession is None

    def test_the_rest_of_preferences_survives_the_drop(self) -> None:
        """Dropping the profession must not drop its siblings with it."""
        document = UserDocument.model_validate(_user_row("12345"))

        assert document.onboarding is not None
        assert document.onboarding.preferences is not None
        assert document.onboarding.preferences.response_style == "warm"
