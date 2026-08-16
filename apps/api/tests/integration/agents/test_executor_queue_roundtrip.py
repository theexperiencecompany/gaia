"""What a queued or HIL-resumed executor run actually receives.

``test_executor_queue.py`` proves ``safe_configurable`` in isolation. This proves
the link that matters to a user: a run context written to Redis, read back, and
rebuilt through the real inheritance code still selects the same model lane and
still carries the turns the HIL intent judge grounds against.

Scope, stated plainly: this exercises the real JSON boundary (the same
``json.dumps``/``loads`` Redis performs) and the real ``build_agent_config``
inheritance. It does NOT boot Redis, the stream manager, or the executor graph —
``prepare_run_from_item``'s lock/stream/websocket machinery is covered by
``TestPopNextQueuedRun``, and the bug this pins never lived there. It lived in
the serialization allowlist and would have survived any amount of lock testing.
"""

import json

import pytest

from app.agents.core.background.executor_queue import build_run_item
from app.helpers.agent_helpers import build_agent_config
from app.models.agent_models import AgentConfigurable, agent_configurable


def _comms_configurable() -> AgentConfigurable:
    """A pro user's live comms configurable, mid-turn."""
    return {
        "thread_id": "conv-1",
        "conversation_id": "conv-1",
        "user_id": "u1",
        "email": "u1@example.com",
        "user_name": "Uno",
        "user_timezone": "Asia/Kolkata",
        "provider": "openrouter",
        "model": "deepseek/deepseek-v4-flash-0731",
        "model_name": "deepseek/deepseek-v4-flash-0731",
        "max_tokens": 1_000_000,
        "model_kwargs": {"provider": {"only": ["deepseek"]}},
        "reasoning": {"effort": "low"},
        "plan_type": "pro",
        "root_request_id": "root-req-1",
        "user_messages": ["draft an email to bob", "looks good, send it"],
        "langfuse_trace_id": "trace-1",
        "execution_mode": "interactive",
        "conversation_source": "web",
    }


def _redis_roundtrip(configurable: AgentConfigurable) -> AgentConfigurable:
    """Exactly what the queue does: serialize the item, store it, read it back."""
    item = build_run_item(
        task="send the email",
        task_id="task-1",
        configurable=configurable,
        conversation_id="conv-1",
        user_message_id="msg-1",
    )
    return json.loads(json.dumps(item))["configurable"]


@pytest.mark.integration
@pytest.mark.regression
class TestQueuedRunRebuild:
    def test_the_rebuilt_executor_keeps_the_provider_pin(self) -> None:
        """Without the pin the queued run load-balances off the first-party lane
        onto throttled resellers — a 429 on the user's second message only."""
        restored = _redis_roundtrip(_comms_configurable())

        executor = agent_configurable(
            build_agent_config(
                conversation_id="conv-1",
                user={"user_id": "u1"},
                agent_name="executor_agent",
                thread_id="executor_conv-1",
                base_configurable=restored,
            )
        )

        assert executor["model_kwargs"] == {"provider": {"only": ["deepseek"]}}

    def test_the_rebuilt_executor_keeps_the_users_verbatim_turns(self) -> None:
        """The HIL intent judge checks a gated tool call against what the USER
        asked. A resumed run that lost these judges against nothing."""
        restored = _redis_roundtrip(_comms_configurable())

        executor = agent_configurable(
            build_agent_config(
                conversation_id="conv-1",
                user={"user_id": "u1"},
                agent_name="executor_agent",
                thread_id="executor_conv-1",
                base_configurable=restored,
            )
        )

        assert executor["user_messages"] == ["draft an email to bob", "looks good, send it"]

    def test_the_rebuilt_executor_keeps_the_request_scoped_accounting_keys(self) -> None:
        """plan_type feeds the budget wall; root_request_id is what makes the
        per-request token ceiling bind across the whole agent tree instead of
        resetting on every hop."""
        restored = _redis_roundtrip(_comms_configurable())

        executor = agent_configurable(
            build_agent_config(
                conversation_id="conv-1",
                user={"user_id": "u1"},
                agent_name="executor_agent",
                thread_id="executor_conv-1",
                base_configurable=restored,
            )
        )

        assert executor["plan_type"] == "pro"
        assert executor["root_request_id"] == "root-req-1"
        assert executor["langfuse_trace_id"] == "trace-1"

    def test_the_rebuilt_run_selects_the_same_model_lane_as_the_original(self) -> None:
        original = _comms_configurable()

        restored = _redis_roundtrip(original)

        lane_keys = ("provider", "model_name", "model_kwargs", "reasoning")
        assert {k: restored.get(k) for k in lane_keys} == {k: original[k] for k in lane_keys}
