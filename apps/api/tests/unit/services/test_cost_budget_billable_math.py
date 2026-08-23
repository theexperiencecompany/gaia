"""Direct pins on the ceiling's arithmetic helpers.

Pure functions, so these kill their mutants deterministically instead of
relying on end-to-end selection. Kept in their own module so the metering
suite imports nothing that is absent on older bases (regression-proof runs
changed files' collections against the merge base).
"""

import pytest

from app.services.cost_budget import _billable_request_tokens, _is_charged_spend


@pytest.mark.unit
class TestBillableTokenMath:
    def test_cache_hits_ride_free_and_output_counts(self) -> None:
        assert (
            _billable_request_tokens(input_tokens=1000, cached_tokens=900, output_tokens=100) == 200
        )

    def test_fully_cached_call_with_no_output_bills_nothing(self) -> None:
        assert _billable_request_tokens(input_tokens=1000, cached_tokens=1000, output_tokens=0) == 0

    def test_negative_uncached_input_clamps_to_zero(self) -> None:
        assert _billable_request_tokens(input_tokens=100, cached_tokens=500, output_tokens=50) == 50

    def test_charged_spend_needs_a_user_and_a_cost(self) -> None:
        assert _is_charged_spend("u", 0.01) is True
        assert _is_charged_spend(None, 0.01) is False
        assert _is_charged_spend("u", 0.0) is False
