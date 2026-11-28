"""Connector calls: reads never ask, each write command type asks until the user always-allows it."""

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.connectors import RUN_CONNECTOR_TOOL
from app.constants.execute import EXECUTE_TOOL_NAME
from app.models.hil_models import HILMode, HILPreferences
from app.models.integration_models import Integration
from app.services.hil.describe import describe_call
from app.services.hil.policy import gated_tool_key, resolve_policy
from app.services.hil.when import UserClock
from app.utils.timezone import Timezone
from tests.factories import make_connector_spec

from .conftest import USER_ID, make_request

CONNECTOR_ID = "c0ffee00-0000-4000-8000-000000000001"
RISK_MODULE = "app.services.hil.connector_risk"
POLICY_MODULE = "app.services.hil.policy"


def _gh_doc() -> Integration:
    return Integration(
        integration_id=CONNECTOR_ID,
        name="GitHub CLI",
        description="",
        category="developer",
        managed_by="connector",
        created_by=USER_ID,
        connector_config=make_connector_spec("cli"),
        display_priority=0,
        is_featured=False,
        published_at=None,
        clone_count=0,
    )


def _call(args: list[str]):
    return make_request(
        name=EXECUTE_TOOL_NAME,
        args={
            "tool_name": RUN_CONNECTOR_TOOL,
            "data": {"connector_id": CONNECTOR_ID, "argv": args},
        },
    )


@pytest.fixture(autouse=True)
def _connector_exists():
    with (
        patch(
            f"{RISK_MODULE}.load_connector",
            AsyncMock(return_value=(_gh_doc(), make_connector_spec("cli"))),
        ),
        patch(f"{POLICY_MODULE}.log"),
    ):
        yield


def _prefs(mode: HILMode, **overrides: bool) -> AsyncMock:
    return AsyncMock(return_value=HILPreferences(mode=mode, tool_overrides=overrides))


@pytest.mark.parametrize("mode", ["always_ask", "auto", "always_allow"])
async def test_a_read_never_asks_in_any_mode(mode: HILMode) -> None:
    with patch(f"{POLICY_MODULE}.get_hil_preferences", _prefs(mode)):
        assert await resolve_policy(_call(["api", "user"]), USER_ID, RUN_CONNECTOR_TOOL) == "allow"


@pytest.mark.parametrize("mode", ["always_ask", "auto"])
async def test_a_write_asks_and_is_never_left_to_the_intent_judge(mode: HILMode) -> None:
    with patch(f"{POLICY_MODULE}.get_hil_preferences", _prefs(mode)):
        policy = await resolve_policy(
            _call(["pr", "create", "-t", "x"]), USER_ID, RUN_CONNECTOR_TOOL
        )

    assert policy == "ask"


async def test_always_allow_covers_only_that_command_type_on_that_connector() -> None:
    allowed = {f"connector:{CONNECTOR_ID}:pr create": False}
    with patch(f"{POLICY_MODULE}.get_hil_preferences", _prefs("auto", **allowed)):
        same = await resolve_policy(_call(["pr", "create"]), USER_ID, RUN_CONNECTOR_TOOL)
        other = await resolve_policy(_call(["repo", "delete", "o/r"]), USER_ID, RUN_CONNECTOR_TOOL)

    assert (same, other) == ("allow", "ask")


async def test_a_write_flag_turns_a_listed_read_into_an_asking_write() -> None:
    with patch(f"{POLICY_MODULE}.get_hil_preferences", _prefs("always_ask")):
        policy = await resolve_policy(
            _call(["api", "/repos/o/r/issues", "-X", "POST"]), USER_ID, RUN_CONNECTOR_TOOL
        )

    assert policy == "ask"


async def test_the_remembered_key_names_the_connector_and_command_type() -> None:
    key = await gated_tool_key(_call(["pr", "create"]), USER_ID, RUN_CONNECTOR_TOOL)

    assert key == f"connector:{CONNECTOR_ID}:pr create"


def test_the_approval_card_names_the_command_and_the_connector() -> None:
    description = describe_call(
        RUN_CONNECTOR_TOOL,
        {"connector_id": CONNECTOR_ID, "argv": ["POST", "/audiences", "--json", "{}"]},
        "Resend",
        clock=UserClock.current(Timezone.parse("UTC")),
    )

    assert description.headline == "Run POST /audiences --json {} on Resend"
    assert description.question.endswith("run POST /audiences --json {} on Resend?")
