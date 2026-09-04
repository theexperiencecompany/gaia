"""Provider subagents can never spawn sub-subagents — structurally, not by
caller discipline. The executor keeps spawn_subagent; the tool must simply not
exist one tier down, whatever options a caller passes."""

from unittest.mock import MagicMock

import pytest

from app.agents.middleware import (
    SubagentMiddleware,
    SubagentStackOptions,
    create_subagent_middleware,
)


@pytest.mark.unit
class TestSubagentCannotSpawn:
    def test_the_spawn_middleware_is_absent_even_when_a_caller_asks_for_it(self) -> None:
        stack = create_subagent_middleware(
            agent_name="gmail_agent",
            subagent=SubagentStackOptions(
                enabled=True,  # a future caller regression, not a legal request
                registry={"read": MagicMock()},
                tool_space="gmail",
            ),
        )
        assert not any(isinstance(mw, SubagentMiddleware) for mw in stack)
