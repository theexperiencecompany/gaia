"""Unit tests for profile card utilities."""

from datetime import UTC, datetime
import random
from typing import Any
from unittest.mock import AsyncMock, patch

from bson import ObjectId
import pytest

from app.utils.profile_card import (
    HOUSES,
    assign_random_house,
    generate_profile_card_design,
    generate_random_color,
    get_user_metadata,
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_user(
    name: str = "Test User",
    profession: str = "developer",
    created_at: Any = None,
    email_memory_processed: bool = False,
) -> dict[str, Any]:
    """Build a fake MongoDB user document."""
    user: dict[str, Any] = {
        "name": name,
        "onboarding": {"preferences": {"profession": profession}},
        "email_memory_processed": email_memory_processed,
    }
    if created_at is not None:
        user["created_at"] = created_at
    return user


# ---------------------------------------------------------------------------
# assign_random_house
# ---------------------------------------------------------------------------


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestGenerateProfileCardDesign:
    def test_returns_expected_keys(self) -> None:
        random.seed(42)
        design = generate_profile_card_design()
        assert "house" in design
        assert "overlay_color" in design
        assert "overlay_opacity" in design

    def test_house_is_valid(self) -> None:
        random.seed(42)
        design = generate_profile_card_design()
        assert design["house"] in HOUSES

    def test_overlay_opacity_in_range(self) -> None:
        random.seed(42)
        design = generate_profile_card_design()
        assert 30 <= design["overlay_opacity"] <= 80

    def test_overlay_color_is_string(self) -> None:
        random.seed(42)
        design = generate_profile_card_design()
        assert isinstance(design["overlay_color"], str)

    def test_deterministic_with_seed(self) -> None:
        random.seed(7)
        d1 = generate_profile_card_design()
        random.seed(7)
        d2 = generate_profile_card_design()
        assert d1 == d2


# ---------------------------------------------------------------------------
# get_user_metadata
# ---------------------------------------------------------------------------

# Stable account number derived from the ObjectId's creation timestamp:
# int(ObjectId(USER_ID).generation_time.timestamp()) % 1_000_000
USER_ID = "507f1f77bcf86cd799439011"  # pragma: allowlist secret
EXPECTED_ACCOUNT_NUMBER = int(ObjectId(USER_ID).generation_time.timestamp()) % 1_000_000


def _today_member_since() -> str:
    """The format prod uses for the fallback member_since (current UTC date)."""
    return datetime.now(UTC).strftime("%b %d, %Y")


@pytest.mark.unit
class TestGetUserMetadata:
    @pytest.mark.asyncio
    async def test_user_found_with_valid_created_at(self) -> None:
        dt = datetime(2025, 6, 15, 12, 0, 0)
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value={"created_at": dt})

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(USER_ID)

        # Account number is derived from the ObjectId, not a DB count
        assert result["account_number"] == EXPECTED_ACCOUNT_NUMBER
        # member_since reflects the document's created_at
        assert result["member_since"] == "Jun 15, 2025"

    @pytest.mark.asyncio
    async def test_user_not_found_returns_defaults(self) -> None:
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(USER_ID)

        # When the user doc is missing, prod returns account_number=1 and the
        # current date as member_since (no hardcoded calendar date).
        assert result["account_number"] == 1
        assert result["member_since"] == _today_member_since()

    @pytest.mark.asyncio
    async def test_created_at_is_none(self) -> None:
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value={"created_at": None})

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(USER_ID)

        # Account number still derived from the ObjectId even without created_at
        assert result["account_number"] == EXPECTED_ACCOUNT_NUMBER
        # No usable created_at => member_since falls back to the current date
        assert result["member_since"] == _today_member_since()

    @pytest.mark.asyncio
    async def test_created_at_is_not_datetime(self) -> None:
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value={"created_at": "2025-01-01"})

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(USER_ID)

        assert result["account_number"] == EXPECTED_ACCOUNT_NUMBER
        # A non-datetime created_at is ignored => fallback to current date
        assert result["member_since"] == _today_member_since()

    @pytest.mark.asyncio
    async def test_exception_returns_defaults(self) -> None:
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(side_effect=Exception("DB connection lost"))

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(USER_ID)

        assert result["account_number"] == 1
        assert result["member_since"] == _today_member_since()

    @pytest.mark.asyncio
    async def test_member_since_reflects_created_at(self) -> None:
        dt = datetime(2025, 3, 10, 8, 30, 0)
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value={"created_at": dt})

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(USER_ID)

        assert result["account_number"] == EXPECTED_ACCOUNT_NUMBER
        assert result["member_since"] == "Mar 10, 2025"

    @pytest.mark.asyncio
    async def test_user_has_no_created_at_key(self) -> None:
        """User document exists but has no created_at field at all."""
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value={"name": "Test"})

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(USER_ID)

        assert result["account_number"] == EXPECTED_ACCOUNT_NUMBER
        assert result["member_since"] == _today_member_since()

    @pytest.mark.asyncio
    async def test_user_passed_in_skips_db_lookup(self) -> None:
        """When a user doc is passed directly, find_one is not called."""
        dt = datetime(2024, 12, 1, 0, 0, 0)
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(USER_ID, user={"created_at": dt})

        mock_collection.find_one.assert_not_awaited()
        assert result["account_number"] == EXPECTED_ACCOUNT_NUMBER
        assert result["member_since"] == "Dec 01, 2024"
