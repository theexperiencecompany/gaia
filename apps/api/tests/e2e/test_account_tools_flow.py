"""E2E: the account-center surface wired into a REAL compiled GAIA graph.

WHAT THIS TESTS (REAL GAIA CODE):
- The five account mutation tools exactly as registered for the executor.
- The real ``create_agent`` graph (bigtool) dispatching LLM tool calls into
  them, with config threading (user_id) intact end to end.
- The real global ToolRegistry stamps: the settings tools carry
  ``always_gate`` and ``manage_linked_account`` does not — plus the REAL
  ``resolve_policy`` returning ``ask`` for them under an ``always_allow`` user.
- The write tool refusing ``account/**`` paths inside a graph turn, naming the
  owning mutation tool, without touching the sandbox.

Mock surfaces:
- LLM: BindableToolsFakeModel (scripted AIMessages)
- Store/Checkpointer: in-memory
- Repository/service seams (Mongo, ElevenLabs, platform links): patched at the
  boundary the tools own

DELETE ``app/agents/tools/account_tools.py`` → these tests FAIL.
DELETE ``app/agents/tools/core/mutations.py`` → these tests FAIL.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from app.agents.tools import account_tools
from app.agents.tools.account_tools import tools as account_tool_list
from app.agents.tools.coding.write_tool import write
from app.core.lazy_loader import providers
from app.db.repositories.users import user_repository
from app.models.hil_models import HILPreferences
from app.services import account_settings
from app.services.analytics_service import AnalyticsEvents
from app.services.hil.policy import resolve_policy
from app.services.hil.utils import unpack_tool_call
from tests.e2e.conftest import build_gaia_test_graph
from tests.helpers import BindableToolsFakeModel

pytestmark = pytest.mark.e2e

TOOLS_BY_NAME = {t.name: t for t in account_tool_list}


def _tool_messages(messages: list) -> list[ToolMessage]:
    return [m for m in messages if isinstance(m, ToolMessage)]


def _graph_with(fake_llm, extra_tools=(), **patches):
    """Compile the real GAIA graph with the account tools bound."""
    return build_gaia_test_graph(
        fake_llm=fake_llm,
        tool_registry={
            name: TOOLS_BY_NAME[name]
            for name in (
                "update_notification_settings",
                "update_preferences",
                "update_custom_instructions",
                "set_selected_voice",
                "manage_linked_account",
            )
        }
        | {t.name: t for t in extra_tools},
    )


@pytest.fixture
def _patched_seams():
    """The repo/service boundaries behind every account tool."""

    with (
        patch.object(user_repository, "set_channel_preferences", new=AsyncMock()) as set_channels,
        patch.object(
            user_repository, "update_onboarding_preferences", new=AsyncMock(return_value=object())
        ) as update_prefs,
        patch.object(user_repository, "update", new=AsyncMock(return_value=object())) as update,
        patch.object(account_settings, "list_voices", new=AsyncMock()) as list_voices,
        patch.object(account_settings, "set_user_voice", new=AsyncMock()) as set_user_voice,
        patch(f"{account_tools.__name__}.schedule_account_sync") as resync,
        patch("app.agents.tools.core.mutations.capture_context_event") as capture,
        patch(f"{account_tools.__name__}.enforce_rate_limit", new=AsyncMock()),
    ):
        yield SimpleNamespace(
            set_channels=set_channels,
            update_prefs=update_prefs,
            update=update,
            list_voices=list_voices,
            set_user_voice=set_user_voice,
            resync=resync,
            capture=capture,
        )


class TestAccountToolsThroughGraph:
    async def test_update_notification_settings_lands_in_the_repo(
        self, thread_config, memory_saver, in_memory_store, _patched_seams
    ):
        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "update_notification_settings",
                            "args": {"email": False},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Email notifications are off."),
            ]
        )
        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={
                "update_notification_settings": TOOLS_BY_NAME["update_notification_settings"]
            },
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="turn off email notifications")]},
            config=thread_config,
        )

        [tool_msg] = _tool_messages(result["messages"])
        assert "Notification settings updated" in tool_msg.content
        assert "email=off" in tool_msg.content
        # The write went to THIS graph's user, not another tenant's.
        _patched_seams.set_channels.assert_awaited_once_with(
            thread_config["configurable"]["user_id"], email=False
        )
        # Analytics only after success.
        _patched_seams.capture.assert_called_once_with(
            AnalyticsEvents.ACCOUNT_SETTING_CHANGED, {"area": "notifications"}
        )
        # NOTE: the projection resync is bound into the tool at import time
        # (factory kwarg), so it cannot be observed through a module patch here;
        # the resync-on-success contract is proven against real probes in
        # tests/unit/agents/tools/test_mutations_factory.py.

    async def test_set_selected_voice_resolves_name_and_persists_id(
        self, thread_config, memory_saver, in_memory_store, _patched_seams
    ):
        voice = SimpleNamespace(voice_id="v-9", name="Rachel", starred=False)
        _patched_seams.list_voices.return_value = SimpleNamespace(
            voices=[voice], selected_voice_id=None
        )
        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c2",
                            "name": "set_selected_voice",
                            "args": {"voice": "rachel"},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Voice switched."),
            ]
        )
        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={"set_selected_voice": TOOLS_BY_NAME["set_selected_voice"]},
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="switch my voice to Rachel")]},
            config=thread_config,
        )

        [tool_msg] = _tool_messages(result["messages"])
        assert "Rachel" in tool_msg.content
        _patched_seams.set_user_voice.assert_awaited_once_with(
            thread_config["configurable"]["user_id"], "v-9"
        )

    async def test_invalid_input_reaches_the_model_as_an_error_string_not_a_crash(
        self, thread_config, memory_saver, in_memory_store, _patched_seams
    ):
        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c3",
                            "name": "update_custom_instructions",
                            "args": {"instructions": "x" * 501},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Sorry, that was too long."),
            ]
        )
        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={
                "update_custom_instructions": TOOLS_BY_NAME["update_custom_instructions"]
            },
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="remember this: ...")]},
            config=thread_config,
        )

        [tool_msg] = _tool_messages(result["messages"])
        assert tool_msg.content.startswith("Error:")
        assert "500 characters" in tool_msg.content
        _patched_seams.update_prefs.assert_not_awaited()

    async def test_manage_linked_account_generate_link_returns_connect_instructions(
        self, thread_config, memory_saver, in_memory_store, _patched_seams
    ):
        flow = SimpleNamespace(
            auth_url=None,
            instructions="Open Telegram and message @gaia_bot with /auth",
            action_link="https://t.me/gaia_bot",
        )
        with patch(
            f"{account_tools.__name__}.start_platform_connect", new=AsyncMock(return_value=flow)
        ):
            fake_llm = BindableToolsFakeModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "c4",
                                "name": "manage_linked_account",
                                "args": {"platform": "telegram", "action": "generate_link"},
                                "type": "tool_call",
                            }
                        ],
                    ),
                    AIMessage(content="Here's your link."),
                ]
            )
            graph = build_gaia_test_graph(
                fake_llm=fake_llm,
                tool_registry={"manage_linked_account": TOOLS_BY_NAME["manage_linked_account"]},
            )

            result = await graph.ainvoke(
                {"messages": [HumanMessage(content="connect telegram")]},
                config=thread_config,
            )

        [tool_msg] = _tool_messages(result["messages"])
        assert "@gaia_bot" in tool_msg.content
        assert "https://t.me/gaia_bot" in tool_msg.content
        # Minting a link is NOT a setting change: no event, but still resyncs.
        _patched_seams.capture.assert_not_called()


class TestHILWiring:
    def test_settings_tools_are_stamped_always_gate_and_link_is_not(self, real_tool_registry):
        async def grab():
            return await providers.aget("tool_registry")

        registry = asyncio.run(grab())
        meta = registry.get_tool_meta("update_notification_settings")
        assert meta is not None and meta.always_gate is True
        for name in ("update_preferences", "update_custom_instructions", "set_selected_voice"):
            assert registry.get_tool_meta(name).always_gate is True, name
        link_meta = registry.get_tool_meta("manage_linked_account")
        assert link_meta is not None and link_meta.always_gate is False

    async def test_resolve_policy_asks_for_settings_even_when_hil_is_off(self, real_tool_registry):
        request = SimpleNamespace(
            tool_call={"id": "c1", "name": "update_preferences", "args": {"timezone": "UTC"}},
            state={"messages": []},
        )
        call = unpack_tool_call(request)
        with patch(
            "app.services.hil.policy._preferences",
            new=AsyncMock(return_value=HILPreferences(mode="always_allow")),
        ):
            policy = await resolve_policy(request, "user-1", call.name)

        assert policy == "ask"


class TestWriteRefusalJourney:
    async def test_write_to_account_path_refuses_inside_a_graph_turn(
        self, thread_config, memory_saver, in_memory_store
    ):
        sandbox = MagicMock()
        sandbox.__aenter__ = AsyncMock(side_effect=AssertionError("sandbox must not open"))
        with patch("app.agents.tools.coding.write_tool.acquire_sandbox", return_value=sandbox):
            fake_llm = BindableToolsFakeModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "c5",
                                "name": "write",
                                "args": {
                                    "path": "/workspace/account/preferences.json",
                                    "content": "{}",
                                },
                                "type": "tool_call",
                            }
                        ],
                    ),
                    AIMessage(content="I can't edit that directly."),
                ]
            )
            graph = build_gaia_test_graph(fake_llm=fake_llm, tool_registry={"write": write})

            result = await graph.ainvoke(
                {"messages": [HumanMessage(content="edit your preferences file")]},
                config=thread_config,
            )

        [tool_msg] = _tool_messages(result["messages"])
        assert "read-only projection" in tool_msg.content
        assert "update_preferences" in tool_msg.content
