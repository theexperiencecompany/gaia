"""The sticky-flip replay's discarded invocation, and who pays for it.

``ainvoke_llm`` re-sends a graph call whose prompt cache came back cold, keeps
the FIRST answer (the one that streamed to the user) and throws the replay's
away. The discarded invocation never lands in graph state, so
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
        response_metadata={"model_name": "served/model"},
        usage_metadata={
            "input_tokens": prompt,
            "output_tokens": 5,
            "total_tokens": prompt + 5,
            "input_token_details": {"cache_read": cached},
        },
    )


class TestStickyFlipReplayAccounting:
    """When a graph call's prompt cache misses, ``ainvoke_llm`` re-sends to warm
    the provider's chain and DISCARDS the replay's answer — the first answer is
    the one the user watched stream, so it is the one returned. The discarded
    invocation never lands in graph state, so ``LLMAccountingMiddleware`` (which
    meters from the state message) can never see it. The provider billed it, so
    ``ainvoke_llm`` meters it itself."""

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
    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_discarded_first_invocation_is_metered(self, mock_record: AsyncMock) -> None:
        mock_record.return_value = 0.004
        primary = self._flipping_primary()

        result = await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config={
                "configurable": {
                    "user_id": "u1",
                    "provider": "openrouter",
                    "root_request_id": "r1",
                }
            },
            label="comms_agent",
            meter_auxiliary=False,
        )

        # The first answer is what streamed to the user, so it is what the turn
        # returns and persists; the replay only warms the provider's chain.
        assert result.content == "cold"
        mock_record.assert_awaited_once()
        charged = mock_record.await_args.kwargs
        # The DISCARDED invocation is the one being paid for: it is the replay,
        # which is the call that came back warm.
        assert charged["cached_tokens"] == 9_900
        assert charged["input_tokens"] == 10_000
        assert charged["root_request_id"] == "r1"
        assert charged["user_id"] == "u1"
        # Priced against what the provider reported serving, not what the run
        # asked for — a fallback bills the model that actually answered.
        assert charged["model_name"] == "served/model"
        assert charged["charge_to_budget"] is True

    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_no_replay_means_no_extra_metering(self, mock_record: AsyncMock) -> None:
        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(
            return_value=_usage_message("warm", prompt=10_000, cached=9_900)
        )

        await ainvoke_llm(runnable, [HumanMessage(content="hi")], meter_auxiliary=False)

        assert runnable.ainvoke.await_count == 1
        mock_record.assert_not_awaited()

    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_auxiliary_lane_never_replays(self, mock_record: AsyncMock) -> None:
        """A one-shot helper call has no prior chain — cold IS its steady
        state, so a replay is pure double billing."""
        primary = self._flipping_primary()

        await ainvoke_llm(primary, [HumanMessage(content="hi")], meter_auxiliary=True)

        assert primary.ainvoke.await_count == 1
        mock_record.assert_not_awaited()

    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_gemini_lane_never_replays(self, mock_record: AsyncMock) -> None:
        """No sticky routing on Gemini: a replay there is a second full-price
        call with no possible upside."""
        primary = self._flipping_primary()

        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config={"configurable": {"provider": "gemini"}},
            meter_auxiliary=False,
        )

        assert primary.ainvoke.await_count == 1
        mock_record.assert_not_awaited()

    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_replay_is_silenced_so_it_never_streams_to_the_user(
        self, mock_record: AsyncMock
    ) -> None:
        """Graph providers stream; without the silent stamp both invocations'
        tokens land in one SSE stream and the user sees two answers."""
        mock_record.return_value = 0.0
        primary = self._flipping_primary()

        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config={"configurable": {"provider": "openrouter"}},
            meter_auxiliary=False,
        )

        first_cfg = primary.ainvoke.await_args_list[0].kwargs["config"]
        replay_cfg = primary.ainvoke.await_args_list[1].kwargs["config"]
        assert not (first_cfg.get("metadata") or {}).get("silent")
        assert replay_cfg["metadata"]["silent"] is True

    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_a_failed_replay_keeps_the_first_response(self, mock_record: AsyncMock) -> None:
        """The first answer is complete and in hand — a 429 on the re-send
        must never cost the turn (or trigger a third, fallback call)."""
        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(
            side_effect=[
                _usage_message("cold", prompt=10_000, cached=0),
                RuntimeError("429 on the re-send"),
            ]
        )

        result = await ainvoke_llm(
            runnable,
            [HumanMessage(content="hi")],
            config={"configurable": {"provider": "openrouter"}},
            meter_auxiliary=False,
        )

        assert result.content == "cold"
        mock_record.assert_not_awaited()  # nothing was discarded
