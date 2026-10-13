"""Unit tests for the todo/workflow creation and holo-card nodes.

These are the nodes that turn LLM output into persisted records, so the tests
concentrate on what happens when the model returns too much, too little, or
fabricated data, and on partial persistence failures. Only the LLM client, the
todo/workflow services and the repositories are faked.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.onboarding import NOT_SPECIFIED
from app.constants.todos import ONBOARDING_TODO_LIMIT
from app.models.onboarding_models import (
    EmailSummary,
    InboxTriage,
    OnboardingTodoSource,
    OnboardingTodoSummary,
    OnboardingTriggerPayload,
    OnboardingWorkflowSummary,
    ProfileCardDesign,
    SocialProfile,
    UserProfileMetadata,
    WritingStyleExampleBlocks,
    WritingStyleProfile,
)
from app.models.user_models import UserDocument
from app.models.workflow_models import (
    IntegrationRef,
    SuggestedTrigger,
    TriggerConfig,
    TriggerType,
)
from app.services.onboarding.intelligence_service import (
    _DEFAULT_WORKFLOW_CRON,
    OnboardingContext,
    OnboardingStage,
    _build_one_workflow,
    _create_fallback_workflow,
    _create_focus_todos,
    _create_onboarding_workflows,
    _create_todos_from_triage,
    _FocusTodoList,
    _run_holo_card,
    _TodoListFromEmails,
    _TodoSpec,
    _wait_for_early_phase,
    _WorkflowList,
    _WorkflowSpec,
)

MODULE = "app.services.onboarding.intelligence_service"
USER = "user-42"


def _ctx(**overrides: Any) -> OnboardingContext:
    defaults: dict[str, Any] = {
        "user_id": USER,
        "name": "Ann",
        "profession": "dev",
        "focus": "ship v2",
        "has_gmail": True,
    }
    defaults.update(overrides)
    return OnboardingContext(**defaults)


@pytest.fixture(autouse=True)
def quiet_logs() -> Any:
    with patch(f"{MODULE}.log", MagicMock()):
        yield


def _triage(**overrides: Any) -> InboxTriage:
    payload: dict[str, Any] = {
        "total_scanned": 9,
        "total_unread": 2,
        "summary": "Busy inbox",
        "important_emails": [
            EmailSummary(sender="ann@x.com", subject="Contract", why_important="deadline")
        ],
        "patterns": ["newsletters"],
    }
    payload.update(overrides)
    return InboxTriage(**payload)


def _made_todo(todo_id: str = "t1") -> MagicMock:
    todo = MagicMock()
    todo.id = todo_id
    return todo


# ---------------------------------------------------------------------------
# _create_focus_todos
# ---------------------------------------------------------------------------


class TestCreateFocusTodos:
    async def test_creates_one_todo_per_generated_title(self) -> None:
        parsed = _FocusTodoList(todos=["Draft the brief", "Book the review"])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(side_effect=[_made_todo("t1"), _made_todo("t2")])
            result = await _create_focus_todos(USER, "Ann", "lawyer", "close Q3")

        assert result == [
            OnboardingTodoSummary(id="t1", title="Draft the brief"),
            OnboardingTodoSummary(id="t2", title="Book the review"),
        ]

    async def test_todos_are_labelled_for_onboarding(self) -> None:
        # The onboarding UI and _fetch_onboarding_todos both filter on this label.
        parsed = _FocusTodoList(todos=["Draft the brief"])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            await _create_focus_todos(USER, "Ann", "lawyer", "close Q3")

        todo, user_id = service.create_todo.await_args.args
        assert todo.labels == ["onboarding"]
        assert user_id == USER

    async def test_description_records_the_originating_focus(self) -> None:
        parsed = _FocusTodoList(todos=["Draft the brief"])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            await _create_focus_todos(USER, "Ann", "lawyer", "close Q3")

        assert "close Q3" in service.create_todo.await_args.args[0].description

    async def test_more_titles_than_the_limit_are_dropped(self) -> None:
        parsed = _FocusTodoList(todos=[f"Task {i}" for i in range(10)])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            result = await _create_focus_todos(USER, "Ann", "lawyer", "close Q3")

        assert len(result) == ONBOARDING_TODO_LIMIT

    async def test_an_overlong_title_is_truncated(self) -> None:
        parsed = _FocusTodoList(todos=[" ".join(c * 10 for c in "abcdefgh")])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            result = await _create_focus_todos(USER, "Ann", "lawyer", "close Q3")

        assert result[0].title == " ".join(c * 10 for c in "abcdefg")

    async def test_one_failed_creation_does_not_lose_the_others(self) -> None:
        parsed = _FocusTodoList(todos=["A", "B", "C"])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(
                side_effect=[_made_todo("t1"), RuntimeError("mongo"), _made_todo("t3")]
            )
            result = await _create_focus_todos(USER, "Ann", "lawyer", "close Q3")

        assert [r.id for r in result] == ["t1", "t3"]

    async def test_an_llm_failure_degrades_to_an_empty_list(self) -> None:
        with patch(f"{MODULE}.ainvoke_structured", AsyncMock(side_effect=RuntimeError("llm"))):
            assert await _create_focus_todos(USER, "Ann", "lawyer", "close Q3") == []

    async def test_no_titles_creates_nothing(self) -> None:
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=_FocusTodoList(todos=[]))),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock()
            assert await _create_focus_todos(USER, "Ann", "lawyer", "close Q3") == []
            assert service.create_todo.await_count == 0

    async def test_clarify_answers_reach_the_prompt(self) -> None:
        llm = AsyncMock(return_value=_FocusTodoList(todos=[]))
        with (
            patch(f"{MODULE}.ainvoke_structured", llm),
            patch(f"{MODULE}.format_clarify_context", return_value="CLARIFY-BLOCK") as fmt,
        ):
            await _create_focus_todos(USER, "Ann", "lawyer", "close Q3", [{"kind": "k"}])

        assert fmt.call_args.args[0] == [{"kind": "k"}]
        assert "CLARIFY-BLOCK" in llm.await_args.args[1]


# ---------------------------------------------------------------------------
# _create_todos_from_triage
# ---------------------------------------------------------------------------


def _spec(**overrides: Any) -> _TodoSpec:
    payload: dict[str, Any] = {"title": "Reply to Ann", "description": "About the contract"}
    payload.update(overrides)
    return _TodoSpec(**payload)


class TestCreateTodosFromTriage:
    async def test_creates_todos_from_the_generated_specs(self) -> None:
        parsed = _TodoListFromEmails(todos=[_spec()])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo("t1"))
            result = await _create_todos_from_triage(USER, _triage())

        assert result == [OnboardingTodoSummary(id="t1", title="Reply to Ann")]

    async def test_a_real_source_email_is_attached(self) -> None:
        parsed = _TodoListFromEmails(
            todos=[_spec(source_sender="ann@x.com", source_subject="Contract")]
        )
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            result = await _create_todos_from_triage(USER, _triage())

        assert result[0].source_email == OnboardingTodoSource(
            sender="ann@x.com", subject="Contract"
        )

    @pytest.mark.parametrize(
        ("sender", "subject"),
        [
            ("ghost@x.com", "Contract"),
            ("ann@x.com", "Never Sent"),
            ("ghost@x.com", "Never Sent"),
        ],
    )
    async def test_a_fabricated_source_email_is_dropped(self, sender: str, subject: str) -> None:
        # The model invents plausible senders/subjects; attaching one would show
        # the user a citation to an email that does not exist.
        parsed = _TodoListFromEmails(todos=[_spec(source_sender=sender, source_subject=subject)])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            result = await _create_todos_from_triage(USER, _triage())

        assert result[0].source_email is None

    async def test_a_todo_with_no_source_claim_is_still_created(self) -> None:
        parsed = _TodoListFromEmails(todos=[_spec(source_sender="", source_subject="")])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            result = await _create_todos_from_triage(USER, _triage())

        assert result[0].id == "t1"
        assert result[0].source_email is None

    async def test_only_the_first_eight_emails_ground_the_prompt(self) -> None:
        triage = _triage(
            important_emails=[
                EmailSummary(sender=f"s{i}@x.com", subject=f"sub{i}", why_important="w")
                for i in range(12)
            ]
        )
        llm = AsyncMock(return_value=_TodoListFromEmails(todos=[]))
        with patch(f"{MODULE}.ainvoke_structured", llm):
            await _create_todos_from_triage(USER, triage)

        prompt = llm.await_args.args[1]
        assert "s7@x.com" in prompt
        assert "s8@x.com" not in prompt

    async def test_a_source_beyond_the_grounded_window_is_rejected(self) -> None:
        # Emails 8+ never reach the model, so a citation to one is a fabrication.
        triage = _triage(
            important_emails=[
                EmailSummary(sender=f"s{i}@x.com", subject=f"sub{i}", why_important="w")
                for i in range(12)
            ]
        )
        parsed = _TodoListFromEmails(todos=[_spec(source_sender="s9@x.com", source_subject="sub9")])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            result = await _create_todos_from_triage(USER, triage)

        assert "source_email" not in result[0]

    async def test_more_specs_than_the_limit_are_dropped(self) -> None:
        parsed = _TodoListFromEmails(todos=[_spec(title=f"T{i}") for i in range(10)])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            result = await _create_todos_from_triage(USER, _triage())

        assert len(result) == ONBOARDING_TODO_LIMIT

    async def test_description_is_capped(self) -> None:
        parsed = _TodoListFromEmails(todos=[_spec(description="d" * 900)])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            await _create_todos_from_triage(USER, _triage())

        assert len(service.create_todo.await_args.args[0].description) == 500

    async def test_one_failed_creation_does_not_lose_the_others(self) -> None:
        parsed = _TodoListFromEmails(todos=[_spec(title="A"), _spec(title="B")])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(side_effect=[RuntimeError("mongo"), _made_todo("t2")])
            result = await _create_todos_from_triage(USER, _triage())

        assert [r.id for r in result] == ["t2"]

    async def test_an_llm_failure_degrades_to_an_empty_list(self) -> None:
        with patch(f"{MODULE}.ainvoke_structured", AsyncMock(side_effect=RuntimeError("llm"))):
            assert await _create_todos_from_triage(USER, _triage()) == []

    async def test_blank_profession_and_focus_are_marked_not_specified(self) -> None:
        llm = AsyncMock(return_value=_TodoListFromEmails(todos=[]))
        with patch(f"{MODULE}.ainvoke_structured", llm):
            await _create_todos_from_triage(USER, _triage(), profession="", focus="")

        assert llm.await_args.args[1].count(NOT_SPECIFIED) >= 2


# ---------------------------------------------------------------------------
# _build_one_workflow
# ---------------------------------------------------------------------------


def _card(workflow_id: str, title: str = "Daily Briefing") -> OnboardingWorkflowSummary:
    return OnboardingWorkflowSummary(
        id=workflow_id,
        title=title,
        description="d",
        categories=[],
        trigger=OnboardingTriggerPayload(
            type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON
        ),
    )


def _fallback_cards() -> list[OnboardingWorkflowSummary]:
    return [_card("fb")]


def _workflow(workflow_id: str = "w1") -> MagicMock:
    workflow = MagicMock()
    workflow.id = workflow_id
    workflow.steps = []
    workflow.trigger_config = TriggerConfig(
        type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON
    )
    return workflow


@pytest.fixture
def workflow_stack() -> Any:
    with (
        patch(f"{MODULE}.WorkflowGenerationService") as generation,
        patch(f"{MODULE}.WorkflowService") as service,
        patch(f"{MODULE}.compute_required_integrations", return_value=[]),
        patch(f"{MODULE}.compute_missing_integrations", AsyncMock(return_value=[])),
    ):
        generation.generate_workflow_prompt = AsyncMock(
            return_value={"prompt": "generated prompt", "suggested_trigger": None}
        )
        service.create_workflow = AsyncMock(return_value=_workflow())
        yield generation, service


class TestBuildOneWorkflow:
    async def test_returns_the_card_payload_for_a_created_workflow(
        self, workflow_stack: Any
    ) -> None:
        spec = _WorkflowSpec(title="Daily brief", description="Summarize", categories=["gmail"])
        result = await _build_one_workflow(USER, 0, spec, "UTC")

        assert result is not None
        assert result.model_dump(mode="json", exclude_none=True) == {
            "id": "w1",
            "title": "Daily brief",
            "description": "Summarize",
            "categories": ["gmail"],
            "trigger": {"type": "schedule", "cron_expression": _DEFAULT_WORKFLOW_CRON},
            "missing_integrations": [],
        }

    async def test_generated_prompt_is_used(self, workflow_stack: Any) -> None:
        _, service = workflow_stack
        await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        assert service.create_workflow.await_args.args[0].prompt == "generated prompt"

    async def test_an_empty_generated_prompt_falls_back_to_the_description(
        self, workflow_stack: Any
    ) -> None:
        generation, service = workflow_stack
        generation.generate_workflow_prompt = AsyncMock(
            return_value={"prompt": "", "suggested_trigger": None}
        )
        await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="the desc"), "UTC")

        assert service.create_workflow.await_args.args[0].prompt == "the desc"

    async def test_user_timezone_is_forwarded(self, workflow_stack: Any) -> None:
        _, service = workflow_stack
        await _build_one_workflow(
            USER, 0, _WorkflowSpec(title="t", description="d"), "Europe/London"
        )

        assert service.create_workflow.await_args.kwargs["user_timezone"] == "Europe/London"

    async def test_spec_categories_become_the_integration_ids(self, workflow_stack: Any) -> None:
        _, service = workflow_stack
        spec = _WorkflowSpec(title="t", description="d", categories=["notion"])
        await _build_one_workflow(USER, 0, spec, "UTC", ["slack"])

        assert service.create_workflow.await_args.args[0].integration_ids == ["notion"]

    async def test_a_suggested_trigger_is_mapped(self, workflow_stack: Any) -> None:
        generation, service = workflow_stack
        generation.generate_workflow_prompt = AsyncMock(
            return_value={"prompt": "p", "suggested_trigger": SuggestedTrigger(type="manual")}
        )
        await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        assert service.create_workflow.await_args.args[0].trigger_config.type is TriggerType.MANUAL

    async def test_missing_integrations_are_surfaced_on_the_card(self, workflow_stack: Any) -> None:
        ref = IntegrationRef(id="slack", name="Slack")
        with patch(f"{MODULE}.compute_missing_integrations", AsyncMock(return_value=[ref])):
            result = await _build_one_workflow(
                USER, 0, _WorkflowSpec(title="t", description="d"), "UTC"
            )

        assert result is not None
        assert result.missing_integrations == [IntegrationRef(id="slack", name="Slack")]

    async def test_the_persisted_trigger_is_echoed_not_the_requested_one(
        self, workflow_stack: Any
    ) -> None:
        # WorkflowService may normalize the trigger; the card must show what was saved.
        _, service = workflow_stack
        saved = _workflow()
        saved.trigger_config = TriggerConfig(type=TriggerType.MANUAL)
        service.create_workflow = AsyncMock(return_value=saved)

        result = await _build_one_workflow(
            USER, 0, _WorkflowSpec(title="t", description="d"), "UTC"
        )

        assert result is not None
        assert result.trigger.model_dump(mode="json", exclude_none=True) == {"type": "manual"}

    async def test_a_creation_failure_yields_none(self, workflow_stack: Any) -> None:
        _, service = workflow_stack
        service.create_workflow = AsyncMock(side_effect=RuntimeError("mongo"))

        assert (
            await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")
            is None
        )

    async def test_a_prompt_generation_failure_yields_none(self, workflow_stack: Any) -> None:
        generation, _ = workflow_stack
        generation.generate_workflow_prompt = AsyncMock(side_effect=RuntimeError("llm"))

        assert (
            await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")
            is None
        )


# ---------------------------------------------------------------------------
# _create_onboarding_workflows
# ---------------------------------------------------------------------------


def _specs(count: int = 4) -> _WorkflowList:
    return _WorkflowList(
        workflows=[_WorkflowSpec(title=f"t{i}", description=f"d{i}") for i in range(count)]
    )


class TestCreateOnboardingWorkflows:
    async def test_builds_one_workflow_per_spec(self) -> None:
        with (
            patch(f"{MODULE}._generate_workflow_specs", AsyncMock(return_value=_specs())),
            patch(
                f"{MODULE}._build_one_workflow",
                AsyncMock(side_effect=[_card(f"w{i}") for i in range(4)]),
            ),
        ):
            result = await _create_onboarding_workflows(_ctx())

        assert [r.id for r in result] == ["w0", "w1", "w2", "w3"]

    async def test_failed_specs_are_dropped_without_failing_the_batch(self) -> None:
        with (
            patch(f"{MODULE}._generate_workflow_specs", AsyncMock(return_value=_specs())),
            patch(
                f"{MODULE}._build_one_workflow",
                AsyncMock(side_effect=[_card("w0"), None, _card("w2"), None]),
            ),
        ):
            result = await _create_onboarding_workflows(_ctx())

        assert [r.id for r in result] == ["w0", "w2"]

    async def test_unknown_integration_ids_are_filtered_out(self) -> None:
        captured: list[Any] = []

        async def build(user_id: str, idx: int, spec: Any, tz: str, selected: Any = None) -> dict:
            captured.append(selected)
            return {"id": f"w{idx}"}

        with (
            patch(f"{MODULE}._generate_workflow_specs", AsyncMock(return_value=_specs())),
            patch(f"{MODULE}._build_one_workflow", AsyncMock(side_effect=build)),
        ):
            await _create_onboarding_workflows(
                _ctx(has_gmail=False), selected_integrations=["slack", "not_real", "slack"]
            )

        assert captured[0] == ["slack"]

    async def test_gmail_is_added_when_connected(self) -> None:
        captured: list[Any] = []

        async def build(user_id: str, idx: int, spec: Any, tz: str, selected: Any = None) -> dict:
            captured.append(selected)
            return {"id": f"w{idx}"}

        with (
            patch(f"{MODULE}._generate_workflow_specs", AsyncMock(return_value=_specs())),
            patch(f"{MODULE}._build_one_workflow", AsyncMock(side_effect=build)),
        ):
            await _create_onboarding_workflows(_ctx(), selected_integrations=["slack"])

        assert captured[0] == ["slack", "gmail"]

    async def test_gmail_is_not_duplicated(self) -> None:
        captured: list[Any] = []

        async def build(user_id: str, idx: int, spec: Any, tz: str, selected: Any = None) -> dict:
            captured.append(selected)
            return {"id": f"w{idx}"}

        with (
            patch(f"{MODULE}._generate_workflow_specs", AsyncMock(return_value=_specs())),
            patch(f"{MODULE}._build_one_workflow", AsyncMock(side_effect=build)),
        ):
            await _create_onboarding_workflows(_ctx(), selected_integrations=["gmail", "slack"])

        assert captured[0] == ["gmail", "slack"]

    async def test_the_rendered_prompt_and_user_reach_the_spec_generator(self) -> None:
        """The prompt IS the whole brief. Losing it (or the user it is billed to)
        still produces four workflows — generic ones, for the wrong meter."""
        with (
            patch(
                f"{MODULE}._build_workflow_prompt_context", return_value="THE PROMPT"
            ) as build_prompt,
            patch(
                f"{MODULE}._generate_workflow_specs", AsyncMock(return_value=_specs())
            ) as generate,
            patch(f"{MODULE}._build_one_workflow", AsyncMock(return_value=_card("w0"))),
        ):
            ctx = _ctx(has_gmail=False)
            await _create_onboarding_workflows(ctx, selected_integrations=["slack"])

        build_prompt.assert_called_once_with(ctx, ["slack"])
        generate.assert_awaited_once_with(USER, "THE PROMPT")

    async def test_no_usable_integrations_reach_the_prompt_as_none_not_an_empty_list(
        self,
    ) -> None:
        """`[]` and `None` render differently downstream: the empty list is the
        \"user picked nothing\" case and must not read as a preference."""
        with (
            patch(f"{MODULE}._build_workflow_prompt_context", return_value="p") as build_prompt,
            patch(f"{MODULE}._generate_workflow_specs", AsyncMock(return_value=_specs())),
            patch(f"{MODULE}._build_one_workflow", AsyncMock(return_value=_card("w0"))),
        ):
            ctx = _ctx(has_gmail=False)
            await _create_onboarding_workflows(ctx, selected_integrations=["not_real"])

        build_prompt.assert_called_once_with(ctx, None)

    async def test_spec_generation_failure_falls_back_to_one_workflow(self) -> None:
        with (
            patch(f"{MODULE}._generate_workflow_specs", AsyncMock(side_effect=RuntimeError("llm"))),
            patch(
                f"{MODULE}._create_fallback_workflow", AsyncMock(return_value=_fallback_cards())
            ) as fallback,
        ):
            result = await _create_onboarding_workflows(_ctx(has_gmail=False))

        assert result == _fallback_cards()
        # No usable integrations here, so the fallback is told None rather than [].
        assert fallback.await_args.args == (USER, "ship v2", "UTC", None)

    async def test_the_fallback_still_gets_the_usable_integrations(self) -> None:
        with (
            patch(f"{MODULE}._generate_workflow_specs", AsyncMock(side_effect=RuntimeError("llm"))),
            patch(
                f"{MODULE}._create_fallback_workflow", AsyncMock(return_value=_fallback_cards())
            ) as fallback,
        ):
            await _create_onboarding_workflows(
                _ctx(has_gmail=False), selected_integrations=["slack"]
            )

        assert fallback.await_args.args == (USER, "ship v2", "UTC", ["slack"])


# ---------------------------------------------------------------------------
# _create_fallback_workflow
# ---------------------------------------------------------------------------

#: The fallback's two fields, verbatim. They are fixed templates, so the tests
#: below pin them exactly rather than sampling a substring.
_FALLBACK_DESCRIPTION = "Summarizes unread emails by priority, today's meetings, and open todos."
_FALLBACK_PROMPT = (
    "1. Summarize my unread emails, most in need of attention first\n"
    "2. List today's meetings with their times\n"
    "3. List my open todos\n\n"
    "Expected output: one short briefing I can read in under a minute."
)


class TestCreateFallbackWorkflow:
    async def test_creates_a_daily_briefing(self) -> None:
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow("fb1"))
            result = await _create_fallback_workflow(USER)

        assert result[0].id == "fb1"
        assert result[0].title == "Daily Briefing"
        assert result[0].trigger.model_dump(mode="json", exclude_none=True) == {
            "type": "schedule",
            "cron_expression": _DEFAULT_WORKFLOW_CRON,
        }

    async def test_focus_is_woven_into_the_description(self) -> None:
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow())
            result = await _create_fallback_workflow(USER, "close Q3 deals")

        assert "close Q3 deals" in result[0].description

    async def test_without_focus_a_generic_description_is_used(self) -> None:
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow())
            result = await _create_fallback_workflow(USER, "")

        assert "Focus:" not in result[0].description

    async def test_the_prompt_is_instructions_not_the_card_copy(self) -> None:
        """This prompt is what the executor reads as the run's goal. It used to be
        the description, which opened "Every morning at 9am" — config the scheduler
        has already acted on by the time the agent sees it. Asserted in full: it is
        a fixed template, so anything less lets a reworded step through."""
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow())
            await _create_fallback_workflow(USER)

        request = service.create_workflow.await_args.args[0]
        assert request.prompt == _FALLBACK_PROMPT
        assert request.description == _FALLBACK_DESCRIPTION
        assert request.prompt != request.description

    async def test_a_long_focus_is_truncated_into_both_fields(self) -> None:
        focus = "shipping the billing rewrite " * 8  # comfortably over the 100-char cap
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow())
            await _create_fallback_workflow(USER, focus)

        request = service.create_workflow.await_args.args[0]
        assert request.description == f"{_FALLBACK_DESCRIPTION} Focus: {focus[:100]}."
        assert request.prompt == (
            f"{_FALLBACK_PROMPT}\n\nWeight everything toward what matters for: {focus[:100]}."
        )

    async def test_integration_ids_are_forwarded(self) -> None:
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow())
            await _create_fallback_workflow(USER, "", "UTC", ["gmail"])

        assert service.create_workflow.await_args.args[0].integration_ids == ["gmail"]

    async def test_a_failure_yields_an_empty_list(self) -> None:
        # This is the last resort; raising here would abort the whole pipeline.
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(side_effect=RuntimeError("mongo"))
            assert await _create_fallback_workflow(USER) == []


# ---------------------------------------------------------------------------
# _run_holo_card
# ---------------------------------------------------------------------------


@pytest.fixture
def holo_stack() -> Any:
    with (
        patch(
            f"{MODULE}.get_user_metadata",
            AsyncMock(return_value=UserProfileMetadata(account_number=1, member_since="2026")),
        ),
        patch(
            f"{MODULE}.generate_profile_card_design",
            return_value=ProfileCardDesign(
                house="mistgrove", overlay_color="#fff", overlay_opacity=20
            ),
        ),
        patch(
            f"{MODULE}.generate_holo_card_content",
            AsyncMock(return_value=("a phrase", "a bio", "ok")),
        ) as content,
        patch(f"{MODULE}.save_personalization_data", AsyncMock()) as save,
        patch(f"{MODULE}._emit_stage", AsyncMock()) as emit,
    ):
        yield content, save, emit


class TestRunHoloCard:
    async def test_saves_the_generated_card_and_announces_readiness(self, holo_stack: Any) -> None:
        _, save, emit = holo_stack
        user = UserDocument(id=USER)
        with patch(
            f"{MODULE}.get_user_metadata",
            AsyncMock(return_value=UserProfileMetadata(account_number=1, member_since="2026")),
        ) as metadata:
            await _run_holo_card(_ctx(focus="focus"), user)

        args = save.await_args.args
        assert args[0] == USER
        assert args[1] == "mistgrove"
        assert args[2] == "a phrase"
        # Both the id and the already-loaded document: without the document the
        # lookup re-reads Mongo, without the id it reads the wrong person.
        metadata.assert_awaited_once_with(USER, user=user)
        assert emit.await_args.args[0] == USER
        assert emit.await_args.args[1] is OnboardingStage.HOLO_READY

    async def test_context_summary_gathers_every_available_signal(self, holo_stack: Any) -> None:
        content, _, _ = holo_stack
        await _run_holo_card(
            OnboardingContext(
                user_id=USER,
                name="Ann",
                focus="ship v2",
                triage=_triage(
                    important_emails=[
                        EmailSummary(sender="ann@x.com", subject="Contract", why_important="d"),
                        EmailSummary(sender="bob@x.com", subject="Invoice", why_important="d"),
                    ],
                    patterns=["newsletters", "receipts"],
                ),
                writing_style=WritingStyleProfile(
                    summary="Terse", example=WritingStyleExampleBlocks(body=["x"])
                ),
                clarify_answers=[{"kind": "goal", "value": "grow the team"}],
            ),
            UserDocument(id=USER),
            [SocialProfile(platform="x", url="u1")],
        )

        summary = content.await_args.args[1]
        assert "Busy inbox" in summary
        # Exact separators, from multi-element lists: with one element a wrong
        # join string never appears in the output at all.
        assert "Inbox patterns: newsletters; receipts" in summary
        assert "Key contacts: ann@x.com, bob@x.com" in summary
        assert "Terse" in summary
        assert "x: u1" in summary
        assert "ship v2" in summary
        assert "Goal: grow the team" in summary

    async def test_only_the_top_five_contacts_reach_the_card(self, holo_stack: Any) -> None:
        """The cap keeps the card prompt bounded; slipping it by one is invisible
        in every fixture with fewer than six important emails."""
        content, _, _ = holo_stack
        emails = [
            EmailSummary(sender=f"s{i}@x.com", subject="s", why_important="w") for i in range(6)
        ]
        await _run_holo_card(
            _ctx(focus="", triage=_triage(important_emails=emails)), UserDocument(id=USER)
        )

        summary = content.await_args.args[1]
        assert "Key contacts: s0@x.com, s1@x.com, s2@x.com, s3@x.com, s4@x.com" in summary
        assert "s5@x.com" not in summary

    async def test_blank_clarify_answers_are_skipped(self, holo_stack: Any) -> None:
        content, _, _ = holo_stack
        await _run_holo_card(
            _ctx(focus="", clarify_answers=[{"kind": "goal", "value": "   "}]),
            UserDocument(id=USER),
        )

        assert "Goal" not in content.await_args.args[1]

    async def test_a_clarify_answer_without_a_kind_defaults_to_context(
        self, holo_stack: Any
    ) -> None:
        content, _, _ = holo_stack
        await _run_holo_card(
            _ctx(focus="", clarify_answers=[{"value": "some note"}]), UserDocument(id=USER)
        )

        assert "Context: some note" in content.await_args.args[1]

    async def test_absent_signals_produce_an_empty_summary(self, holo_stack: Any) -> None:
        content, _, _ = holo_stack
        await _run_holo_card(_ctx(focus=""), UserDocument(id=USER))

        assert content.await_args.args[1] == ""

    async def test_a_failure_still_announces_readiness(self, holo_stack: Any) -> None:
        # The frontend waits on HOLO_READY; skipping it leaves the card spinning.
        _, _, emit = holo_stack
        with patch(f"{MODULE}.get_user_metadata", AsyncMock(side_effect=RuntimeError("mongo"))):
            await _run_holo_card(_ctx(focus=""), UserDocument(id=USER))

        assert emit.await_args.args[1] is OnboardingStage.HOLO_READY


# ---------------------------------------------------------------------------
# _wait_for_early_phase
# ---------------------------------------------------------------------------


class TestWaitForEarlyPhase:
    async def test_returns_true_once_the_marker_appears(self) -> None:
        user = MagicMock()
        user.onboarding = {"early_intelligence_done_at": "2026-07-27T00:00:00Z"}
        with patch(f"{MODULE}.user_repository") as repo:
            repo.get = AsyncMock(return_value=user)
            assert await _wait_for_early_phase(USER) is True

    async def test_polls_until_the_marker_is_written(self) -> None:
        pending, done = MagicMock(), MagicMock()
        pending.onboarding = {}
        done.onboarding = {"early_intelligence_done_at": "t"}

        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
        ):
            repo.get = AsyncMock(side_effect=[pending, pending, done])
            assert await _wait_for_early_phase(USER) is True
            assert repo.get.await_count == 3

    async def test_a_missing_user_keeps_polling(self) -> None:
        done = MagicMock()
        done.onboarding = {"early_intelligence_done_at": "t"}
        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
        ):
            repo.get = AsyncMock(side_effect=[None, done])
            assert await _wait_for_early_phase(USER) is True

    async def test_returns_false_when_the_deadline_passes(self) -> None:
        # The caller proceeds with whatever is persisted rather than hanging.
        pending = MagicMock()
        pending.onboarding = {}
        clock = iter([0.0] + [1000.0] * 10)

        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
            patch(f"{MODULE}.time.monotonic", side_effect=lambda: next(clock)),
        ):
            repo.get = AsyncMock(return_value=pending)
            assert await _wait_for_early_phase(USER) is False

    async def test_a_user_with_no_onboarding_subdoc_is_tolerated(self) -> None:
        user = MagicMock()
        user.onboarding = None
        clock = iter([0.0] + [1000.0] * 10)

        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
            patch(f"{MODULE}.time.monotonic", side_effect=lambda: next(clock)),
        ):
            repo.get = AsyncMock(return_value=user)
            assert await _wait_for_early_phase(USER) is False
