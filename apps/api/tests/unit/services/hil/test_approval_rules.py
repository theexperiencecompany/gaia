"""set_approval_rule: the agent's way to change when a tool or a whole integration asks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import pytest

from app.constants import hil as hil_constants
from app.schemas.integrations.responses import IntegrationToolApproval
from app.services.hil import approval_rules
from app.utils.errors import AppError

pytestmark = pytest.mark.unit

MODULE = "app.services.hil.approval_rules"
USER = "u1"

NOTION = [
    IntegrationToolApproval(
        name="NOTION_CREATE_PAGE",
        description="",
        destructive=True,
        approval_key="NOTION_CREATE_PAGE",
    ),
    IntegrationToolApproval(
        name="NOTION_SEARCH", description="", destructive=False, approval_key="NOTION_SEARCH"
    ),
]


def _seams(tools: list[IntegrationToolApproval] = NOTION):
    return (
        patch(f"{MODULE}.get_integration_tool_list", new=AsyncMock(return_value=tools)),
        patch(f"{MODULE}.set_tool_override", new=AsyncMock()),
    )


class TestAWholeIntegration:
    async def test_dont_ask_stops_every_tool_asking_storing_only_what_differs(self) -> None:
        listed, written = _seams()
        with listed as tool_list, written as override:
            reply = await approval_rules.set_approval_rule(
                USER, rule=hil_constants.ApprovalRule.DONT_ASK, integration="notion"
            )
        tool_list.assert_awaited_once_with("notion")
        assert override.await_args_list == [
            call(USER, "NOTION_CREATE_PAGE", False),
            # Already runs without asking by default, so no rule is stored.
            call(USER, "NOTION_SEARCH", None),
        ]
        assert "notion" in reply and "2" in reply

    async def test_ask_makes_every_tool_ask(self) -> None:
        listed, written = _seams()
        with listed, written as override:
            await approval_rules.set_approval_rule(
                USER, rule=hil_constants.ApprovalRule.ASK, integration="notion"
            )
        assert override.await_args_list == [
            call(USER, "NOTION_CREATE_PAGE", None),
            call(USER, "NOTION_SEARCH", True),
        ]

    async def test_default_clears_every_rule(self) -> None:
        listed, written = _seams()
        with listed, written as override:
            await approval_rules.set_approval_rule(
                USER, rule=hil_constants.ApprovalRule.DEFAULT, integration="notion"
            )
        assert [c.args[2] for c in override.await_args_list] == [None, None]

    async def test_an_integration_with_no_tools_writes_nothing(self) -> None:
        listed, written = _seams([])
        with listed, written as override, pytest.raises(AppError):
            await approval_rules.set_approval_rule(
                USER, rule=hil_constants.ApprovalRule.DONT_ASK, integration="nope"
            )
        override.assert_not_awaited()


class TestOneTool:
    async def test_a_rule_lands_under_the_tools_approval_key(self) -> None:
        meta = SimpleNamespace(
            name="GMAIL_SEND_EMAIL", tool=SimpleNamespace(metadata={}), destructive=True
        )
        registry = SimpleNamespace(
            get_tool_meta=lambda name: meta if name == "GMAIL_SEND_EMAIL" else None
        )
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(f"{MODULE}.set_tool_override", new=AsyncMock()) as override,
        ):
            await approval_rules.set_approval_rule(
                USER, rule=hil_constants.ApprovalRule.DONT_ASK, tool="GMAIL_SEND_EMAIL"
            )
        override.assert_awaited_once_with(USER, "GMAIL_SEND_EMAIL", False)

    async def test_an_unknown_tool_writes_nothing(self) -> None:
        registry = SimpleNamespace(get_tool_meta=lambda name: None)
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(f"{MODULE}.set_tool_override", new=AsyncMock()) as override,
            pytest.raises(AppError),
        ):
            await approval_rules.set_approval_rule(
                USER, rule=hil_constants.ApprovalRule.DONT_ASK, tool="NOPE"
            )
        override.assert_not_awaited()

    @pytest.mark.parametrize("name", ["set_approval_rule", "update_user_instructions"])
    async def test_a_tool_that_always_asks_refuses_any_rule(self, name: str) -> None:
        """Saying "never ask" to these would be a no-op the user believes worked."""
        with (
            patch(f"{MODULE}.set_tool_override", new=AsyncMock()) as override,
            pytest.raises(AppError),
        ):
            await approval_rules.set_approval_rule(
                USER, rule=hil_constants.ApprovalRule.DONT_ASK, tool=name
            )
        override.assert_not_awaited()


@pytest.mark.parametrize(
    "target", [{}, {"integration": "notion", "tool": "NOTION_SEARCH"}], ids=["neither", "both"]
)
async def test_exactly_one_target_is_named(target: dict[str, str]) -> None:
    with (
        patch(f"{MODULE}.set_tool_override", new=AsyncMock()) as override,
        pytest.raises(AppError),
    ):
        await approval_rules.set_approval_rule(USER, rule=hil_constants.ApprovalRule.ASK, **target)
    override.assert_not_awaited()


def test_the_rule_tool_itself_always_asks() -> None:
    """Otherwise text in an email could tell the agent to switch its own approvals off."""
    assert "set_approval_rule" in hil_constants.ALWAYS_ASK_TOOLS
