"""Unit tests for profile card utilities."""

from datetime import UTC, datetime
import random
from unittest.mock import AsyncMock, patch

from bson import ObjectId
import pytest

from app.models.user_models import UserDocument
from app.utils.profile_card import (
    HOUSES,
    assign_random_house,
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
