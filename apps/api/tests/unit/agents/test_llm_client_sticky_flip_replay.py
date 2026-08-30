"""The sticky-flip replay's discarded invocation, and who pays for it.

``ainvoke_llm`` re-sends a graph call whose prompt cache came back cold, keeps
the FIRST answer (the one that streamed to the user) and throws the replay's
away. The discarded invocation never lands in graph state, so
``LLMAccountingMiddleware`` — which meters from the state message — can never
see it, while the provider billed it all the same. These pin who accounts for
that invocation on each lane.

Split out of ``test_llm_client.py`` deliberately: the regression test here must
COLLECT *and RUN* against the base revision for the ``regression-proof`` lane to
prove anything, and that file imports symbols this branch introduces
(``ainvoke_structured_gemini``, ``AUX_MODEL_NAME``), so importing it on base
aborts during collection. Everything below imports only what base already has;
the one knob whose spelling this branch changed is resolved from the signature
in front of us (see ``invoke_kwargs``) so the assertions actually run on both
revisions.
"""

from collections.abc import Callable
import inspect
from typing import Any
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


@pytest.fixture(name="invoke_kwargs")
def _invoke_kwargs() -> Callable[..., dict[str, Any]]:
    """Spell the ``ainvoke_llm`` knobs the way the revision under test takes
    them, resolved when a test RUNS rather than when this file is imported.

    The regression-proof lane runs this file's marked test against the BASE
    revision and demands a real assertion failure there: an ERROR (a missing
    fixture, an import of a symbol the fix introduces) is explicitly rejected
    as proof, because the test never reached its assertions. This branch moved
    those knobs from loose keywords into an ``LLMInvokeOptions`` dataclass it
    introduces, so hard-coding either spelling makes the test unrunnable on one
    of the two revisions — and importing the dataclass at module (or fixture)
    scope turns base collection into exactly the ERROR the lane rejects.

    So the shape is chosen from the signature actually in front of us. On this
    branch that yields ``options=LLMInvokeOptions(...)``; on base, the loose
    ``meter_auxiliary=...`` keyword. Either way the call goes through and the
    assertions run, which is what makes the base result proof about the bug
    rather than proof that the harness broke.
    """

    def build(**knobs: Any) -> dict[str, Any]:
        if "options" in inspect.signature(ainvoke_llm).parameters:
            from app.agents.llm.client import LLMInvokeOptions

            return {"options": LLMInvokeOptions(**knobs)}
        return knobs

    return build


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
    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_discarded_first_invocation_is_metered_as_background_cogs(
        self,
        mock_record: AsyncMock,
        mock_log: MagicMock,
        invoke_kwargs: Callable[..., dict[str, Any]],
    ) -> None:
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
            **invoke_kwargs(meter_auxiliary=False),
        )

        # The first answer is what streamed to the user, so it is what the turn
        # returns and persists; the replay only warms the provider's chain.
        assert result.content == "cold"
        mock_record.assert_awaited_once()
        charged = mock_record.await_args.kwargs
        # The DISCARDED invocation is the one being paid for: it is the replay,
        # which is the call that came back warm.
        assert charged["usage"]["cached_tokens"] == 9_900
        assert charged["usage"]["input_tokens"] == 10_000
        assert charged["user_id"] == "u1"
        # Priced against what the provider reported serving, not what the run
        # asked for — a fallback bills the model that actually answered.
        assert charged["model_name"] == "served/model"
        # The bug this pins: the replay is a cache-warming re-send GAIA chose to
        # make, whose answer the user never received. Charging it made the
        # user's daily allowance pay for a discarded reply (3,614 of them,
        # $34.55, ~20% of all LLM spend over 2026-08-16..29). It is recorded
        # durably as auxiliary COGS instead.
        assert charged["charge_to_budget"] is False
        # And it carries no root_request_id: that counter is the per-request
        # token ceiling bounding one agent tree against runaway loops. Our own
        # re-send is not the model looping, and letting it count lets a turn be
        # truncated by the optimisation meant to make it cheaper.
        assert charged["root_request_id"] is None

        # The wide event has to agree, or COGS dashboards and the true-cost
        # backfill still read the replay as the user's foreground spend.
        event = mock_log.info.call_args.kwargs
        assert mock_log.info.call_args.args == ("llm_call",)
        assert event["sticky_flip_discarded"] is True
        assert event["background"] is True
        assert event["cost_usd"] == 0.004

    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_no_replay_means_no_extra_metering(
        self, mock_record: AsyncMock, invoke_kwargs: Callable[..., dict[str, Any]]
    ) -> None:
        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(
            return_value=_usage_message("warm", prompt=10_000, cached=9_900)
        )
        await ainvoke_llm(
            runnable, [HumanMessage(content="hi")], **invoke_kwargs(meter_auxiliary=False)
        )

        assert runnable.ainvoke.await_count == 1
        mock_record.assert_not_awaited()

    @staticmethod
    def _primary_answering_with_hit(cached: int) -> NonCallableMagicMock:
        """A primary whose FIRST answer reports ``cached`` of 10,000 prompt
        tokens read from the provider's cache — the only number the replay gate
        looks at."""
        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(
            side_effect=[
                _usage_message("first", prompt=10_000, cached=cached),
                _usage_message("replay", prompt=10_000, cached=9_900),
            ]
        )
        return runnable

    @pytest.mark.regression
    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_a_reported_85_percent_hit_is_the_steady_state_and_does_not_replay(
        self, mock_record: AsyncMock, invoke_kwargs: Callable[..., dict[str, Any]]
    ) -> None:
        """83-90% is a provider under-REPORTING a chain it already holds, not a
        request that landed on a cold upstream.

        There is nothing to re-warm there, so the re-send buys a second full
        request and no saving — and that band is the bulk of the 3,614 replays
        / $34.55 measured over 2026-08-16..29. The old 0.92 floor swept it in.
        """
        primary = self._primary_answering_with_hit(8_500)

        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config={"configurable": {"provider": "openrouter"}},
            **invoke_kwargs(meter_auxiliary=False),
        )

        assert primary.ainvoke.await_count == 1
        mock_record.assert_not_awaited()

    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_a_reported_75_percent_hit_is_a_real_flip_and_still_replays(
        self, mock_record: AsyncMock, invoke_kwargs: Callable[..., dict[str, Any]]
    ) -> None:
        """The partial static-only dip (65-75%) IS a flip — the floor has to
        stay below it, or lowering the threshold would silently switch the
        optimisation off for the shape it exists to catch."""
        primary = self._primary_answering_with_hit(7_500)

        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config={"configurable": {"provider": "openrouter"}},
            **invoke_kwargs(meter_auxiliary=False),
        )

        assert primary.ainvoke.await_count == 2
        mock_record.assert_awaited_once()

    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_auxiliary_lane_never_replays(
        self, mock_record: AsyncMock, invoke_kwargs: Callable[..., dict[str, Any]]
    ) -> None:
        """A one-shot helper call has no prior chain — cold IS its steady
        state, so a replay is pure double billing."""
        primary = self._flipping_primary()

        await ainvoke_llm(
            primary, [HumanMessage(content="hi")], **invoke_kwargs(meter_auxiliary=True)
        )

        assert primary.ainvoke.await_count == 1
        mock_record.assert_not_awaited()

    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_gemini_lane_never_replays(
        self, mock_record: AsyncMock, invoke_kwargs: Callable[..., dict[str, Any]]
    ) -> None:
        """No sticky routing on Gemini: a replay there is a second full-price
        call with no possible upside."""
        primary = self._flipping_primary()

        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config={"configurable": {"provider": "gemini"}},
            **invoke_kwargs(meter_auxiliary=False),
        )

        assert primary.ainvoke.await_count == 1
        mock_record.assert_not_awaited()

    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_replay_is_silenced_so_it_never_streams_to_the_user(
        self, mock_record: AsyncMock, invoke_kwargs: Callable[..., dict[str, Any]]
    ) -> None:
        """Graph providers stream; without the silent stamp both invocations'
        tokens land in one SSE stream and the user sees two answers."""
        mock_record.return_value = 0.0
        primary = self._flipping_primary()

        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config={"configurable": {"provider": "openrouter"}},
            **invoke_kwargs(meter_auxiliary=False),
        )

        first_cfg = primary.ainvoke.await_args_list[0].kwargs["config"]
        replay_cfg = primary.ainvoke.await_args_list[1].kwargs["config"]
        assert not (first_cfg.get("metadata") or {}).get("silent")
        assert replay_cfg["metadata"]["silent"] is True

    @patch("app.agents.llm.client.record_llm_call", new_callable=AsyncMock)
    async def test_a_failed_replay_keeps_the_first_response(
        self, mock_record: AsyncMock, invoke_kwargs: Callable[..., dict[str, Any]]
    ) -> None:
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
            **invoke_kwargs(meter_auxiliary=False),
        )

        assert result.content == "cold"
        mock_record.assert_not_awaited()  # nothing was discarded
