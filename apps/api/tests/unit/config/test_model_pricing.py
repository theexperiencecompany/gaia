"""Model pricing: the in-code rate card and token cost arithmetic.

Regression anchor: in production, gemini-3.1-flash-lite (the vision and
memory model) was priced at DEFAULT_PRICING — ~10x its real input rate —
because its row was missing from the prod ai_models Mongo collection and
nothing enforced the seed. Pricing now ships in code (MODEL_PRICING), so a
runtime-referenced model without a rate fails this suite instead of silently
distorting COGS in prod.
"""

from contextlib import AbstractContextManager
from unittest.mock import MagicMock, patch

import pytest

from app.config.model_pricing import (
    DEFAULT_PRICING,
    MODEL_PRICING,
    ModelPricing,
    calculate_token_cost,
    get_model_pricing,
    has_rate_card,
)
from app.config.settings import settings
from app.constants.llm import (
    AUX_MODEL_NAME,
    DEFAULT_MODEL_NAME,
    HIL_JUDGE_MODEL_NAME,
    MEMORY_MODEL_NAME,
    OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT,
    PAID_MODEL_NAME,
    VISION_MODEL_NAME,
)
from shared.py.wide_events import log

# `log.reset()` between tests -- the fallback-logging test below asserts on
# `log.get()["errors"]`, which otherwise accumulates across the module.
pytestmark = pytest.mark.usefixtures("_fresh_wide_event")


@pytest.fixture
def _fresh_wide_event() -> None:
    log.reset()


# Every model id the runtime actually meters. A new runtime model constant
# must be added to MODEL_PRICING, or the coverage test below catches it.
RUNTIME_MODEL_IDS = sorted(
    {
        DEFAULT_MODEL_NAME,
        PAID_MODEL_NAME,
        AUX_MODEL_NAME,
        MEMORY_MODEL_NAME,
        VISION_MODEL_NAME,
        HIL_JUDGE_MODEL_NAME,
        # The browser lane's decision model and its text helper — both metered
        # from Browser-Use's history.
        settings.BROWSER_USE_JEV_MODEL,
        settings.BROWSER_USE_JEV_TEXT_MODEL,
    }
)


class TestModelPricingShape:
    def test_construction(self) -> None:
        pricing = ModelPricing(input_cost_per_1k=0.01, output_cost_per_1k=0.03)

        assert pricing.input_cost_per_1k == 0.01
        assert pricing.output_cost_per_1k == 0.03
        assert pricing.cached_input_cost_per_1k == 0.0

    def test_default_pricing_values(self) -> None:
        assert DEFAULT_PRICING.input_cost_per_1k == 0.001
        assert DEFAULT_PRICING.output_cost_per_1k == 0.002
        assert DEFAULT_PRICING.cached_input_cost_per_1k == 0.00025


class TestEveryRuntimeModelIsPriced:
    """The drift-proofing this refactor exists for."""

    @pytest.mark.parametrize("model_id", RUNTIME_MODEL_IDS)
    def test_a_referenced_model_never_falls_back_to_default_pricing(self, model_id: str) -> None:
        """DEFAULT_PRICING is ~10x the real rate of the cheap models; a runtime model resolving to it means its COGS numbers are fiction."""
        assert get_model_pricing(model_id) is not DEFAULT_PRICING

    def test_the_memory_and_vision_model_carries_its_real_rate(self) -> None:
        """The exact production regression: gemini-3.1-flash-lite priced at $0.001/1k input instead of $0.0001."""
        pricing = get_model_pricing("gemini-3.1-flash-lite")

        assert pricing.input_cost_per_1k == 0.0001
        assert pricing.output_cost_per_1k == 0.0004
        assert pricing.cached_input_cost_per_1k == 0.000025

    def test_the_default_model_carries_its_real_rate(self) -> None:
        pricing = get_model_pricing(DEFAULT_MODEL_NAME)

        assert pricing.input_cost_per_1k == 0.00004
        assert pricing.output_cost_per_1k == 0.00008
        assert pricing.cached_input_cost_per_1k == 0.000016

    def test_the_judge_model_carries_its_real_rate(self) -> None:
        """The approval gate judges here; an unpriced judge id would meter at DEFAULT_PRICING (~3x input, ~1x output — close enough to look right while being wrong, the worst kind of drift)."""
        pricing = get_model_pricing(HIL_JUDGE_MODEL_NAME)

        assert pricing.input_cost_per_1k == 0.0003
        assert pricing.output_cost_per_1k == 0.0025
        assert pricing.cached_input_cost_per_1k == 0.00003

    def test_an_unknown_model_still_gets_the_loud_default(self) -> None:
        assert get_model_pricing("some-model-nobody-registered") == DEFAULT_PRICING

    def test_the_fallback_logs_the_mispricing(self) -> None:
        """DEFAULT_PRICING is not the model's real rate, so serving it must log the message an operator greps for plus the model_name field."""
        with patch("app.config.model_pricing.log") as mock_log:
            get_model_pricing("some-model-nobody-registered")

        mock_log.error.assert_called_once()
        args, kwargs = mock_log.error.call_args
        assert args[0].endswith("model missing from pricing table — priced at DEFAULT_PRICING")
        assert kwargs == {"model_name": "some-model-nobody-registered"}

    def test_a_known_model_does_not_log(self) -> None:
        get_model_pricing(DEFAULT_MODEL_NAME)

        assert not log.get().get("errors", [])

    @pytest.mark.parametrize("variant", ["nitro", "floor"])
    def test_an_openrouter_routing_variant_is_priced_as_its_base_model(self, variant: str) -> None:
        """Routing variants such as :nitro only pick the provider; the default price misprices every turn."""
        with patch("app.config.model_pricing.log") as mock_log:
            pricing = get_model_pricing(f"{DEFAULT_MODEL_NAME}:{variant}")

        assert pricing == MODEL_PRICING[DEFAULT_MODEL_NAME]
        mock_log.error.assert_not_called()

    def test_the_onboarding_declaration_matches_the_rate_card(self) -> None:
        """Every id in OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT must carry a rate; the default model stays text-only, or flipping it without the live gate run would 400 real turns mid-stream."""
        assert OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT == {DEFAULT_MODEL_NAME: False}
        assert set(OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT) <= set(MODEL_PRICING)

    def test_no_table_entry_accidentally_equals_the_fallback(self) -> None:
        """An entry equal to DEFAULT_PRICING is indistinguishable from a missing one — someone pasted the fallback instead of the real rate."""
        for model_id, pricing in MODEL_PRICING.items():
            assert pricing != DEFAULT_PRICING, model_id


class TestHasRateCard:
    """The flag the analytics event reports as cost_estimated."""

    def test_a_priced_model_is_not_estimated(self) -> None:
        assert has_rate_card(DEFAULT_MODEL_NAME) is True

    def test_a_model_missing_from_the_table_is_estimated(self) -> None:
        assert has_rate_card("some-model-nobody-registered") is False


class TestAuxModelPricing:
    """The aux lane runs on the same model id as the graph, isolated by session suffixes rather than a second model id.

    Measured: the old separate id's provider pool could not hold session
    affinity for tool-carrying requests (fixed sessions read
    [1536,0]/[0,0]/[0,0]) while the 0731 pool chains perfectly
    ([0,1792,1792]/[1792,1792,1792]); pricing follows at the default rate.
    """

    def test_aux_resolves_to_the_default_model_id(self) -> None:
        assert AUX_MODEL_NAME == DEFAULT_MODEL_NAME

    def test_aux_spend_meters_at_the_default_rate(self) -> None:
        assert get_model_pricing(AUX_MODEL_NAME) == get_model_pricing(DEFAULT_MODEL_NAME)

    def test_the_retired_aux_id_still_meters_at_its_served_rate(self) -> None:
        """Historical llm_call events on the old "0423" id must price at the rate they were actually served at, never fall through to DEFAULT_PRICING."""
        retired = get_model_pricing("deepseek/deepseek-v4-flash")

        assert retired.input_cost_per_1k == 0.00006426
        assert retired.output_cost_per_1k == 0.00012852
        assert retired != DEFAULT_PRICING

    def test_aux_cached_tokens_meter_at_the_cached_rate_end_to_end(self) -> None:
        """Cached input prices at ~1/10th; a metering bug billing it at the full rate would silently erase that saving."""
        result = calculate_token_cost(
            AUX_MODEL_NAME, input_tokens=100_000, output_tokens=2_000, cached_tokens=80_000
        )
        rate = get_model_pricing(AUX_MODEL_NAME)

        assert result["input_cost"] == pytest.approx(20_000 / 1000 * rate.input_cost_per_1k)
        assert result["cached_input_cost"] == pytest.approx(
            80_000 / 1000 * rate.cached_input_cost_per_1k
        )
        # The live 0731 rate card prices cached input at two-fifths of uncached.
        assert rate.cached_input_cost_per_1k == pytest.approx(rate.input_cost_per_1k * 2 / 5)


def _with_rate(pricing: ModelPricing) -> AbstractContextManager[MagicMock]:
    """Patch the table lookup so arithmetic is asserted against a known rate."""
    return patch("app.config.model_pricing.get_model_pricing", MagicMock(return_value=pricing))


class TestCalculateTokenCost:
    """Arithmetic and rounding, isolated from the table via a patched rate."""

    def test_basic_cost_calculation(self) -> None:
        with _with_rate(ModelPricing(input_cost_per_1k=0.01, output_cost_per_1k=0.03)):
            result = calculate_token_cost("any-model", input_tokens=1000, output_tokens=500)

        assert result["input_cost"] == pytest.approx(0.01)
        assert result["output_cost"] == pytest.approx(0.015)
        assert result["total_cost"] == pytest.approx(0.025)

    def test_zero_tokens_cost_nothing(self) -> None:
        with _with_rate(ModelPricing(input_cost_per_1k=0.01, output_cost_per_1k=0.03)):
            result = calculate_token_cost("any-model", input_tokens=0, output_tokens=0)

        assert result["total_cost"] == 0.0

    def test_rounding_to_six_decimals(self) -> None:
        with _with_rate(ModelPricing(input_cost_per_1k=0.0000015, output_cost_per_1k=0.0)):
            result = calculate_token_cost("any-model", input_tokens=1, output_tokens=0)

        # (1/1000) * 0.0000015 = 0.0000000015 -> rounds to 0.0
        assert result["input_cost"] == 0.0

    def test_large_token_count(self) -> None:
        with _with_rate(ModelPricing(input_cost_per_1k=0.001, output_cost_per_1k=0.002)):
            result = calculate_token_cost(
                "any-model", input_tokens=1_000_000, output_tokens=1_000_000
            )

        assert result["input_cost"] == pytest.approx(1.0)
        assert result["output_cost"] == pytest.approx(2.0)
        assert result["total_cost"] == pytest.approx(3.0)

    def test_result_keys(self) -> None:
        with _with_rate(DEFAULT_PRICING):
            result = calculate_token_cost("any-model", input_tokens=10, output_tokens=10)

        assert set(result) == {"input_cost", "cached_input_cost", "output_cost", "total_cost"}

    def test_cached_tokens_billed_at_discounted_rate(self) -> None:
        with _with_rate(
            ModelPricing(
                input_cost_per_1k=0.01, output_cost_per_1k=0.0, cached_input_cost_per_1k=0.001
            )
        ):
            result = calculate_token_cost(
                "any-model", input_tokens=1000, output_tokens=0, cached_tokens=600
            )

        # uncached 400 @ 0.01/1k = 0.004; cached 600 @ 0.001/1k = 0.0006
        assert result["input_cost"] == pytest.approx(0.004)
        assert result["cached_input_cost"] == pytest.approx(0.0006)
        assert result["total_cost"] == pytest.approx(0.0046)

    def test_cached_tokens_never_exceed_input_tokens(self) -> None:
        """A provider reporting more cached than prompt tokens must not produce a negative uncached cost."""
        with _with_rate(
            ModelPricing(
                input_cost_per_1k=0.01, output_cost_per_1k=0.0, cached_input_cost_per_1k=0.001
            )
        ):
            result = calculate_token_cost(
                "any-model", input_tokens=100, output_tokens=0, cached_tokens=500
            )

        assert result["input_cost"] == 0.0
        assert result["cached_input_cost"] == pytest.approx(0.0001)
