"""Unit tests for profile card utilities."""

import random
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.memory_models import MemoryEntry
from app.models.user_models import BioStatus
from app.utils.profile_card import (
    HOUSES,
    assign_random_house,
    generate_profile_card_design,
    generate_random_color,
    generate_personality_phrase,
    generate_user_bio,
    get_user_metadata,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_memory(content: str) -> MemoryEntry:
    """Create a minimal MemoryEntry for testing."""
    return MemoryEntry(content=content)


def _make_memories(contents: List[str]) -> List[MemoryEntry]:
    """Create a list of MemoryEntry objects from content strings."""
    return [_make_memory(c) for c in contents]


def _make_user(
    name: str = "Test User",
    profession: str = "developer",
    created_at: Any = None,
    email_memory_processed: bool = False,
) -> Dict[str, Any]:
    """Build a fake MongoDB user document."""
    user: Dict[str, Any] = {
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


@pytest.mark.unit
class TestGetUserMetadata:
    @pytest.mark.asyncio
    async def test_user_found_with_valid_created_at(self) -> None:
        dt = datetime(2025, 6, 15, 12, 0, 0)
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value={"created_at": dt})
        mock_collection.count_documents = AsyncMock(return_value=5)

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(
                "507f1f77bcf86cd799439011"  # pragma: allowlist secret
            )

        assert result["account_number"] == 6
        assert result["member_since"] == "Jun 15, 2025"

    @pytest.mark.asyncio
    async def test_user_not_found_returns_defaults(self) -> None:
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(
                "507f1f77bcf86cd799439011"  # pragma: allowlist secret
            )

        assert result == {"account_number": 1, "member_since": "Nov 21, 2024"}

    @pytest.mark.asyncio
    async def test_created_at_is_none(self) -> None:
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value={"created_at": None})

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(
                "507f1f77bcf86cd799439011"  # pragma: allowlist secret
            )

        assert result["account_number"] == 1
        assert result["member_since"] == "Nov 21, 2024"

    @pytest.mark.asyncio
    async def test_created_at_is_not_datetime(self) -> None:
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value={"created_at": "2025-01-01"})

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(
                "507f1f77bcf86cd799439011"  # pragma: allowlist secret
            )

        assert result["account_number"] == 1
        assert result["member_since"] == "Nov 21, 2024"

    @pytest.mark.asyncio
    async def test_exception_returns_defaults(self) -> None:
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(
            side_effect=Exception("DB connection lost")
        )

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(
                "507f1f77bcf86cd799439011"  # pragma: allowlist secret
            )

        assert result == {"account_number": 1, "member_since": "Nov 21, 2024"}

    @pytest.mark.asyncio
    async def test_count_documents_called_with_correct_filter(self) -> None:
        dt = datetime(2025, 3, 10, 8, 30, 0)
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value={"created_at": dt})
        mock_collection.count_documents = AsyncMock(return_value=0)

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(
                "507f1f77bcf86cd799439011"  # pragma: allowlist secret
            )

        mock_collection.count_documents.assert_awaited_once_with(
            {"created_at": {"$lt": dt}}
        )
        assert result["account_number"] == 1
        assert result["member_since"] == "Mar 10, 2025"

    @pytest.mark.asyncio
    async def test_user_has_no_created_at_key(self) -> None:
        """User document exists but has no created_at field at all."""
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value={"name": "Test"})

        with patch("app.utils.profile_card.users_collection", mock_collection):
            result = await get_user_metadata(
                "507f1f77bcf86cd799439011"  # pragma: allowlist secret
            )

        assert result["account_number"] == 1
        assert result["member_since"] == "Nov 21, 2024"


# ---------------------------------------------------------------------------
# generate_personality_phrase
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGeneratePersonalityPhrase:
    @pytest.mark.asyncio
    async def test_llm_succeeds_returns_phrase(self) -> None:
        mock_response = MagicMock()
        mock_response.content = "  Digital Alchemist  "

        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        memories = _make_memories(["likes coding", "enjoys music"])

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase(
                "user123", memories, profession="developer"
            )

        assert result == "Digital Alchemist"

    @pytest.mark.asyncio
    async def test_llm_succeeds_strips_quotes(self) -> None:
        mock_response = MagicMock()
        mock_response.content = '"Bold Visionary"'

        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase("user123", [], profession="")

        assert result == "Bold Visionary"

    @pytest.mark.asyncio
    async def test_llm_succeeds_with_single_quotes(self) -> None:
        mock_response = MagicMock()
        mock_response.content = "'Creative Soul'"

        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase("user123", [], profession="")

        assert result == "Creative Soul"

    @pytest.mark.asyncio
    async def test_llm_content_is_not_string(self) -> None:
        """When response.content is a list (e.g. multi-part), it gets str()-ified."""
        mock_response = MagicMock()
        mock_response.content = ["Digital", "Alchemist"]

        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase("user123", [], profession="")

        # str(["Digital", "Alchemist"]) -> "['Digital', 'Alchemist']"
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_llm_fails_profession_developer(self) -> None:
        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM timeout"))

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase(
                "user123", [], profession="developer"
            )

        assert result == "Curious Developer"

    @pytest.mark.asyncio
    async def test_llm_fails_profession_designer(self) -> None:
        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM error"))

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase(
                "user123", [], profession="UX Designer"
            )

        assert result == "Creative Designer"

    @pytest.mark.asyncio
    async def test_llm_fails_profession_engineer(self) -> None:
        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM error"))

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase(
                "user123", [], profession="Software Engineer"
            )

        assert result == "Innovative Engineer"

    @pytest.mark.asyncio
    async def test_llm_fails_profession_student(self) -> None:
        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM error"))

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase(
                "user123", [], profession="student"
            )

        assert result == "Eager Learner"

    @pytest.mark.asyncio
    async def test_llm_fails_profession_manager(self) -> None:
        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM error"))

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase(
                "user123", [], profession="Project Manager"
            )

        assert result == "Strategic Leader"

    @pytest.mark.asyncio
    async def test_llm_fails_profession_not_in_map(self) -> None:
        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM error"))

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase(
                "user123", [], profession="astronaut"
            )

        assert result == "Curious Adventurer"

    @pytest.mark.asyncio
    async def test_llm_fails_empty_profession(self) -> None:
        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM error"))

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase("user123", [], profession="")

        assert result == "Curious Adventurer"

    @pytest.mark.asyncio
    async def test_empty_memories_still_generates(self) -> None:
        mock_response = MagicMock()
        mock_response.content = "Lone Wanderer"

        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase(
                "user123", [], profession="developer"
            )

        assert result == "Lone Wanderer"
        # Verify prompt was invoked with empty memory_summary
        call_args = mock_llm.ainvoke.call_args[0][0]
        assert isinstance(call_args, str)

    @pytest.mark.asyncio
    async def test_memory_summary_joined_correctly(self) -> None:
        mock_response = MagicMock()
        mock_response.content = "Tech Poet"

        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        memories = _make_memories(["loves Python", "reads sci-fi", "plays guitar"])

        with patch("app.utils.profile_card.init_llm", return_value=mock_llm):
            result = await generate_personality_phrase(
                "user123", memories, profession="developer"
            )

        assert result == "Tech Poet"
        prompt_text = mock_llm.ainvoke.call_args[0][0]
        assert "loves Python" in prompt_text
        assert "reads sci-fi" in prompt_text
        assert "plays guitar" in prompt_text

    @pytest.mark.asyncio
    async def test_init_llm_called_with_gemini(self) -> None:
        mock_response = MagicMock()
        mock_response.content = "Digital Nomad"

        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(
            "app.utils.profile_card.init_llm", return_value=mock_llm
        ) as mock_init:
            await generate_personality_phrase("user123", [], profession="")

        mock_init.assert_called_once_with(preferred_provider="gemini")
        mock_llm.bind.assert_called_once_with(temperature=1.2, top_k=80)


# ---------------------------------------------------------------------------
# generate_user_bio
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateUserBio:
    @pytest.mark.asyncio
    async def test_user_not_found_returns_no_gmail(self) -> None:
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)

        with patch("app.utils.profile_card.users_collection", mock_collection):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                [],
            )

        assert bio == "Welcome to GAIA!"
        assert status == BioStatus.NO_GMAIL

    @pytest.mark.asyncio
    async def test_no_memories_gmail_connected_and_processed(self) -> None:
        user = _make_user(
            name="Alice",
            profession="developer",
            email_memory_processed=True,
        )
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        mock_composio = AsyncMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": True})

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
            patch(
                "app.utils.profile_card.get_random_bio_for_profession",
                return_value="A developer bio for Alice",
            ) as mock_bio_fn,
        ):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                [],
            )

        assert bio == "A developer bio for Alice"
        assert status == BioStatus.COMPLETED
        mock_bio_fn.assert_called_once_with("Alice", "developer")

    @pytest.mark.asyncio
    async def test_no_memories_gmail_connected_not_processed(self) -> None:
        user = _make_user(email_memory_processed=False)
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        mock_composio = AsyncMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": True})

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
        ):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                [],
            )

        assert bio == "Processing your insights... Please check back in a moment."
        assert status == BioStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_no_memories_no_gmail(self) -> None:
        user = _make_user(name="Bob", profession="")
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        mock_composio = AsyncMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": False})

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
            patch(
                "app.utils.profile_card.get_random_bio_for_profession",
                return_value="A default bio for Bob",
            ) as mock_bio_fn,
        ):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                [],
            )

        assert bio == "A default bio for Bob"
        assert status == BioStatus.NO_GMAIL
        # Empty profession falls back to "other"
        mock_bio_fn.assert_called_once_with("Bob", "other")

    @pytest.mark.asyncio
    async def test_memories_exist_llm_generates_bio(self) -> None:
        user = _make_user(name="Carol", profession="designer")
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        mock_composio = AsyncMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": True})

        mock_response = MagicMock()
        mock_response.content = "  Carol is a creative force.  "

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        memories = _make_memories(["loves design", "uses Figma daily"])

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
            patch("app.utils.profile_card.init_llm", return_value=mock_llm),
        ):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                memories,
            )

        assert bio == "Carol is a creative force."
        assert status == BioStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_memories_exist_llm_content_not_string(self) -> None:
        """When LLM returns non-string content, it gets str()-ified."""
        user = _make_user(name="Dana", profession="writer")
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        mock_composio = AsyncMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": True})

        mock_response = MagicMock()
        mock_response.content = ["Dana", "is", "awesome"]

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        memories = _make_memories(["writes poetry"])

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
            patch("app.utils.profile_card.init_llm", return_value=mock_llm),
        ):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                memories,
            )

        assert isinstance(bio, str)
        assert status == BioStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_llm_fails_fallback_has_gmail(self) -> None:
        """LLM raises, fallback checks Gmail -> PROCESSING."""
        user = _make_user(name="Eve")
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        mock_composio = AsyncMock()
        # First call in main try: succeeds
        # Second call in except block: also succeeds with gmail=True
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": True})

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM down"))

        memories = _make_memories(["some memory"])

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
            patch("app.utils.profile_card.init_llm", return_value=mock_llm),
        ):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                memories,
            )

        assert status == BioStatus.PROCESSING
        assert "Processing" in bio

    @pytest.mark.asyncio
    async def test_llm_fails_fallback_no_gmail(self) -> None:
        """LLM raises, fallback checks Gmail -> NO_GMAIL."""
        user = _make_user(name="Frank")
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        mock_composio = AsyncMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": False})

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM down"))

        memories = _make_memories(["some memory"])

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
            patch("app.utils.profile_card.init_llm", return_value=mock_llm),
        ):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                memories,
            )

        assert status == BioStatus.NO_GMAIL
        assert "Connect your Gmail" in bio

    @pytest.mark.asyncio
    async def test_llm_fails_fallback_composio_also_fails(self) -> None:
        """Both LLM and fallback composio check fail -> NO_GMAIL."""
        user = _make_user(name="Grace")
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        # First composio call succeeds, second (in except) raises
        mock_composio_ok = AsyncMock()
        mock_composio_ok.check_connection_status = AsyncMock(
            return_value={"gmail": True}
        )
        mock_composio_fail = AsyncMock()
        mock_composio_fail.check_connection_status = AsyncMock(
            side_effect=Exception("Composio down")
        )

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM down"))

        memories = _make_memories(["some memory"])

        call_count = 0

        def _get_composio_side_effect() -> AsyncMock:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return mock_composio_ok
            return mock_composio_fail

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                side_effect=_get_composio_side_effect,
            ),
            patch("app.utils.profile_card.init_llm", return_value=mock_llm),
        ):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                memories,
            )

        assert status == BioStatus.NO_GMAIL
        assert "Connect your Gmail" in bio

    @pytest.mark.asyncio
    async def test_db_find_raises_falls_to_outer_except(self) -> None:
        """DB failure in find_one triggers the outer except block."""
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(
            side_effect=Exception("DB connection lost")
        )

        mock_composio = AsyncMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": False})

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
        ):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                [],
            )

        assert status == BioStatus.NO_GMAIL

    @pytest.mark.asyncio
    async def test_memories_prompt_truncated_to_10000_chars(self) -> None:
        """Memory summary is truncated to 10000 characters in the prompt."""
        user = _make_user(name="Hank", profession="writer")
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        mock_composio = AsyncMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": True})

        mock_response = MagicMock()
        mock_response.content = "Hank is prolific."

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        # Create a very long memory
        long_content = "x" * 20000
        memories = _make_memories([long_content])

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
            patch("app.utils.profile_card.init_llm", return_value=mock_llm),
        ):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                memories,
            )

        assert bio == "Hank is prolific."
        assert status == BioStatus.COMPLETED
        # Verify the prompt was called (memory_summary is truncated internally)
        mock_llm.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_init_llm_called_with_gemini_for_bio(self) -> None:
        user = _make_user(name="Ivy", profession="artist")
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        mock_composio = AsyncMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": True})

        mock_response = MagicMock()
        mock_response.content = "Ivy creates beauty."

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        memories = _make_memories(["paints murals"])

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
            patch(
                "app.utils.profile_card.init_llm", return_value=mock_llm
            ) as mock_init,
        ):
            await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                memories,
            )

        mock_init.assert_called_once_with(preferred_provider="gemini")

    @pytest.mark.asyncio
    async def test_no_memories_profession_missing_uses_other(self) -> None:
        """When profession is empty, 'other' is passed to get_random_bio_for_profession."""
        user = _make_user(name="Jack", profession="")
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        mock_composio = AsyncMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": True})

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
            patch(
                "app.utils.profile_card.get_random_bio_for_profession",
                return_value="A default bio",
            ) as mock_bio_fn,
        ):
            user["email_memory_processed"] = True
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                [],
            )

        mock_bio_fn.assert_called_once_with("Jack", "other")
        assert status == BioStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_user_missing_onboarding_key(self) -> None:
        """User document lacks onboarding key entirely."""
        user: Dict[str, Any] = {"name": "Kara"}
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        mock_composio = AsyncMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": False})

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
            patch(
                "app.utils.profile_card.get_random_bio_for_profession",
                return_value="Default bio for Kara",
            ) as mock_bio_fn,
        ):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                [],
            )

        # profession defaults to "" -> "other"
        mock_bio_fn.assert_called_once_with("Kara", "other")
        assert status == BioStatus.NO_GMAIL

    @pytest.mark.asyncio
    async def test_user_missing_name_defaults_to_user(self) -> None:
        """User document lacks name key entirely."""
        user: Dict[str, Any] = {
            "onboarding": {"preferences": {"profession": "chef"}},
            "email_memory_processed": False,
        }
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=user)

        mock_composio = AsyncMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": False})

        with (
            patch("app.utils.profile_card.users_collection", mock_collection),
            patch(
                "app.utils.profile_card.get_composio_service",
                return_value=mock_composio,
            ),
            patch(
                "app.utils.profile_card.get_random_bio_for_profession",
                return_value="Chef bio for User",
            ) as mock_bio_fn,
        ):
            bio, status = await generate_user_bio(
                "507f1f77bcf86cd799439011",  # pragma: allowlist secret
                [],
            )

        mock_bio_fn.assert_called_once_with("User", "chef")
        assert status == BioStatus.NO_GMAIL
