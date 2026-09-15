"""Unit tests for profile card utilities."""

from datetime import UTC, datetime
import random
from unittest.mock import AsyncMock, patch

from bson import ObjectId
import pytest

from app.agents.prompts.onboarding_prompts import HOLO_CARD_PROMPT
from app.constants.profession_bios import PROFESSION_BIOS
from app.models.onboarding_models import HoloCardLLMOutput
from app.models.user_models import (
    BioStatus,
    OnboardingPreferences,
    OnboardingSubdocument,
    UserDocument,
)
from app.utils.profile_card import (
    HOUSES,
    assign_random_house,
    generate_holo_card_content,
    generate_profile_card_design,
    generate_random_color,
    get_user_metadata,
)

# The account_number is now derived from the ObjectId creation timestamp,
# not from a count_documents query. Pre-compute for the test ObjectId.
_TEST_OID = "507f1f77bcf86cd799439011"  # pragma: allowlist secret
_EXPECTED_ACCOUNT_NUMBER = int(ObjectId(_TEST_OID).generation_time.timestamp()) % 1_000_000


def _today() -> str:
    """Return today's date in the same format as the production fallback."""
    return datetime.now(UTC).strftime("%b %d, %Y")


# ---------------------------------------------------------------------------
# assign_random_house
# ---------------------------------------------------------------------------


class TestAssignRandomHouse:
    def test_returns_valid_house(self) -> None:
        random.seed(42)
        house = assign_random_house()
        assert house in HOUSES

    def test_deterministic_with_seed(self) -> None:
        random.seed(0)
        first = assign_random_house()
        random.seed(0)
        second = assign_random_house()
        assert first == second

    def test_all_houses_reachable(self) -> None:
        """Every house should be reachable given enough calls."""
        seen = set()
        for seed in range(200):
            random.seed(seed)
            seen.add(assign_random_house())
        assert seen == set(HOUSES)


# ---------------------------------------------------------------------------
# generate_random_color
# ---------------------------------------------------------------------------


class TestGenerateRandomColor:
    def test_returns_tuple_of_str_and_int(self) -> None:
        random.seed(42)
        color, opacity = generate_random_color()
        assert isinstance(color, str)
        assert isinstance(opacity, int)

    def test_opacity_in_valid_range(self) -> None:
        for seed in range(50):
            random.seed(seed)
            _, opacity = generate_random_color()
            assert 30 <= opacity <= 80

    def test_gradient_branch(self) -> None:
        """Force random.random() > 0.5 to produce a gradient."""
        # Find a seed that produces a gradient (random.random() > 0.5)
        for seed in range(200):
            random.seed(seed)
            if random.random() > 0.5:  # NOSONAR
                # Re-seed and call the function
                random.seed(seed)
                color, _ = generate_random_color()
                assert color.startswith("linear-gradient(")
                assert "deg," in color
                return
        pytest.fail("Could not find a seed that produces a gradient")

    def test_solid_color_branch(self) -> None:
        """Force random.random() <= 0.5 to produce a solid color."""
        for seed in range(200):
            random.seed(seed)
            if random.random() <= 0.5:  # NOSONAR
                random.seed(seed)
                color, _ = generate_random_color()
                assert color.startswith("rgba(")
                assert "linear-gradient" not in color
                return
        pytest.fail("Could not find a seed that produces a solid color")

    def test_deterministic_with_seed(self) -> None:
        random.seed(99)
        result1 = generate_random_color()
        random.seed(99)
        result2 = generate_random_color()
        assert result1 == result2

    def test_solid_color_format(self) -> None:
        """Solid color must be valid rgba(r, g, b, 1)."""
        for seed in range(200):
            random.seed(seed)
            if random.random() <= 0.5:  # NOSONAR
                random.seed(seed)
                color, _ = generate_random_color()
                assert color.startswith("rgba(")
                assert color.endswith(", 1)")
                return
        pytest.fail("Could not find a seed that produces a solid color")

    def test_gradient_contains_two_colors(self) -> None:
        """Gradient string should contain two rgba colors."""
        for seed in range(200):
            random.seed(seed)
            if random.random() > 0.5:  # NOSONAR
                random.seed(seed)
                color, _ = generate_random_color()
                assert color.count("rgba(") == 2
                return
        pytest.fail("Could not find a seed that produces a gradient")


# ---------------------------------------------------------------------------
# generate_profile_card_design
# ---------------------------------------------------------------------------


class TestGenerateProfileCardDesign:
    def test_house_is_valid(self) -> None:
        random.seed(42)
        design = generate_profile_card_design()
        assert design.house in HOUSES

    def test_overlay_opacity_in_range(self) -> None:
        random.seed(42)
        design = generate_profile_card_design()
        assert 30 <= design.overlay_opacity <= 80

    def test_overlay_color_is_string(self) -> None:
        random.seed(42)
        design = generate_profile_card_design()
        assert isinstance(design.overlay_color, str)

    def test_deterministic_with_seed(self) -> None:
        random.seed(7)
        d1 = generate_profile_card_design()
        random.seed(7)
        d2 = generate_profile_card_design()
        assert d1 == d2


# ---------------------------------------------------------------------------
# get_user_metadata
# ---------------------------------------------------------------------------


class TestGetUserMetadata:
    """account_number is now derived from the ObjectId creation timestamp
    (``int(oid.generation_time.timestamp()) % 1_000_000``) rather than a
    ``count_documents`` query.  member_since falls back to today's date (UTC)
    when the stored created_at is missing or not a datetime instance.
    """

    @pytest.mark.asyncio
    async def test_user_found_with_valid_created_at(self) -> None:
        dt = datetime(2025, 6, 15, 12, 0, 0)
        with patch(
            "app.utils.profile_card.user_repository.get",
            new_callable=AsyncMock,
            return_value=UserDocument(created_at=dt),
        ):
            result = await get_user_metadata(_TEST_OID)

        assert result.account_number == _EXPECTED_ACCOUNT_NUMBER
        assert result.member_since == "Jun 15, 2025"

    @pytest.mark.asyncio
    async def test_user_not_found_returns_defaults(self) -> None:
        with patch(
            "app.utils.profile_card.user_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await get_user_metadata(_TEST_OID)

        assert result.account_number == 1
        assert result.member_since == _today()

    @pytest.mark.asyncio
    async def test_created_at_is_none(self) -> None:
        with patch(
            "app.utils.profile_card.user_repository.get",
            new_callable=AsyncMock,
            return_value=UserDocument(created_at=None),
        ):
            result = await get_user_metadata(_TEST_OID)

        assert result.account_number == _EXPECTED_ACCOUNT_NUMBER
        assert result.member_since == _today()

    @pytest.mark.asyncio
    async def test_created_at_is_not_datetime(self) -> None:
        # model_construct skips validation, which is the only way a non-datetime
        # created_at still reaches the guard now the parameter is a UserDocument.
        result = await get_user_metadata(
            _TEST_OID, user=UserDocument.model_construct(created_at="2025-01-01")
        )

        assert result.account_number == _EXPECTED_ACCOUNT_NUMBER
        assert result.member_since == _today()

    @pytest.mark.asyncio
    async def test_exception_returns_defaults(self) -> None:
        with patch(
            "app.utils.profile_card.user_repository.get",
            new_callable=AsyncMock,
            side_effect=Exception("DB connection lost"),
        ):
            result = await get_user_metadata(_TEST_OID)

        assert result.account_number == 1
        assert result.member_since == _today()

    @pytest.mark.asyncio
    async def test_account_number_derived_from_objectid(self) -> None:
        """account_number is the ObjectId timestamp modulo 1 000 000."""
        dt = datetime(2025, 3, 10, 8, 30, 0)
        result = await get_user_metadata(_TEST_OID, user=UserDocument(created_at=dt))

        assert result.account_number == _EXPECTED_ACCOUNT_NUMBER
        assert result.member_since == "Mar 10, 2025"

    @pytest.mark.asyncio
    async def test_user_has_no_created_at_key(self) -> None:
        """User document exists but has no created_at field at all."""
        with patch(
            "app.utils.profile_card.user_repository.get",
            new_callable=AsyncMock,
            return_value=UserDocument(name="Test"),
        ):
            result = await get_user_metadata(_TEST_OID)

        assert result.account_number == _EXPECTED_ACCOUNT_NUMBER
        assert result.member_since == _today()


# ---------------------------------------------------------------------------
# generate_holo_card_content — profession resolution
# ---------------------------------------------------------------------------


def _bios_for(profession: str, name: str) -> list[str]:
    """Every bio the production pool can hand back for a profession."""
    return [bio.format(name=name) for bio in PROFESSION_BIOS[profession]]


class TestGenerateHoloCardContentProfession:
    """The profession drives both the fallback phrase and the bio pool, and it is
    read off a typed onboarding subdocument that is absent on most rows."""

    @pytest.mark.asyncio
    async def test_profession_comes_from_the_onboarding_preferences(self) -> None:
        user = UserDocument(
            name="Ada",
            onboarding=OnboardingSubdocument(
                preferences=OnboardingPreferences(profession="developer")
            ),
        )

        phrase, bio, status = await generate_holo_card_content("uid", "", user=user)

        assert phrase == "Curious Developer"
        assert bio in _bios_for("developer", "Ada")
        assert status == BioStatus.NO_GMAIL

    @pytest.mark.asyncio
    async def test_a_user_without_onboarding_falls_back_to_other(self) -> None:
        user = UserDocument(name="Ada", onboarding=None)

        phrase, bio, _ = await generate_holo_card_content("uid", "", user=user)

        assert phrase == "Curious Adventurer"
        assert bio in _bios_for("other", "Ada")

    @pytest.mark.asyncio
    async def test_onboarding_without_preferences_falls_back_to_other(self) -> None:
        user = UserDocument(name="Ada", onboarding=OnboardingSubdocument(preferences=None))

        phrase, bio, _ = await generate_holo_card_content("uid", "", user=user)

        assert phrase == "Curious Adventurer"
        assert bio in _bios_for("other", "Ada")

    @pytest.mark.asyncio
    async def test_preferences_without_a_profession_falls_back_to_other(self) -> None:
        user = UserDocument(
            name="Ada",
            onboarding=OnboardingSubdocument(preferences=OnboardingPreferences(profession=None)),
        )

        phrase, bio, _ = await generate_holo_card_content("uid", "", user=user)

        assert phrase == "Curious Adventurer"
        assert bio in _bios_for("other", "Ada")

    @pytest.mark.asyncio
    async def test_an_unknown_user_is_named_user_and_has_no_profession(self) -> None:
        with patch(
            "app.utils.profile_card.user_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            phrase, bio, _ = await generate_holo_card_content("uid", "")

        assert phrase == "Curious Adventurer"
        assert bio in _bios_for("other", "User")

    @pytest.mark.asyncio
    async def test_the_profession_reaches_the_llm_prompt(self) -> None:
        """With a context summary the profession is interpolated into the prompt."""
        user = UserDocument(
            name="Ada",
            onboarding=OnboardingSubdocument(
                preferences=OnboardingPreferences(profession="designer")
            ),
        )
        llm_output = AsyncMock(
            return_value=HoloCardLLMOutput(
                personality_phrase='"Pixel Wrangler"', user_bio="  Ada designs things.  "
            )
        )

        with patch("app.utils.profile_card.ainvoke_structured", llm_output):
            phrase, bio, status = await generate_holo_card_content(
                "uid", "inbox summary", user=user
            )

        prompt = llm_output.await_args.args[1]
        assert "designer" in prompt
        assert phrase == "Pixel Wrangler"
        assert bio == "Ada designs things."
        assert status == BioStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_a_missing_profession_reaches_the_llm_prompt_empty(self) -> None:
        """No profession must render as nothing in the prompt — any placeholder the
        fallback invented would be read by the LLM as the user's actual job."""
        user = UserDocument(name="Ada", onboarding=None)
        llm_output = AsyncMock(
            return_value=HoloCardLLMOutput(personality_phrase="Quiet Builder", user_bio="Ada.")
        )

        with patch("app.utils.profile_card.ainvoke_structured", llm_output):
            await generate_holo_card_content("uid", "inbox summary", user=user)

        assert llm_output.await_args.args[1] == HOLO_CARD_PROMPT.format(
            name="Ada", profession="", context_summary="inbox summary"
        )
