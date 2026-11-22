"""title_conversation: the first message's title is the agent's work, and every open client hears it."""

from dataclasses import dataclass, field

import pytest

from app.constants.chat import ConversationSource
from app.models.conversation_log_models import UserMessage
from app.models.message_models import SelectedWorkflowData
from app.models.user_models import AuthenticatedUser
from app.services.conversation import title as title_module
from app.services.conversation.runtime import install_runtime_ports
from app.services.conversation.title import title_conversation
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.context import (
    AnalyticsContext,
    analytics_context,
    current_analytics_context,
)
from shared.py.conversation_wire import ConversationUpdatedFrame
from tests.unit.services.conversation.runtime_doubles import CONVERSATION, Runtime

USERS_TURN = AnalyticsContext(
    attribution=Attribution(actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.WEB)
)


@dataclass
class Titler:
    """Stands in for the LLM title generator: records what it was asked, and who was acting."""

    asked: list[tuple[object, ...]] = field(default_factory=list)
    actors: list[Actor] = field(default_factory=list)

    async def __call__(self, *args: object) -> str:
        self.asked.append(args)
        self.actors.append(current_analytics_context().attribution.actor)
        return "Trip to Pune"


async def test_the_title_is_generated_as_the_agent_and_published_to_the_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rt = Runtime()
    install_runtime_ports(rt.ports)
    titler = Titler()
    monkeypatch.setattr(title_module, "generate_and_update_description", titler)
    user = AuthenticatedUser(user_id="uid1")
    workflow = SelectedWorkflowData(id="wf_1", title="Trip", description="plan", steps=[])
    first = UserMessage(
        id="m1",
        text="plan my trip",
        surface=ConversationSource.WEB,
        selected_tool="search",
        selected_workflow=workflow,
    )
    with analytics_context(USERS_TURN):
        await title_conversation(CONVERSATION, user, first)
    assert titler.asked == [
        (CONVERSATION, {"role": "user", "content": "plan my trip"}, user, "search", workflow)
    ]
    assert titler.actors == [Actor.AGENT]
    assert rt.frames.published == [ConversationUpdatedFrame(description="Trip to Pune")]
    assert rt.frames.conversations == [CONVERSATION]
