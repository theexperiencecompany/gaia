"""The sticky-flip replay's discarded first invocation, and who pays for it.

``ainvoke_llm`` re-sends a graph call whose prompt cache came back cold and
RETURNS the replay. The first invocation never lands in graph state, so
``LLMAccountingMiddleware`` — which meters from the state message — can never
see it, while the provider billed it all the same. These pin who accounts for
that invocation on each lane.

Split out of ``test_llm_client.py`` deliberately: the regression test here must
COLLECT against the base revision for the ``regression-proof`` lane to prove
anything, and that file imports symbols this branch introduces
(``ainvoke_structured_gemini``, ``AUX_MODEL_NAME``), so importing it on base
aborts during collection. Everything below imports only what base already has.
"""

from unittest.mock import AsyncMock, MagicMock, NonCallableMagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
import pytest

from app.agents.llm.client import ainvoke_llm


def _usage_message(content: str, *, prompt: int, cached: int) -> AIMessage:
    return AIMessage(
        content=content,
        usage_metadata={
            "input_tokens": prompt,
            "output_tokens": 5,
            "total_tokens": prompt + 5,
            "input_token_details": {"cache_read": cached},
        },
    )


class TestStickyFlipReplayAccounting:
    """When a graph call's prompt cache misses, ``ainvoke_llm`` re-sends and
    RETURNS the replay — the first invocation never lands in graph state, so
    ``LLMAccountingMiddleware`` (which meters from the state message) can never
    see it. The provider billed it, so ``ainvoke_llm`` meters it itself."""

    @staticmethod
    def _flipping_primary() -> NonCallableMagicMock:
        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(
            side_effect=[
                _usage_message("cold", prompt=10_000, cached=0),
                _usage_message("warm", prompt=10_000, cached=9_900),
            ]
        )
        return runnable

    @pytest.mark.regression
    @patch("app.agents.llm.client.record_graph_model_call", new_callable=AsyncMock)
    async def test_discarded_first_invocation_is_metered(self, mock_record: AsyncMock) -> None:
        mock_record.return_value = (
            {
                "input_tokens": 10_000,
                "output_tokens": 5,
                "cached_tokens": 0,
                "reasoning_tokens": 0,
            },
            0.004,
        )
        primary = self._flipping_primary()

        result = await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config={"configurable": {"user_id": "u1", "model_name": "m", "root_request_id": "r1"}},
            meter_auxiliary=False,
        )

        assert result.content == "warm"
        mock_record.assert_awaited_once()
        metered_message, configurable = mock_record.await_args.args
        assert metered_message.content == "cold"
        assert configurable["root_request_id"] == "r1"

    @patch("app.agents.llm.client.record_graph_model_call", new_callable=AsyncMock)
    async def test_no_replay_means_no_extra_metering(self, mock_record: AsyncMock) -> None:
        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(
            return_value=_usage_message("warm", prompt=10_000, cached=9_900)
        )

        await ainvoke_llm(runnable, [HumanMessage(content="hi")], meter_auxiliary=False)

        assert runnable.ainvoke.await_count == 1
        mock_record.assert_not_awaited()

    @patch("app.agents.llm.client.record_graph_model_call", new_callable=AsyncMock)
    async def test_auxiliary_lane_is_left_to_its_usage_handler(
        self, mock_record: AsyncMock
    ) -> None:
        """``UsageMetadataCallbackHandler`` sums BOTH invocations, so metering
        the discarded one here too would double-bill auxiliary COGS."""
        primary = self._flipping_primary()

        await ainvoke_llm(primary, [HumanMessage(content="hi")], meter_auxiliary=True)

        assert primary.ainvoke.await_count == 2
        mock_record.assert_not_awaited()
