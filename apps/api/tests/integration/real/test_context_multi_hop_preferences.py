"""Real-infra proof that onboarding preferences survive the multi-hop build_agent_config chain to the section a subagent renders.

Unit tests for this plumbing (tests/unit/helpers/test_agent_helpers.py,
tests/unit/agents/test_agent_core.py et al.) each prove one hop at a time
against a hand-built base_configurable dict. This proves the real chain:
comms reads a real user document, the executor inherits from comms's live
configurable, and a handoff subagent inherits from the executor's — three
real, unmocked build_agent_config calls, chained the same way
_core_agent_logic / prepare_executor_execution / prepare_subagent_execution
chain them in production.
"""

from __future__ import annotations

import pytest

from app.agents.context.assemble import assemble_context
from app.agents.context.section_context import SectionContext, SectionScope
from app.agents.context.tiers import AgentTier
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository
from app.helpers.agent_helpers import (
    AgentIdentity,
    AgentThread,
    AgentTurn,
    build_agent_config,
)
from app.models.agent_models import AgentUserContext
from app.models.todo_models import TodoDocument
from app.models.user_models import UserDocument
from app.utils.user_preferences_utils import onboarding_preferences


@pytest.mark.service
class TestPreferencesSurviveTheRealMultiHopChain:
    async def test_root_to_executor_to_subagent(self, mongo_db, real_redis) -> None:
        """Confirm onboarding preferences carry from MongoDB through two real comms -> executor -> subagent inheritance calls, not a hand-built stand-in."""
        await user_repository.create(
            UserDocument(
                email="prefs-multi-hop@gaia.local",
                name="Multi Hop",
                onboarding={
                    "preferences": {"profession": "architect"},
                    "writing_style": {"summary": "warm and concise"},
                },
            )
        )

        # Hop 1 — root. Mirrors _core_agent_logic: read the real document back,
        # extract onboarding data from it, seed build_agent_config with no parent.
        real_user = await user_repository.get_by_email("prefs-multi-hop@gaia.local")
        assert real_user is not None
        preferences, writing_style = onboarding_preferences(real_user.onboarding)
        agent_user: AgentUserContext = {
            "user_id": real_user.id,
            "email": real_user.email,
            "name": real_user.name,
        }
        comms_config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id="conv-multi-hop",
                user=agent_user,
                agent_name="comms_agent",
            ),
            turn=AgentTurn(
                user_preferences=preferences,
                writing_style=writing_style,
            ),
        )

        # Hop 2 — executor. Mirrors prepare_executor_execution: a fresh
        # build_agent_config call whose base_configurable is the parent's own
        # live configurable, not a value re-threaded by hand.
        executor_config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id="conv-multi-hop",
                user=agent_user,
                agent_name="executor_agent",
            ),
            thread=AgentThread(
                base_configurable=comms_config["configurable"],
            ),
        )

        # Hop 3 — subagent handoff. Mirrors prepare_subagent_execution. Also
        # where the run gets bound to a real todo, seeded below.
        todo = await todo_repository.create(
            TodoDocument(user_id=real_user.id, title="Draft the quarterly update")
        )
        subagent_config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id="conv-multi-hop",
                user=agent_user,
                agent_name="gmail_agent",
            ),
            thread=AgentThread(
                base_configurable=executor_config["configurable"],
                subagent_id="gmail_agent",
            ),
            turn=AgentTurn(
                active_todo_id=todo.id,
            ),
        )

        configurable = subagent_config["configurable"]
        assert configurable["user_preferences"] == {"profession": "architect"}
        assert configurable["writing_style"] == {"summary": "warm and concise"}

        # The active-todo banner is a fresh MongoDB read at assembly time, not
        # carried through the chain above.
        ctx = SectionContext.from_configurable(
            AgentTier.PROVIDER_SUBAGENT, configurable, SectionScope(user_id=real_user.id)
        )
        assembled = await assemble_context(ctx)

        assert "User Profession: Architect" in assembled.stable.content
        assert assembled.volatile is not None
        assert "Draft the quarterly update" in assembled.volatile.content
