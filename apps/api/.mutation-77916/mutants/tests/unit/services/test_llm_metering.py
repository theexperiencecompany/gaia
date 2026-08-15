"""``record_llm_call`` — the single funnel every LLM charge passes through.

Reached only through ``LLMAccountingMiddleware`` in the existing tests, which
always fills in every counter, so the helper's own signature has never been
exercised: a caller that omits an optional counter is billed by whatever the
default happens to be, and a wrong default silently mis-books real money.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services import llm_metering
from app.services.llm_metering import record_llm_call

pytestmark = pytest.mark.unit

MODULE = "app.services.llm_metering"


@pytest.fixture
def usage() -> Any:
    with (
        patch.object(
            llm_metering,
            "calculate_token_cost",
            AsyncMock(return_value={"total_cost": 0.25}),
        ),
        patch.object(llm_metering, "record_model_call_usage", AsyncMock()) as recorded,
    ):
        yield recorded


class TestRecordLlmCall:
    async def test_the_priced_call_reaches_the_rollup_whole(self, usage: Any) -> None:
        cost = await record_llm_call(
            user_id="u1",
            model_name="deepseek/deepseek-v4-flash",
            input_tokens=100,
            output_tokens=20,
            cached_tokens=40,
            reasoning_tokens=7,
            root_request_id="req-1",
            charge_to_budget=True,
        )

        assert cost == 0.25
        usage.assert_awaited_once_with(
            "u1",
            0.25,
            "req-1",
            input_tokens=100,
            output_tokens=20,
            cached_tokens=40,
            reasoning_tokens=7,
            charge_to_budget=True,
        )

    async def test_an_unreported_reasoning_count_is_booked_as_none_of_it(self, usage: Any) -> None:
        # Most providers report no reasoning tokens at all, and those callers
        # omit the argument. Defaulting to anything but zero would invent
        # hidden-thinking usage for every one of them.
        await record_llm_call(
            user_id="u1",
            model_name="deepseek/deepseek-v4-flash",
            input_tokens=100,
            output_tokens=20,
            charge_to_budget=False,
        )

        assert usage.await_args.kwargs["reasoning_tokens"] == 0
        assert usage.await_args.kwargs["cached_tokens"] == 0
