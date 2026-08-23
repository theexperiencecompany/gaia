"""Model pricing: the in-code rate card and token cost arithmetic.

Regression anchor: in production, ``gemini-3.1-flash-lite`` (the vision and
memory model) was priced at DEFAULT_PRICING — ~10x its real input rate —
because its row was missing from the prod ``ai_models`` Mongo collection and
nothing enforced the seed. Pricing now ships in code (``MODEL_PRICING``), so a
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
)
from app.constants.llm import (
    AUX_MODEL_NAME,
    DEFAULT_MODEL_NAME,
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


# Every model id the runtime actually meters: the graph lane on both tiers, the
# aux one-shot alias, and the memory/vision model. A new runtime model constant
# belongs in MODEL_PRICING — the coverage test below is what turns a forgotten
# rate into a red build instead of a prod log line.
RUNTIME_MODEL_IDS = sorted(
    {DEFAULT_MODEL_NAME, PAID_MODEL_NAME, AUX_MODEL_NAME, MEMORY_MODEL_NAME, VISION_MODEL_NAME}
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
        """DEFAULT_PRICING is ~10x the real rate of the cheap models; a runtime
        model resolving to it means its COGS numbers are fiction."""
        assert get_model_pricing(model_id) is not DEFAULT_PRICING

    def test_the_memory_and_vision_model_carries_its_real_rate(self) -> None:
        """The exact production regression: gemini-3.1-flash-lite priced at
        $0.001/1k input instead of $0.0001, with no database row to depend on."""
        pricing = get_model_pricing("gemini-3.1-flash-lite")

        assert pricing.input_cost_per_1k == 0.0001
        assert pricing.output_cost_per_1k == 0.0004
        assert pricing.cached_input_cost_per_1k == 0.000025

    def test_the_default_model_carries_its_real_rate(self) -> None:
        pricing = get_model_pricing(DEFAULT_MODEL_NAME)

        assert pricing.input_cost_per_1k == 0.00014
        assert pricing.output_cost_per_1k == 0.00028
        assert pricing.cached_input_cost_per_1k == 0.000028

    def test_an_unknown_model_still_gets_the_loud_default(self) -> None:
        assert get_model_pricing("some-model-nobody-registered") == DEFAULT_PRICING

    def test_the_fallback_logs_the_mispricing(self) -> None:
        """DEFAULT_PRICING is not the model's real rate, so serving it must
        never pass quietly — the error line is what surfaced the prod bug.
        Asserted exactly: the message is what an operator greps for, and the
        model_name field is what tells them WHICH model is mispriced."""
        with patch("app.config.model_pricing.log") as mock_log:
            get_model_pricing("some-model-nobody-registered")

        mock_log.error.assert_called_once()
        args, kwargs = mock_log.error.call_args
        assert args[0].endswith("model missing from pricing table — priced at DEFAULT_PRICING")
        assert kwargs == {"model_name": "some-model-nobody-registered"}

    def test_a_known_model_does_not_log(self) -> None:
        get_model_pricing(DEFAULT_MODEL_NAME)

        assert not log.get().get("errors", [])

    def test_the_onboarding_declaration_matches_the_rate_card(self) -> None:
        """OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT is the model-onboarding gate's one
        place of declaration; every id in it must also carry a rate, and the
        default model stays declared text-only (its tool media routes through
        the caption fallback — flipping this to True without the live gate run
        would 400 real turns mid-stream)."""
        assert OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT == {DEFAULT_MODEL_NAME: False}
        assert set(OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT) <= set(MODEL_PRICING)

    def test_no_table_entry_accidentally_equals_the_fallback(self) -> None:
        """An entry equal to DEFAULT_PRICING is indistinguishable from a missing
        one — someone pasted the fallback instead of the real rate."""
        for model_id, pricing in MODEL_PRICING.items():
            assert pricing != DEFAULT_PRICING, model_id


class TestAuxModelPricing:
    """The aux lane runs a separate model id under AUX_MODEL_NAME ("V4 Flash
    0423", not the "0731" revision the graph runs) with its OWN published rate.
    The two ids carry different OpenRouter rate cards, and 0423 is the CHEAPER
    of the two, so pricing the aux lane at the default's rate would over-count
    aux COGS by ~2.2x."""

    def test_aux_model_priced_at_its_own_rate(self) -> None:
        pricing = get_model_pricing(AUX_MODEL_NAME)

        assert pricing.input_cost_per_1k == 0.00006426
        assert pricing.output_cost_per_1k == 0.00012852

    def test_aux_rate_differs_from_default_rate(self) -> None:
        aux = get_model_pricing(AUX_MODEL_NAME)
        default = get_model_pricing(DEFAULT_MODEL_NAME)

        assert aux != default
        assert aux.input_cost_per_1k < default.input_cost_per_1k

    def test_aux_spend_meters_at_aux_rate_end_to_end(self) -> None:
        result = calculate_token_cost(
            AUX_MODEL_NAME, input_tokens=100_000, output_tokens=2_000, cached_tokens=80_000
        )

        # Costs are rounded to 6dp by calculate_token_cost:
        # uncached input: (100000 - 80000) / 1000 * 0.00006426  = 0.0012852  -> 0.001285
        # cached input:   80000 / 1000 * 0.000012852            = 0.00102816 -> 0.001028
        # output:         2000 / 1000 * 0.00012852              = 0.00025704 -> 0.000257
        assert result["input_cost"] == pytest.approx(0.001285)
        assert result["cached_input_cost"] == pytest.approx(0.001028)
        assert result["output_cost"] == pytest.approx(0.000257)
        assert result["total_cost"] == pytest.approx(0.00257)


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
        """A provider reporting more cached than prompt tokens must not produce a
        negative uncached cost."""
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
