"""build_comms_turn: the run config, context and attribution of one comms attempt on its batch."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from app.agents.context.assemble import AssembledContext
from app.agents.core.messages import TurnContext, build_turn_context
from app.agents.llm.lane import AgentRole
from app.agents.prompts.comms_prompts import PLATFORM_DELIVERY_NOTE
from app.agents.prompts.openui_prompts import OPENUI_INSTRUCTIONS
from app.constants.chat import ConversationSource
from app.models.conversation_log_models import Batch, Entry, StepClaim, UserMessage
from app.models.presence_models import PresenceSnapshot
from app.models.user_models import AuthenticatedUser, OnboardingSubdocument
from app.services.conversation.comms_turn import build_comms_turn
from app.services.conversation.reply_analytics import spoken_context
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.context import AnalyticsContext
from tests.factories import make_authenticated_user
from tests.unit.services.conversation.log_helpers import at, finished, fired, logged, todo_run
from tests.unit.services.conversation.runtime_doubles import CONVERSATION, USER

MODULE = "app.services.conversation.comms_turn"

PRESENCE: PresenceSnapshot = {"captured_at": 100, "last_seen": {"web": 90}}

CLAIM = StepClaim(conversation_id=CONVERSATION, user_id=USER, epoch=4)


def _batch(start: int, entries: Sequence[Entry]) -> Batch:
    waking = tuple(logged(start + offset, entry) for offset, entry in enumerate(entries))
    return Batch(start=start, end=start + len(entries) - 1, waking=waking, first_at=at(start))


def _said(entry_id: str, surface: ConversationSource, **fields: object) -> UserMessage:
    return UserMessage.model_validate(
        {"id": entry_id, "text": f"text {entry_id}", "surface": surface, **fields}
    )


@dataclass
class Seams:
    user: AuthenticatedUser
    presence: AsyncMock
    touch: MagicMock
    conversations: MagicMock
    turn_context: AsyncMock
    agent_config: AsyncMock
    reported: AsyncMock
    write_up: AsyncMock
    context: TurnContext
    log: object
    owner: AsyncMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    user = make_authenticated_user(
        user_id=USER,
        name="Priya",
        timezone="UTC",
        onboarding=OnboardingSubdocument.model_validate(
            {"preferences": {"response_style": "brief"}, "writing_style": {"tone": "warm"}}
        ),
    )
    context = TurnContext(
        chain=[SystemMessage(content="system")],
        presence=HumanMessage(content="presence"),
        clock=HumanMessage(content="clock"),
    )
    log = object()
    with (
        patch(f"{MODULE}.require_owner", AsyncMock(return_value=user)) as owner,
        patch(f"{MODULE}.presence_before", AsyncMock(return_value=PRESENCE)) as presence,
        patch(f"{MODULE}.schedule_last_active_touch") as touch,
        patch(f"{MODULE}.conversation_repository") as conversations,
        patch(f"{MODULE}.build_turn_context", AsyncMock(return_value=context)) as turn_context,
        patch(f"{MODULE}.build_agent_config", AsyncMock()) as agent_config,
        patch(f"{MODULE}.todo_runs_reported", AsyncMock(return_value=[])) as reported,
        patch(f"{MODULE}.write_up_note", AsyncMock(return_value="write it up")) as write_up,
        patch(f"{MODULE}.runtime_ports", return_value=SimpleNamespace(log=log)),
    ):
        conversations.get_todo_id = AsyncMock(return_value=None)
        conversations.is_workflow_execution = AsyncMock(return_value=False)
        conversations.get_source = AsyncMock(return_value=None)
        agent_config.side_effect = lambda **_: {"configurable": {}}
        yield Seams(
            user,
            presence,
            touch,
            conversations,
            turn_context,
            agent_config,
            reported,
            write_up,
            context,
            log,
            owner,
        )


async def test_a_users_messages_are_answered_on_the_surface_they_last_spoke_from(
    seams: Seams,
) -> None:
    seams.conversations.get_todo_id.return_value = "todo_9"
    first = _said("u1", ConversationSource.WEB, selected_tool="gmail_send", tool_category="mail")
    last = _said("u2", ConversationSource.TELEGRAM)
    batch = _batch(1, [first, last])

    turn = await build_comms_turn(CLAIM, batch)

    query = "text u1\n\ntext u2"
    seams.presence.assert_awaited_once_with(USER, last)
    seams.touch.assert_called_once_with(USER, CONVERSATION)
    seams.conversations.get_todo_id.assert_awaited_once_with(CONVERSATION, user_id=USER)
    turn_query, scope = seams.turn_context.await_args.args
    assert turn_query == query
    assert (scope.user_id, scope.user_name, scope.user_dict) == (USER, "Priya", seams.user)
    assert (scope.conversation_id, scope.source, scope.active_todo_id) == (
        CONVERSATION,
        "telegram",
        "todo_9",
    )
    seams.owner.assert_awaited_once_with(USER)
    assert (scope.execution_mode, scope.presence, scope.opens_thread) == (
        "interactive",
        PRESENCE,
        True,
    )

    kwargs = seams.agent_config.await_args.kwargs
    assert kwargs["identity"].conversation_id == CONVERSATION
    assert kwargs["identity"].agent_name == "comms_agent"
    assert kwargs["identity"].user["user_id"] == USER
    assert kwargs["lane"].role is AgentRole.COMMS
    agent_turn = kwargs["turn"]
    assert (agent_turn.selected_tool, agent_turn.tool_category) == ("gmail_send", "mail")
    assert (agent_turn.active_todo_id, agent_turn.execution_mode, agent_turn.source) == (
        "todo_9",
        "interactive",
        "telegram",
    )
    assert agent_turn.user_messages == ["text u1", "text u2"]
    assert agent_turn.user_request == query
    assert agent_turn.workflow_id is None
    assert agent_turn.presence == PRESENCE
    assert agent_turn.user_preferences == {"response_style": "brief"}
    assert agent_turn.writing_style == {"tone": "warm"}

    configurable = turn.config["configurable"]
    assert configurable["conversation_step"] == {
        "epoch": 4,
        "batch_start": 1,
        "cause_through": 2,
        "answers": ["u1", "u2"],
        "asked": True,
    }
    assert UUID(configurable["stream_id"])
    assert "workflow_id" not in configurable
    assert turn.opening == [*seams.context.chain, seams.context.presence]
    assert turn.closing == [seams.context.clock]
    assert turn.analytics == spoken_context(last)
    assert turn.run_started.agent == "comms"
    assert (turn.run_started.mode, turn.run_started.source) == ("interactive", "telegram")
    assert turn.run_started.conversation_id == CONVERSATION
    assert turn.run_started.trigger_type is None
    assert turn.state == {
        "query": query,
        "intent": query,
        "memory_user_id": USER,
        "conversation_id": CONVERSATION,
        "integration_usernames": {},
        "active_todo_id": "todo_9",
    }
    seams.reported.assert_not_awaited()


async def test_each_attempt_gets_its_own_stream_and_a_later_batch_does_not_open_the_thread(
    seams: Seams,
) -> None:
    seams.context = TurnContext(chain=seams.context.chain, presence=None, clock=seams.context.clock)
    seams.turn_context.return_value = seams.context
    batch = _batch(5, [_said("u5", ConversationSource.WEB)])

    one = await build_comms_turn(CLAIM, batch)
    two = await build_comms_turn(CLAIM, batch)

    assert one.config["configurable"]["stream_id"] != two.config["configurable"]["stream_id"]
    assert seams.turn_context.await_args.args[1].opens_thread is False
    assert one.opening == seams.context.chain
    assert seams.agent_config.await_args.kwargs["turn"].selected_tool is None
    assert "active_todo_id" not in one.state


async def test_a_workflow_fire_runs_in_the_background_on_its_own_record(seams: Seams) -> None:
    entry = fired("f1", execution_id="ex_7")
    run = entry.run.model_copy(
        update={
            "trigger": entry.run.trigger.model_copy(
                update={
                    "type": "schedule",
                    "workflow_notify_on_completion": False,
                    "playbook_fallback": "the agent",
                }
            )
        }
    )
    batch = _batch(3, [entry.model_copy(update={"run": run})])
    seams.conversations.get_source.return_value = ConversationSource.WEB

    turn = await build_comms_turn(CLAIM, batch)

    seams.presence.assert_awaited_once_with(USER, None)
    seams.touch.assert_not_called()
    query, scope = seams.turn_context.await_args.args
    assert query == "Execute workflow: Morning brief"
    assert (scope.execution_mode, scope.source) == ("background", "background")
    assert scope.user_dict.timezone == "Asia/Kolkata"
    agent_turn = seams.agent_config.await_args.kwargs["turn"]
    assert agent_turn.workflow_id == "wf_1"
    assert agent_turn.user_request == query
    assert any("Morning brief" in line for line in agent_turn.user_messages)
    assert any("Brief me" in line for line in agent_turn.user_messages)
    configurable = turn.config["configurable"]
    assert configurable["stream_id"] == "ex_7"
    assert configurable["workflow_id"] == "wf_1"
    assert configurable["workflow_title"] == "Morning brief"
    assert configurable["workflow_notify_on_completion"] is False
    assert configurable["playbook_fallback"] == "the agent"
    assert turn.analytics == AnalyticsContext(attribution=run.attribution)
    assert turn.run_started.trigger_type == "schedule"
    assert turn.run_started.mode == "background"


async def test_finished_work_with_no_one_asking_is_unprompted_and_quiet_by_default(
    seams: Seams,
) -> None:
    batch = _batch(6, [finished("w6", "t1")])

    turn = await build_comms_turn(CLAIM, batch)

    assert turn.analytics == AnalyticsContext(
        attribution=Attribution(
            actor=Actor.AGENT, trigger=Trigger.SYSTEM, surface=EntrySurface.WORKER
        )
    )
    assert seams.turn_context.await_args.args[1].source == "background"
    seams.reported.assert_awaited_once_with(seams.log, CONVERSATION, USER, batch)
    seams.conversations.is_workflow_execution.assert_awaited_once_with(CONVERSATION)
    assert turn.closing == [seams.context.clock]


async def test_a_workflows_finished_work_is_written_for_a_plain_text_platform(
    seams: Seams,
) -> None:
    seams.conversations.is_workflow_execution.return_value = True

    turn = await build_comms_turn(CLAIM, _batch(6, [finished("w6", "t1")]))

    assert turn.closing == [HumanMessage(content=PLATFORM_DELIVERY_NOTE), seams.context.clock]


async def test_a_todos_finished_run_is_written_up_by_its_note(seams: Seams) -> None:
    work = finished("w6", "t1")
    run = todo_run()
    seams.reported.return_value = [(work, run)]

    turn = await build_comms_turn(CLAIM, _batch(6, [work]))

    seams.write_up.assert_awaited_once_with(run)
    seams.conversations.is_workflow_execution.assert_not_awaited()
    assert turn.closing == [HumanMessage(content="write it up"), seams.context.clock]


@pytest.mark.parametrize(
    ("surface", "renders_openui"),
    [(ConversationSource.TELEGRAM, False), (ConversationSource.WEB, True)],
)
async def test_finished_work_is_answered_with_the_prompt_of_the_conversations_own_surface(
    seams: Seams, surface: ConversationSource, renders_openui: bool
) -> None:
    seams.conversations.get_source.return_value = surface

    await build_comms_turn(CLAIM, _batch(6, [finished("w6", "t1")]))

    scope = seams.turn_context.await_args.args[1]
    assert seams.agent_config.await_args.kwargs["turn"].source == surface.value
    seams.presence.assert_not_awaited()
    assert scope.presence is None
    stable = AssembledContext(stable=HumanMessage(content="context"), volatile=None)
    with patch("app.agents.core.messages.assemble_context", AsyncMock(return_value=stable)):
        system = (await build_turn_context("report", scope)).chain[0]
    assert (OPENUI_INSTRUCTIONS in str(system.content)) is renders_openui
