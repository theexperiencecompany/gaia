"""Unit tests for model pricing configuration.

Tests cover:
- ModelPricing NamedTuple construction
- DEFAULT_PRICING fallback values
- get_model_pricing: exact match, missing pricing fields, model not found, exceptions
- calculate_token_cost: correct arithmetic, rounding, zero tokens, large values
"""

from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


from app.config.model_pricing import (
    DEFAULT_PRICING,
    ModelPricing,
    calculate_token_cost,
    get_model_pricing,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model(
    *,
    pricing_per_1k_input_tokens: Optional[float] = 0.01,
    pricing_per_1k_output_tokens: Optional[float] = 0.03,
) -> MagicMock:
    """Create a mock ModelConfig with optional pricing attributes."""
    model = MagicMock()
    model.pricing_per_1k_input_tokens = pricing_per_1k_input_tokens
    model.pricing_per_1k_output_tokens = pricing_per_1k_output_tokens
    return model


# ---------------------------------------------------------------------------
# Tests: ModelPricing NamedTuple
# ---------------------------------------------------------------------------


class TestModelPricing:
    """Tests for the ModelPricing NamedTuple."""

    def test_construction(self) -> None:
        pricing = ModelPricing(input_cost_per_1k=0.005, output_cost_per_1k=0.015)
        assert pricing.input_cost_per_1k == pytest.approx(0.005)
        assert pricing.output_cost_per_1k == pytest.approx(0.015)

    def test_is_tuple(self) -> None:
        pricing = ModelPricing(input_cost_per_1k=0.001, output_cost_per_1k=0.002)
        assert isinstance(pricing, tuple)
        assert pricing[0] == pytest.approx(0.001)
        assert pricing[1] == pytest.approx(0.002)

    def test_equality(self) -> None:
        a = ModelPricing(input_cost_per_1k=0.01, output_cost_per_1k=0.02)
        b = ModelPricing(input_cost_per_1k=0.01, output_cost_per_1k=0.02)
        assert a == b

    def test_inequality(self) -> None:
        a = ModelPricing(input_cost_per_1k=0.01, output_cost_per_1k=0.02)
        b = ModelPricing(input_cost_per_1k=0.01, output_cost_per_1k=0.03)
        assert a != b


# ---------------------------------------------------------------------------
# Tests: DEFAULT_PRICING
# ---------------------------------------------------------------------------


class TestDefaultPricing:
    """Tests for the default fallback pricing constant."""

    def test_default_values(self) -> None:
        assert DEFAULT_PRICING.input_cost_per_1k == pytest.approx(0.001)
        assert DEFAULT_PRICING.output_cost_per_1k == pytest.approx(0.002)

    def test_default_is_model_pricing(self) -> None:
        assert isinstance(DEFAULT_PRICING, ModelPricing)


# ---------------------------------------------------------------------------
# Tests: get_model_pricing
# ---------------------------------------------------------------------------


class TestGetModelPricing:
    """Tests for get_model_pricing — model lookup and fallback behavior."""

    @patch("app.config.model_pricing.get_model_by_id", new_callable=AsyncMock)
    async def test_exact_match_returns_model_pricing(
        self, mock_get_model: AsyncMock
    ) -> None:
        model = _make_model(
            pricing_per_1k_input_tokens=0.01,
            pricing_per_1k_output_tokens=0.03,
        )
        mock_get_model.return_value = model

        result = await get_model_pricing("gpt-4o")

        assert result == ModelPricing(input_cost_per_1k=0.01, output_cost_per_1k=0.03)
        mock_get_model.assert_awaited_once_with("gpt-4o")

    @patch("app.config.model_pricing.get_model_by_id", new_callable=AsyncMock)
    async def test_model_not_found_returns_default(
        self, mock_get_model: AsyncMock
    ) -> None:
        mock_get_model.return_value = None

        result = await get_model_pricing("unknown-model")

        assert result == DEFAULT_PRICING

    @patch("app.config.model_pricing.get_model_by_id", new_callable=AsyncMock)
    async def test_model_missing_input_pricing_returns_default(
        self, mock_get_model: AsyncMock
    ) -> None:
        model = _make_model(
            pricing_per_1k_input_tokens=None,
            pricing_per_1k_output_tokens=0.03,
        )
        mock_get_model.return_value = model

        result = await get_model_pricing("gpt-4o")

        assert result == DEFAULT_PRICING

    @patch("app.config.model_pricing.get_model_by_id", new_callable=AsyncMock)
    async def test_model_missing_output_pricing_returns_default(
        self, mock_get_model: AsyncMock
    ) -> None:
        model = _make_model(
            pricing_per_1k_input_tokens=0.01,
            pricing_per_1k_output_tokens=None,
        )
        mock_get_model.return_value = model

        result = await get_model_pricing("gpt-4o")

        assert result == DEFAULT_PRICING

    @patch("app.config.model_pricing.get_model_by_id", new_callable=AsyncMock)
    async def test_model_missing_both_pricing_fields_returns_default(
        self, mock_get_model: AsyncMock
    ) -> None:
        model = _make_model(
            pricing_per_1k_input_tokens=None,
            pricing_per_1k_output_tokens=None,
        )
        mock_get_model.return_value = model

        result = await get_model_pricing("gpt-4o")

        assert result == DEFAULT_PRICING

    @patch("app.config.model_pricing.get_model_by_id", new_callable=AsyncMock)
    async def test_exception_returns_default(self, mock_get_model: AsyncMock) -> None:
        mock_get_model.side_effect = RuntimeError("db connection failed")

        result = await get_model_pricing("gpt-4o")

        assert result == DEFAULT_PRICING

    @patch("app.config.model_pricing.get_model_by_id", new_callable=AsyncMock)
    async def test_pricing_values_cast_to_float(
        self, mock_get_model: AsyncMock
    ) -> None:
        """Ensure integer or Decimal-like pricing values are cast to float."""
        model = MagicMock()
        model.pricing_per_1k_input_tokens = 1  # int
        model.pricing_per_1k_output_tokens = 2  # int
        mock_get_model.return_value = model

        result = await get_model_pricing("model-x")

        assert result == ModelPricing(input_cost_per_1k=1.0, output_cost_per_1k=2.0)
        assert isinstance(result.input_cost_per_1k, float)
        assert isinstance(result.output_cost_per_1k, float)

    @patch("app.config.model_pricing.get_model_by_id", new_callable=AsyncMock)
    async def test_zero_pricing_is_valid(self, mock_get_model: AsyncMock) -> None:
        """Zero cost should NOT fall back to default — 0 is a valid price."""
        model = _make_model(
            pricing_per_1k_input_tokens=0.0,
            pricing_per_1k_output_tokens=0.0,
        )
        mock_get_model.return_value = model

        result = await get_model_pricing("free-model")

        assert result == ModelPricing(input_cost_per_1k=0.0, output_cost_per_1k=0.0)

    @patch("app.config.model_pricing.get_model_by_id", new_callable=AsyncMock)
    async def test_model_without_pricing_attributes_returns_default(
        self, mock_get_model: AsyncMock
    ) -> None:
        """Model object that lacks pricing attributes entirely (getattr returns None)."""
        model = MagicMock(spec=[])  # spec=[] means no attributes
        mock_get_model.return_value = model

        result = await get_model_pricing("barebones-model")

        assert result == DEFAULT_PRICING


# ---------------------------------------------------------------------------
# Tests: calculate_token_cost
# ---------------------------------------------------------------------------


class TestCalculateTokenCost:
    """Tests for calculate_token_cost — arithmetic and rounding."""

    @patch("app.config.model_pricing.get_model_pricing", new_callable=AsyncMock)
    async def test_basic_cost_calculation(self, mock_pricing: AsyncMock) -> None:
        mock_pricing.return_value = ModelPricing(
            input_cost_per_1k=0.01,
            output_cost_per_1k=0.03,
        )

        result = await calculate_token_cost(
            "gpt-4o", input_tokens=1000, output_tokens=500
        )

        # input: (1000/1000) * 0.01 = 0.01
        # output: (500/1000) * 0.03 = 0.015
        # total: 0.025
        assert result["input_cost"] == pytest.approx(0.01)
        assert result["output_cost"] == pytest.approx(0.015)
        assert result["total_cost"] == pytest.approx(0.025)

    @patch("app.config.model_pricing.get_model_pricing", new_callable=AsyncMock)
    async def test_zero_tokens(self, mock_pricing: AsyncMock) -> None:
        mock_pricing.return_value = ModelPricing(
            input_cost_per_1k=0.01,
            output_cost_per_1k=0.03,
        )

        result = await calculate_token_cost("gpt-4o", input_tokens=0, output_tokens=0)

        assert result["input_cost"] == pytest.approx(0.0)
        assert result["output_cost"] == pytest.approx(0.0)
        assert result["total_cost"] == pytest.approx(0.0)

    @patch("app.config.model_pricing.get_model_pricing", new_callable=AsyncMock)
    async def test_only_input_tokens(self, mock_pricing: AsyncMock) -> None:
        mock_pricing.return_value = ModelPricing(
            input_cost_per_1k=0.01,
            output_cost_per_1k=0.03,
        )

        result = await calculate_token_cost(
            "gpt-4o", input_tokens=2500, output_tokens=0
        )

        # input: (2500/1000) * 0.01 = 0.025
        assert result["input_cost"] == pytest.approx(0.025)
        assert result["output_cost"] == pytest.approx(0.0)
        assert result["total_cost"] == pytest.approx(0.025)

    @patch("app.config.model_pricing.get_model_pricing", new_callable=AsyncMock)
    async def test_only_output_tokens(self, mock_pricing: AsyncMock) -> None:
        mock_pricing.return_value = ModelPricing(
            input_cost_per_1k=0.01,
            output_cost_per_1k=0.03,
        )

        result = await calculate_token_cost(
            "gpt-4o", input_tokens=0, output_tokens=3000
        )

        # output: (3000/1000) * 0.03 = 0.09
        assert result["input_cost"] == pytest.approx(0.0)
        assert result["output_cost"] == pytest.approx(0.09)
        assert result["total_cost"] == pytest.approx(0.09)

    @patch("app.config.model_pricing.get_model_pricing", new_callable=AsyncMock)
    async def test_rounding_precision(self, mock_pricing: AsyncMock) -> None:
        """Ensure costs are rounded to 6 decimal places."""
        mock_pricing.return_value = ModelPricing(
            input_cost_per_1k=0.000001,
            output_cost_per_1k=0.000002,
        )

        result = await calculate_token_cost(
            "cheap-model", input_tokens=1, output_tokens=1
        )

        # input: (1/1000) * 0.000001 = 0.000000001 -> rounds to 0.0
        # output: (1/1000) * 0.000002 = 0.000000002 -> rounds to 0.0
        assert result["input_cost"] == pytest.approx(0.0)
        assert result["output_cost"] == pytest.approx(0.0)
        assert result["total_cost"] == pytest.approx(0.0)

    @patch("app.config.model_pricing.get_model_pricing", new_callable=AsyncMock)
    async def test_large_token_count(self, mock_pricing: AsyncMock) -> None:
        mock_pricing.return_value = ModelPricing(
            input_cost_per_1k=0.01,
            output_cost_per_1k=0.03,
        )

        result = await calculate_token_cost(
            "gpt-4o", input_tokens=1_000_000, output_tokens=500_000
        )

        # input: (1_000_000 / 1000) * 0.01 = 10.0
        # output: (500_000 / 1000) * 0.03 = 15.0
        assert result["input_cost"] == pytest.approx(10.0)
        assert result["output_cost"] == pytest.approx(15.0)
        assert result["total_cost"] == pytest.approx(25.0)

    @patch("app.config.model_pricing.get_model_pricing", new_callable=AsyncMock)
    async def test_result_keys(self, mock_pricing: AsyncMock) -> None:
        """Verify the returned dict has exactly the expected keys."""
        mock_pricing.return_value = DEFAULT_PRICING

        result = await calculate_token_cost(
            "any-model", input_tokens=100, output_tokens=50
        )

        assert set(result.keys()) == {"input_cost", "output_cost", "total_cost"}

    @patch("app.config.model_pricing.get_model_pricing", new_callable=AsyncMock)
    async def test_total_equals_sum_of_parts(self, mock_pricing: AsyncMock) -> None:
        mock_pricing.return_value = ModelPricing(
            input_cost_per_1k=0.015,
            output_cost_per_1k=0.045,
        )

        result = await calculate_token_cost(
            "gpt-4o", input_tokens=3333, output_tokens=7777
        )

        expected_input = round((3333 / 1000) * 0.015, 6)
        expected_output = round((7777 / 1000) * 0.045, 6)
        expected_total = round(expected_input + expected_output, 6)

        assert result["input_cost"] == expected_input
        assert result["output_cost"] == expected_output
        assert result["total_cost"] == expected_total

    @patch("app.config.model_pricing.get_model_pricing", new_callable=AsyncMock)
    async def test_fractional_tokens(self, mock_pricing: AsyncMock) -> None:
        """Token counts less than 1000 should produce fractional costs."""
        mock_pricing.return_value = ModelPricing(
            input_cost_per_1k=0.01,
            output_cost_per_1k=0.03,
        )

        result = await calculate_token_cost(
            "gpt-4o", input_tokens=100, output_tokens=200
        )

        # input: (100/1000) * 0.01 = 0.001
        # output: (200/1000) * 0.03 = 0.006
        assert result["input_cost"] == pytest.approx(0.001)
        assert result["output_cost"] == pytest.approx(0.006)
        assert result["total_cost"] == pytest.approx(0.007)

    @patch("app.config.model_pricing.get_model_by_id", new_callable=AsyncMock)
    async def test_end_to_end_with_default_pricing(
        self, mock_get_model: AsyncMock
    ) -> None:
        """Full integration: unknown model falls back to DEFAULT_PRICING."""
        mock_get_model.return_value = None

        result = await calculate_token_cost(
            "unknown-model", input_tokens=5000, output_tokens=2000
        )

        # DEFAULT_PRICING: input=0.001, output=0.002
        # input: (5000/1000) * 0.001 = 0.005
        # output: (2000/1000) * 0.002 = 0.004
        assert result["input_cost"] == pytest.approx(0.005)
        assert result["output_cost"] == pytest.approx(0.004)
        assert result["total_cost"] == pytest.approx(0.009)
