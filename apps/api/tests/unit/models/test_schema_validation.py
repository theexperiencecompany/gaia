"""Unit tests for Pydantic model validation across chat, message, and user models."""

from pydantic import ValidationError
import pytest

from app.models.user_models import (
    PROFESSION_MAX_LENGTH,
    ROLE_NEEDS,
    OnboardingNeed,
    OnboardingPreferences,
    OnboardingRequest,
    role_of_need,
)


class TestOnboardingRequest:
    def test_more_than_the_pick_cap_is_rejected(self) -> None:
        """Q2 is "pick up to three": a fourth need is a client that skipped the cap."""
        with pytest.raises(ValidationError):
            OnboardingRequest(
                profession="Founder", needs=["inbox", "calendar", "mornings", "reminders"]
            )
        # The stored shape is read back for users who picked up to seven under
        # the old Q2; it keeps their first picks rather than refusing to load.
        assert [
            n.value
            for n in OnboardingPreferences(
                needs=["inbox", "calendar", "mornings", "reminders"]
            ).needs
        ] == ["inbox", "calendar", "mornings"]

    def test_a_role_need_is_rejected_for_another_role(self) -> None:
        """The student pair is only ever shown to students; a founder sending it is a replayed or hand-built request."""
        with pytest.raises(ValidationError, match="only offered to student"):
            OnboardingRequest(profession="founder", needs=["student_exams"])
        with pytest.raises(ValidationError, match="only offered to student"):
            OnboardingRequest(profession="Plumber", needs=["student_exams"])

    def test_every_role_pair_belongs_to_exactly_one_role(self) -> None:
        seen: list[OnboardingNeed] = []
        for role, pair in ROLE_NEEDS.items():
            assert len(pair) == 2
            for need in pair:
                assert role_of_need(need) == role
                seen.append(need)
        assert len(seen) == len(set(seen))
        shared = [n for n in OnboardingNeed if role_of_need(n) is None]
        assert len(shared) == 6

    def test_preferences_and_request_share_the_profession_rule(self):
        """The two models once disagreed and the wizard hung on the stricter one."""
        typed = "I'm a founder, designer & dad"
        assert OnboardingPreferences(profession=typed).profession == typed
        with pytest.raises(ValidationError):
            OnboardingPreferences(profession="Eng\nineer")

    def test_typed_need_alone_answers_q2(self):
        r = OnboardingRequest(profession="Founder", other_need=" chasing invoices ")
        assert r.needs == []
        assert r.other_need == "chasing invoices"

    @pytest.mark.parametrize(
        ("profession", "message"),
        [
            ("   ", r"Value error, Profession cannot be empty \["),
            ("Eng\nineer", r"Value error, Profession must be one line of words \["),
            ("12345", r"Value error, Profession must be one line of words \["),
        ],
    )
    def test_profession_rejections_say_why(self, profession: str, message: str):
        """The message is what the wizard surfaces; a vague one is a support ticket."""
        with pytest.raises(ValidationError, match=message):
            OnboardingRequest(profession=profession, needs=["inbox"])
        with pytest.raises(ValidationError, match=message):
            OnboardingPreferences(profession=profession)

    def test_too_long_profession_says_why_on_the_preferences_model(self):
        # The request field carries max_length, so pydantic answers first there;
        # the shared rule is what the preferences PATCH reports.
        with pytest.raises(
            ValidationError,
            match=rf"Value error, Profession must be {PROFESSION_MAX_LENGTH} characters or less \[",
        ):
            OnboardingPreferences(profession="E" * (PROFESSION_MAX_LENGTH + 1))

    def test_no_q2_answer_says_why(self):
        with pytest.raises(
            ValidationError,
            match=r"Value error, Pick at least one need or say it in your own words \[",
        ):
            OnboardingRequest(profession="Founder", needs=[])

    # --- needs (Q2) ---

    def test_unknown_need_rejected(self):
        with pytest.raises(ValidationError):
            OnboardingRequest(profession="Engineer", needs=["world_peace"])

    def test_a_name_is_not_part_of_the_contract(self):
        """The name is derived from the email server-side; an extra key is ignored."""
        r = OnboardingRequest(profession="Engineer", needs=["inbox"], name="Mallory")
        assert not hasattr(r, "name")


class TestOnboardingPreferences:
    def test_empty_string_normalized_to_none(self):
        p = OnboardingPreferences(profession="", response_style="")
        assert p.profession is None
        assert p.response_style is None

    def test_needs_drop_a_key_the_enum_no_longer_has(self):
        """Stored documents from before the Q2 rewrite carry retired values that the stored model must still load."""
        assert [n.value for n in OnboardingPreferences(needs=["inbox", "telepathy"]).needs] == [
            "inbox"
        ]
