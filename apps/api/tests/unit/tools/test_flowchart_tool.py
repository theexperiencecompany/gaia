"""Unit tests for app.agents.tools.flowchart_tool."""

from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.flowchart_tool"


def _make_config(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    """Return a minimal RunnableConfig-like dict."""
    return {"metadata": {"user_id": user_id}}


# ---------------------------------------------------------------------------
# Tests: create_flowchart
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateFlowchart:
    """Tests for the create_flowchart tool."""

    async def test_happy_path_default_direction(self) -> None:
        """Returns a prompt dict with the rendered template, default TD direction."""
        from app.agents.tools.flowchart_tool import create_flowchart

        result = await create_flowchart.coroutine(
            config=_make_config(),
            description="User login flow",
        )

        assert "prompt" in result
        assert "User login flow" in result["prompt"]
        assert "TD" in result["prompt"]

    async def test_custom_direction_lr(self) -> None:
        """Custom direction LR is used in the prompt."""
        from app.agents.tools.flowchart_tool import create_flowchart

        result = await create_flowchart.coroutine(
            config=_make_config(),
            description="Data pipeline",
            direction="LR",
        )

        assert "LR" in result["prompt"]
        assert "Data pipeline" in result["prompt"]

    async def test_custom_direction_bt(self) -> None:
        """Bottom-to-top direction works correctly."""
        from app.agents.tools.flowchart_tool import create_flowchart

        result = await create_flowchart.coroutine(
            config=_make_config(),
            description="Hierarchy chart",
            direction="BT",
        )

        assert "BT" in result["prompt"]

    async def test_custom_direction_rl(self) -> None:
        """Right-to-left direction works correctly."""
        from app.agents.tools.flowchart_tool import create_flowchart

        result = await create_flowchart.coroutine(
            config=_make_config(),
            description="Process flow",
            direction="RL",
        )

        assert "RL" in result["prompt"]

    async def test_invalid_direction_defaults_to_td(self) -> None:
        """Invalid direction is normalized to TD."""
        from app.agents.tools.flowchart_tool import create_flowchart

        result = await create_flowchart.coroutine(
            config=_make_config(),
            description="Test chart",
            direction="INVALID",
        )

        assert "prompt" in result
        # The tool forces TD when direction is not in the valid list
        assert "TD" in result["prompt"]

    async def test_empty_direction_defaults_to_td(self) -> None:
        """Empty string direction defaults to TD."""
        from app.agents.tools.flowchart_tool import create_flowchart

        result = await create_flowchart.coroutine(
            config=_make_config(),
            description="Simple flow",
            direction="",
        )

        assert "TD" in result["prompt"]

    async def test_result_is_dict_with_prompt_key(self) -> None:
        """Result structure is a dict with exactly the 'prompt' key."""
        from app.agents.tools.flowchart_tool import create_flowchart

        result = await create_flowchart.coroutine(
            config=_make_config(),
            description="Any description",
        )

        assert isinstance(result, dict)
        assert "prompt" in result
        assert isinstance(result["prompt"], str)

    async def test_description_embedded_in_prompt(self) -> None:
        """The user's description appears in the generated prompt."""
        from app.agents.tools.flowchart_tool import create_flowchart

        desc = "CI/CD pipeline with testing and deployment stages"
        result = await create_flowchart.coroutine(
            config=_make_config(),
            description=desc,
        )

        assert desc in result["prompt"]
