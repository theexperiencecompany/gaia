"""Learned-skill induction: distill a reusable skill from an expensive run."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from app.agents.skills.models import SKILL_NAME_PATTERN
from app.agents.skills.skill_induction import (
    SkillCandidate,
    induce_skill_from_trajectory,
    maybe_persist_induced_skill,
)


def _call(name: str, args: dict, cid: str) -> dict:
    return {"name": name, "args": args, "id": cid, "type": "tool_call"}


def _trajectory(n_calls: int, *, include_scaffolding: bool = False, error_ids=()):
    """Build a message list with n_calls successful gmail_search tool calls."""
    msgs = [HumanMessage(content="find all my support requests")]
    if include_scaffolding:
        msgs += [
            AIMessage(content="", tool_calls=[_call("retrieve_tools", {"query": "gmail"}, "rt")]),
            ToolMessage(content="tools", tool_call_id="rt", name="retrieve_tools"),
        ]
    for i in range(n_calls):
        cid = f"c{i}"
        msgs.append(
            AIMessage(content="", tool_calls=[_call("gmail_search", {"query": f"q{i}"}, cid)])
        )
        msgs.append(
            ToolMessage(
                content="results",
                tool_call_id=cid,
                name="gmail_search",
                status="error" if cid in error_ids else "success",
            )
        )
    msgs.append(AIMessage(content="Found them."))
    return msgs


class TestInduction:
    def test_cheap_run_is_not_compiled(self):
        assert induce_skill_from_trajectory("find x", _trajectory(2), min_tool_calls=5) is None

    def test_expensive_run_yields_a_skill(self):
        cand = induce_skill_from_trajectory(
            "find all my support requests", _trajectory(6), min_tool_calls=5
        )
        assert isinstance(cand, SkillCandidate)
        assert SKILL_NAME_PATTERN.match(cand.name), f"invalid skill name: {cand.name!r}"
        assert "gmail_search" in cand.instructions
        assert "find all my support requests" in cand.instructions

    def test_scaffolding_calls_do_not_count_toward_cost(self):
        # 4 real calls + scaffolding: below threshold 5, so no skill even though
        # the raw tool-call count (incl. retrieve_tools) is 5.
        traj = _trajectory(4, include_scaffolding=True)
        assert induce_skill_from_trajectory("find x", traj, min_tool_calls=5) is None

    def test_failed_calls_do_not_count(self):
        # 6 calls but 2 errored -> 4 successful -> below threshold.
        traj = _trajectory(6, error_ids={"c0", "c1"})
        assert induce_skill_from_trajectory("find x", traj, min_tool_calls=5) is None

    def test_name_is_always_kebab_valid_even_for_messy_tasks(self):
        cand = induce_skill_from_trajectory(
            "  Find MY  support requests!!! (urgent)  ", _trajectory(6), min_tool_calls=5
        )
        assert SKILL_NAME_PATTERN.match(cand.name)


class TestPersist:
    async def test_persist_calls_installer_for_expensive_run(self):
        with patch(
            "app.agents.skills.installer.install_from_inline",
            new=AsyncMock(return_value=type("S", (), {"name": "find-support-requests"})()),
        ) as mock_install:
            name = await maybe_persist_induced_skill(
                "user-1", "find all my support requests", _trajectory(6), min_tool_calls=5
            )
        assert name == "find-support-requests"
        assert mock_install.call_args.kwargs["target"] == "executor"
        assert mock_install.call_args.kwargs["extra_metadata"]["source"] == "induced"

    async def test_persist_skips_cheap_run(self):
        with patch(
            "app.agents.skills.installer.install_from_inline", new=AsyncMock()
        ) as mock_install:
            name = await maybe_persist_induced_skill(
                "user-1", "find x", _trajectory(2), min_tool_calls=5
            )
        assert name is None
        mock_install.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
