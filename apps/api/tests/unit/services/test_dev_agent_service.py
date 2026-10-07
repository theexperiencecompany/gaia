"""A direct dev run that parks on a HIL approval must fail loud, not answer empty.

When a run pauses, SubagentOutcome.text is "" — returning it would present
an empty string as the agent's answer. A direct run has no approval channel to
resume on, so the only honest outcome is an error naming that.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.subagents.subagent_runner import SubagentOutcome
from app.agents.llm.lane import AgentRole, dev_option_for
from app.config.settings import settings
from app.constants.llm import DEV_MODEL_OPTIONS
from app.helpers.agent_helpers import AgentIdentity, AgentLane, AgentTurn
from app.models.user_models import OnboardingPreferences, OnboardingSubdocument
from app.schemas.dev_schemas import DevAgentRunResponse
from app.services.dev_agent_service import (
    _dev_base_configurable,
    _reject_pause,
    run_executor_direct,
    run_subagent_direct,
)
from app.utils.errors import AppError

MODULE = "app.services.dev_agent_service"


def test_a_paused_outcome_raises_conflict_instead_of_returning_empty_text() -> None:
    paused = SubagentOutcome(text="", interrupt={"type": "hil_approval", "approval_id": "a1"})

    with pytest.raises(AppError) as excinfo:
        _reject_pause(paused, "executor_agent")

    assert excinfo.value.status_code == 409


def test_a_finished_outcome_passes_through() -> None:
    assert _reject_pause(SubagentOutcome(text="done"), "executor_agent") is None


class TestTheParentConfigurableADirectRunBuilds:
    """A direct run is top-level, so it has to resolve its own lane.

    It resolved none at all before, which is why the dev harness quietly ran a
    different model than real chat — the one thing the harness exists to be
    faithful about.
    """

    async def _build(self, conversation_id: str | None) -> tuple[AsyncMock, str, str]:
        build_config = AsyncMock(return_value={"configurable": {"thread_id": "t"}})
        with (
            patch(f"{MODULE}.require_dev_user", AsyncMock(return_value=_dev_user_doc())),
            patch(f"{MODULE}.build_agent_config", build_config),
        ):
            _, user_id, cid = await _dev_base_configurable(
                "dev@gaia.local", conversation_id, "executor_agent"
            )
        return build_config, user_id, cid

    async def test_it_resolves_a_lane_as_the_executor_tier(self) -> None:
        build_config, _, cid = await self._build("conv-1")

        assert build_config.call_args.kwargs == {
            "identity": AgentIdentity(
                conversation_id=cid,
                user={"user_id": "u1", "email": "dev@gaia.local", "name": "Dev"},
                agent_name="executor_agent",
            ),
            # No model key passed, so the lane resolves the env DEV_DEFAULT_MODEL
            # pin — the same one real chat runs — rather than leaving it None and
            # silently falling to the plan-resolved lane.
            "lane": AgentLane(
                role=AgentRole.EXECUTOR,
                dev_option=dev_option_for(None, use_defaults=True),
            ),
            "turn": AgentTurn(user_preferences=None, writing_style=None),
        }

    async def test_a_passed_conversation_id_is_reused_so_turns_share_a_thread(self) -> None:
        _, _, cid = await self._build("conv-1")

        assert cid == "conv-1"

    async def test_a_missing_conversation_id_is_minted(self) -> None:
        _, _, cid = await self._build(None)

        assert cid and cid != "conv-1"


async def test_the_dev_users_onboarding_data_reaches_the_configurable() -> None:
    """_dev_base_configurable must thread onboarding into build_agent_config like comms does, not leave a direct run blind to it."""
    # name is MagicMock's own constructor argument, so it is set afterwards.
    user_doc = MagicMock(
        id="dev-user-1",
        email="dev@gaia.local",
        onboarding=OnboardingSubdocument(
            preferences=OnboardingPreferences(profession="engineer"),
            writing_style={"summary": "terse"},
        ),
    )
    user_doc.name = "Dev User"
    with patch(f"{MODULE}.require_dev_user", AsyncMock(return_value=user_doc)):
        configurable, user_id, _ = await _dev_base_configurable("dev@gaia.local", None, "executor")

    assert user_id == "dev-user-1"
    assert configurable["user_preferences"] == {"profession": "engineer"}
    assert configurable["writing_style"] == {"summary": "terse"}


def _dev_user_doc() -> MagicMock:
    # onboarding=None explicitly: a bare MagicMock attribute is truthy, unlike a never-onboarded user's.
    user_doc = MagicMock(id="u1", email="dev@gaia.local", onboarding=None)
    user_doc.name = "Dev"
    return user_doc


PARENT_CONFIGURABLE = {"thread_id": "parent-thread"}


@contextmanager
def _direct_run(
    prepare_target: str, prepared: tuple[object, ...], outcome: SubagentOutcome
) -> Iterator[SimpleNamespace]:
    """Stand in for the dev user lookup, the config build and the graph run of a direct run."""
    seams = SimpleNamespace(
        dev_user=AsyncMock(return_value=_dev_user_doc()),
        build=AsyncMock(return_value={"configurable": PARENT_CONFIGURABLE}),
        prepare=AsyncMock(return_value=prepared),
        execute=AsyncMock(return_value=outcome),
    )
    with (
        patch(f"{MODULE}.require_dev_user", seams.dev_user),
        patch(f"{MODULE}.build_agent_config", seams.build),
        patch(f"{MODULE}.{prepare_target}", seams.prepare),
        patch(f"{MODULE}.execute_subagent_stream", seams.execute),
    ):
        yield seams


class TestTheModelADirectRunIsAskedFor:
    """The endpoint's model field is the dev harness's one knob for picking a model."""

    async def _lane_for(self, model: str | None, dev_default: str | None) -> AgentLane:
        build_config = AsyncMock(return_value={"configurable": {"thread_id": "t"}})
        with (
            patch(f"{MODULE}.require_dev_user", AsyncMock(return_value=_dev_user_doc())),
            patch(f"{MODULE}.build_agent_config", build_config),
            patch.object(settings, "DEV_DEFAULT_MODEL", dev_default),
        ):
            await _dev_base_configurable("dev@gaia.local", "conv-1", "executor_agent", model)
        return build_config.call_args.kwargs["lane"]

    @pytest.mark.regression
    async def test_an_explicit_model_wins_over_the_env_default(self) -> None:
        lane = await self._lane_for("glm-5.2", dev_default="minimax-m3")

        assert lane.dev_option == DEV_MODEL_OPTIONS["glm-5.2"]

    @pytest.mark.regression
    async def test_an_explicit_model_is_honoured_with_no_env_default(self) -> None:
        lane = await self._lane_for("glm-5.2", dev_default=None)

        assert lane.dev_option == DEV_MODEL_OPTIONS["glm-5.2"]

    async def test_no_model_falls_back_to_the_env_default(self) -> None:
        lane = await self._lane_for(None, dev_default="minimax-m3")

        assert lane.dev_option == DEV_MODEL_OPTIONS["minimax-m3"]

    async def test_the_executor_run_forwards_its_model(self) -> None:
        ctx = SimpleNamespace(agent_name="executor_agent", configurable={"thread_id": "t"})
        with (
            _direct_run("prepare_executor_execution", (ctx, None), SubagentOutcome("ok")) as seams,
            patch.object(settings, "DEV_DEFAULT_MODEL", None),
        ):
            await run_executor_direct("dev@gaia.local", "task", "conv-1", model="glm-5.2")

        assert seams.build.call_args.kwargs["lane"].dev_option == DEV_MODEL_OPTIONS["glm-5.2"]

    async def test_the_subagent_run_forwards_its_model(self) -> None:
        ctx = SimpleNamespace(agent_name="gmail_agent", configurable={"thread_id": "t"})
        with (
            _direct_run(
                "prepare_subagent_execution", (ctx, None, None), SubagentOutcome("ok")
            ) as seams,
            patch.object(settings, "DEV_DEFAULT_MODEL", None),
        ):
            await run_subagent_direct("dev@gaia.local", "gmail", "task", "conv-1", model="glm-5.2")

        assert seams.build.call_args.kwargs["lane"].dev_option == DEV_MODEL_OPTIONS["glm-5.2"]


class TestRunExecutorDirect:
    async def test_it_returns_the_executors_answer_on_the_prepared_thread(self) -> None:
        ctx = SimpleNamespace(agent_name="executor_agent", configurable={"thread_id": "exec-t"})
        with _direct_run(
            "prepare_executor_execution", (ctx, None), SubagentOutcome("the answer")
        ) as seams:
            response = await run_executor_direct("dev@gaia.local", "do it", "conv-1")

        assert response == DevAgentRunResponse(
            user_id="u1",
            conversation_id="conv-1",
            thread_id="exec-t",
            agent="executor_agent",
            message="the answer",
        )
        seams.prepare.assert_awaited_once_with(task="do it", configurable=PARENT_CONFIGURABLE)
        seams.execute.assert_awaited_once_with(ctx)
        seams.dev_user.assert_awaited_once_with("dev@gaia.local")
        assert seams.build.call_args.kwargs["identity"].agent_name == "executor_agent"

    async def test_a_context_without_a_thread_reports_an_empty_thread_id(self) -> None:
        ctx = SimpleNamespace(agent_name="executor_agent", configurable={})
        with _direct_run("prepare_executor_execution", (ctx, None), SubagentOutcome("ok")):
            response = await run_executor_direct("dev@gaia.local", "do it", "conv-1")

        assert response.thread_id == ""

    async def test_an_unavailable_executor_is_a_503_naming_the_cause(self) -> None:
        with (
            _direct_run("prepare_executor_execution", (None, "no model"), SubagentOutcome("")),
            pytest.raises(AppError) as excinfo,
        ):
            await run_executor_direct("dev@gaia.local", "do it", "conv-1")

        assert excinfo.value.status_code == 503
        assert excinfo.value.message == "Executor agent unavailable"
        assert excinfo.value.why == "no model"

    async def test_an_unavailable_executor_with_no_cause_still_says_why(self) -> None:
        with (
            _direct_run("prepare_executor_execution", (None, None), SubagentOutcome("")),
            pytest.raises(AppError) as excinfo,
        ):
            await run_executor_direct("dev@gaia.local", "do it", "conv-1")

        assert excinfo.value.why == "prepare_executor_execution returned no context"

    async def test_a_paused_executor_run_is_a_409(self) -> None:
        ctx = SimpleNamespace(agent_name="executor_agent", configurable={"thread_id": "t"})
        paused = SubagentOutcome(text="", interrupt={"type": "hil_approval", "approval_id": "a1"})
        with (
            _direct_run("prepare_executor_execution", (ctx, None), paused),
            pytest.raises(AppError) as excinfo,
        ):
            await run_executor_direct("dev@gaia.local", "do it", "conv-1")

        assert excinfo.value.status_code == 409


class TestRunSubagentDirect:
    async def test_it_returns_the_subagents_answer_on_the_prepared_thread(self) -> None:
        ctx = SimpleNamespace(agent_name="gmail_agent", configurable={"thread_id": "sub-t"})
        metadata = {"integration_id": "gmail"}
        with _direct_run(
            "prepare_subagent_execution", (ctx, metadata, None), SubagentOutcome("sent")
        ) as seams:
            response = await run_subagent_direct("dev@gaia.local", "gmail", "send it", "conv-1")

        assert response == DevAgentRunResponse(
            user_id="u1",
            conversation_id="conv-1",
            thread_id="sub-t",
            agent="gmail_agent",
            message="sent",
        )
        seams.prepare.assert_awaited_once_with(
            subagent_id="gmail", task="send it", configurable=PARENT_CONFIGURABLE
        )
        seams.execute.assert_awaited_once_with(ctx, integration_metadata=metadata)
        seams.dev_user.assert_awaited_once_with("dev@gaia.local")
        assert seams.build.call_args.kwargs["identity"].agent_name == "dev_direct"

    async def test_a_context_without_a_thread_reports_an_empty_thread_id(self) -> None:
        ctx = SimpleNamespace(agent_name="gmail_agent", configurable={})
        with _direct_run("prepare_subagent_execution", (ctx, None, None), SubagentOutcome("ok")):
            response = await run_subagent_direct("dev@gaia.local", "gmail", "send it", "conv-1")

        assert response.thread_id == ""

    async def test_an_unrunnable_subagent_is_a_400_pointing_at_the_list(self) -> None:
        with (
            _direct_run(
                "prepare_subagent_execution", (None, None, "not a subagent"), SubagentOutcome("")
            ),
            pytest.raises(AppError) as excinfo,
        ):
            await run_subagent_direct("dev@gaia.local", "nope", "send it", "conv-1")

        assert excinfo.value.status_code == 400
        assert excinfo.value.message == "Cannot run subagent 'nope'"
        assert excinfo.value.why == "not a subagent"
        assert excinfo.value.fix == "GET /api/v1/dev/subagents lists the runnable ids"

    async def test_an_unrunnable_subagent_with_no_cause_still_says_why(self) -> None:
        with (
            _direct_run("prepare_subagent_execution", (None, None, None), SubagentOutcome("")),
            pytest.raises(AppError) as excinfo,
        ):
            await run_subagent_direct("dev@gaia.local", "nope", "send it", "conv-1")

        assert excinfo.value.why == "prepare_subagent_execution returned no context"

    async def test_a_paused_subagent_run_is_a_409(self) -> None:
        ctx = SimpleNamespace(agent_name="gmail_agent", configurable={"thread_id": "t"})
        paused = SubagentOutcome(text="", interrupt={"type": "hil_approval", "approval_id": "a1"})
        with (
            _direct_run("prepare_subagent_execution", (ctx, None, None), paused),
            pytest.raises(AppError) as excinfo,
        ):
            await run_subagent_direct("dev@gaia.local", "gmail", "send it", "conv-1")

        assert excinfo.value.status_code == 409
