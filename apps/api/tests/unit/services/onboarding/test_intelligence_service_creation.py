"""Unit tests for the todo/workflow creation and holo-card nodes.

These are the nodes that turn LLM output into persisted records, so the tests
concentrate on what happens when the model returns too much, too little, or
fabricated data, and on partial persistence failures. Only the LLM client, the
todo/workflow services and the repositories are faked.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.onboarding import (
    EARLY_PHASE_POLL_INTERVAL_S,
    EARLY_PHASE_WAIT_TIMEOUT_S,
    NOT_SPECIFIED,
    OAUTH_INTEGRATION_NAME_BY_ID,
)
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
from app.models.todo_models import Priority
from app.models.user_models import UserDocument
from app.models.workflow_models import (
    IntegrationRef,
    SuggestedTrigger,
    TriggerConfig,
    TriggerType,
)
from app.services.onboarding.intelligence_service import (
    _DEFAULT_WORKFLOW_CRON,
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


def _style(summary: str = "Terse") -> WritingStyleProfile:
    return WritingStyleProfile(summary=summary, example=WritingStyleExampleBlocks(body=["Thanks."]))


def _registered_trigger_slugs() -> tuple[str, str]:
    """(config-free slug, config-bearing slug) from the real oauth registry, so
    the integration-suggestion tests exercise the real schema lookup."""
    from app.config.oauth_config import OAUTH_INTEGRATIONS

    config_free: str | None = None
    config_bearing: str | None = None
    for integration in OAUTH_INTEGRATIONS:
        for tc in integration.associated_triggers or []:
            schema = tc.workflow_trigger_schema
            if not schema:
                continue
            if config_free is None and not schema.config_schema:
                config_free = str(schema.slug)
            if config_bearing is None and schema.config_schema:
                config_bearing = str(schema.slug)
    if config_free is None or config_bearing is None:
        pytest.skip("workflow trigger schemas missing from oauth registry")
    return config_free, config_bearing


# ---------------------------------------------------------------------------
# _create_focus_todos
# ---------------------------------------------------------------------------


class TestCreateFocusTodos:
    async def test_creates_one_todo_per_generated_title(self) -> None:
        parsed = _FocusTodoList(todos=["Draft the brief", "Book the review"])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
            patch(f"{MODULE}.log") as log,
        ):
            service.create_todo = AsyncMock(side_effect=[_made_todo("t1"), _made_todo("t2")])
            result = await _create_focus_todos(USER, "Ann", "lawyer", "close Q3")

        assert result == [
            OnboardingTodoSummary(id="t1", title="Draft the brief"),
            OnboardingTodoSummary(id="t2", title="Book the review"),
        ]
        done = [c for c in log.info.call_args_list if "focus_todos done" in str(c)]
        assert done, "no focus_todos completion line emitted"
        assert done[-1].kwargs["user_id"] == USER
        assert done[-1].kwargs["step"] == "todos_focus"
        assert done[-1].kwargs["outcome"] == "ok"
        assert done[-1].kwargs["specs_count"] == 2
        assert done[-1].kwargs["created_count"] == 2
        assert isinstance(done[-1].kwargs["llm_duration_s"], float)
        assert isinstance(done[-1].kwargs["create_duration_s"], float)
        assert isinstance(done[-1].kwargs["duration_s"], float)

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
        assert [r.title for r in result] == ["Task 0", "Task 1", "Task 2"]

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
            patch(f"{MODULE}.log") as log,
        ):
            service.create_todo = AsyncMock(
                side_effect=[_made_todo("t1"), RuntimeError("mongo"), _made_todo("t3")]
            )
            result = await _create_focus_todos(USER, "Ann", "lawyer", "close Q3")

        assert [r.id for r in result] == ["t1", "t3"]
        warns = [c for c in log.warning.call_args_list if "focus todo create failed" in str(c)]
        assert warns, "failed todo creation was not logged"
        assert warns[-1].kwargs["user_id"] == USER
        assert warns[-1].kwargs["step"] == "todos_focus_create_one"
        assert warns[-1].kwargs["title"] == "B"
        assert warns[-1].kwargs["error"] == "mongo"
        assert warns[-1].kwargs["error_type"] == "RuntimeError"

    async def test_a_long_title_and_error_are_trimmed_in_the_failure_log(self) -> None:
        # The log caps the title at 60 chars and the error at 200 — off-by-one
        # slices would leak truncated garbage into the wide-event stream.
        long_title = "x" * 100
        long_error = "e" * 300
        parsed = _FocusTodoList(todos=[long_title])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
            patch(f"{MODULE}.log") as log,
        ):
            service.create_todo = AsyncMock(side_effect=RuntimeError(long_error))
            await _create_focus_todos(USER, "Ann", "lawyer", "close Q3")

        warns = [c for c in log.warning.call_args_list if "focus todo create failed" in str(c)]
        assert warns[-1].kwargs["title"] == "x" * 60
        assert warns[-1].kwargs["error"] == "e" * 200

    async def test_an_llm_failure_degrades_to_an_empty_list(self) -> None:
        long_error = "e" * 300
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(side_effect=RuntimeError(long_error))),
            patch(f"{MODULE}.log") as log,
        ):
            assert await _create_focus_todos(USER, "Ann", "lawyer", "close Q3") == []

        warns = [c for c in log.warning.call_args_list if "focus_todos failed" in str(c)]
        assert warns, "llm failure was not logged"
        assert warns[-1].kwargs["user_id"] == USER
        assert warns[-1].kwargs["step"] == "todos_focus"
        assert warns[-1].kwargs["outcome"] == "failed"
        assert warns[-1].kwargs["error"] == "e" * 200
        assert warns[-1].kwargs["error_type"] == "RuntimeError"
        assert isinstance(warns[-1].kwargs["duration_s"], float)

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

    async def test_the_llm_call_and_prompt_are_exact(self) -> None:
        # Every input the model could anchor on must reach the prompt, and the
        # call itself must be shaped like the other onboarding LLM calls.
        llm = AsyncMock(return_value=_FocusTodoList(todos=[]))
        with (
            patch(f"{MODULE}.ainvoke_structured", llm),
            patch(f"{MODULE}.metered_config", return_value="METERED") as metered,
        ):
            await _create_focus_todos(USER, "Ann", "lawyer", "close Q3", [{"kind": "goal", "value": "grow"}])

        args, kwargs = llm.await_args
        assert args[0] is _FocusTodoList
        assert kwargs["label"] == "onboarding_focus_todos"
        assert kwargs["config"] == "METERED"
        assert metered.call_args.args == (USER,)

        prompt = args[1]
        assert "Ann" in prompt
        assert "lawyer" in prompt
        assert "close Q3" in prompt
        assert "- Goal: grow" in prompt
        assert prompt.endswith(
            f"Return a JSON object with a 'todos' key containing a list of {ONBOARDING_TODO_LIMIT} todo title strings."
        )

    async def test_the_todo_record_is_built_exactly(self) -> None:
        parsed = _FocusTodoList(todos=["Draft the brief"])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo("t1"))
            await _create_focus_todos(USER, "Ann", "lawyer", "close Q3")

        todo, user_id = service.create_todo.await_args.args
        assert todo.title == "Draft the brief"
        assert todo.description == "Created from your focus: close Q3"
        assert todo.labels == ["onboarding"]
        assert todo.priority is Priority.MEDIUM
        assert "project_id" in todo.model_fields_set
        assert todo.project_id is None
        assert user_id == USER

    async def test_an_exactly_80_char_title_is_untouched(self) -> None:
        # The boundary that decides whether truncation happens at all — a <
        # instead of <= would chop the last word off a title that fits exactly.
        title = " ".join(c * 8 for c in "abcdefghi")
        assert len(title) == 80
        parsed = _FocusTodoList(todos=[title])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            result = await _create_focus_todos(USER, "Ann", "lawyer", "close Q3")

        assert result[0].title == title

    async def test_a_focus_over_200_chars_is_capped_in_the_description(self) -> None:
        parsed = _FocusTodoList(todos=["Draft the brief"])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            await _create_focus_todos(USER, "Ann", "lawyer", "f" * 250)

        assert (
            service.create_todo.await_args.args[0].description
            == f"Created from your focus: {'f' * 200}"
        )


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
            patch(f"{MODULE}.log") as log,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo("t1"))
            result = await _create_todos_from_triage(USER, _triage())

        assert result == [OnboardingTodoSummary(id="t1", title="Reply to Ann")]
        done = [c for c in log.info.call_args_list if "triage_todos done" in str(c)]
        assert done, "no triage_todos completion line emitted"
        assert done[-1].kwargs["user_id"] == USER
        assert done[-1].kwargs["step"] == "todos_triage"
        assert done[-1].kwargs["outcome"] == "ok"
        assert done[-1].kwargs["specs_count"] == 1
        assert done[-1].kwargs["created_count"] == 1
        assert isinstance(done[-1].kwargs["llm_duration_s"], float)
        assert isinstance(done[-1].kwargs["create_duration_s"], float)
        assert isinstance(done[-1].kwargs["duration_s"], float)

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
        assert [r.title for r in result] == ["T0", "T1", "T2"]

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
            patch(f"{MODULE}.log") as log,
        ):
            service.create_todo = AsyncMock(side_effect=[RuntimeError("mongo"), _made_todo("t2")])
            result = await _create_todos_from_triage(USER, _triage())

        assert [r.id for r in result] == ["t2"]
        warns = [c for c in log.warning.call_args_list if "Failed to create todo" in str(c)]
        assert warns, "failed todo creation was not logged"
        assert warns[-1].kwargs["error"] == "mongo"
        assert warns[-1].kwargs["error_type"] == "RuntimeError"

    async def test_an_llm_failure_degrades_to_an_empty_list(self) -> None:
        long_error = "e" * 300
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(side_effect=RuntimeError(long_error))),
            patch(f"{MODULE}.log") as log,
        ):
            assert await _create_todos_from_triage(USER, _triage()) == []

        warns = [c for c in log.warning.call_args_list if "triage_todos failed" in str(c)]
        assert warns, "llm failure was not logged"
        assert warns[-1].kwargs["user_id"] == USER
        assert warns[-1].kwargs["step"] == "todos_triage"
        assert warns[-1].kwargs["outcome"] == "failed"
        assert warns[-1].kwargs["error"] == "e" * 200
        assert warns[-1].kwargs["error_type"] == "RuntimeError"
        assert isinstance(warns[-1].kwargs["duration_s"], float)

    async def test_default_profession_and_focus_are_marked_not_specified(self) -> None:
        # The signature defaults ("" for both) must behave exactly like explicit
        # blanks — a mutated default would leak into the prompt.
        llm = AsyncMock(return_value=_TodoListFromEmails(todos=[]))
        with patch(f"{MODULE}.ainvoke_structured", llm):
            await _create_todos_from_triage(USER, _triage())

        assert llm.await_args.args[1].count(NOT_SPECIFIED) >= 2

    async def test_blank_profession_and_focus_are_marked_not_specified(self) -> None:
        llm = AsyncMock(return_value=_TodoListFromEmails(todos=[]))
        with patch(f"{MODULE}.ainvoke_structured", llm):
            await _create_todos_from_triage(USER, _triage(), profession="", focus="")

        assert llm.await_args.args[1].count(NOT_SPECIFIED) >= 2

    async def test_the_prompt_and_llm_call_are_exact(self) -> None:
        # The grounded window, the real senders/subjects, and the instructions
        # all ride the prompt — the model can only ground on what it was given.
        triage = _triage(
            important_emails=[
                EmailSummary(sender=f"s{i}@x.com", subject=f"sub{i}", why_important=f"w{i}")
                for i in range(8)
            ]
        )
        llm = AsyncMock(return_value=_TodoListFromEmails(todos=[]))
        with (
            patch(f"{MODULE}.ainvoke_structured", llm),
            patch(f"{MODULE}.metered_config", return_value="METERED") as metered,
        ):
            await _create_todos_from_triage(USER, triage, profession="lawyer", focus="close Q3")

        args, kwargs = llm.await_args
        assert args[0] is _TodoListFromEmails
        assert kwargs["label"] == "onboarding_todos_from_emails"
        assert kwargs["config"] == "METERED"
        assert metered.call_args.args == (USER,)

        prompt = args[1]
        expected_lines = [
            f"- From: s{i}@x.com | Subject: sub{i} | Why important: w{i}" for i in range(8)
        ]
        assert "\n".join(expected_lines) in prompt
        assert "lawyer" in prompt
        assert "close Q3" in prompt
        assert prompt.endswith(
            "Return a JSON object with a 'todos' key containing a list of todo objects, "
            "each with 'title', 'description', 'source_sender', and 'source_subject'."
        )

    async def test_a_lone_hallucinated_sender_is_logged(self) -> None:
        # Sender claimed, no subject claim: the elif must still treat it as a
        # fabricated citation and warn, not silently attach or silently drop.
        parsed = _TodoListFromEmails(todos=[_spec(source_sender="ghost@x.com", source_subject="")])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
            patch(f"{MODULE}.log") as log,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo())
            result = await _create_todos_from_triage(USER, _triage())

        assert result[0].source_email is None
        warns = [c for c in log.warning.call_args_list if "Dropped hallucinated source_email" in str(c)]
        assert warns, "hallucinated citation was not logged"
        assert warns[-1].kwargs["source_sender"] == "ghost@x.com"
        assert warns[-1].kwargs["source_subject"] == ""

    async def test_the_todo_record_is_built_exactly(self) -> None:
        parsed = _TodoListFromEmails(todos=[_spec(title="Reply to Ann", description="About the contract")])
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=parsed)),
            patch(f"{MODULE}.TodoService") as service,
        ):
            service.create_todo = AsyncMock(return_value=_made_todo("t1"))
            await _create_todos_from_triage(USER, _triage())

        todo, user_id = service.create_todo.await_args.args
        assert todo.title == "Reply to Ann"
        assert todo.description == "About the contract"
        assert todo.labels == ["onboarding"]
        assert todo.priority is Priority.MEDIUM
        assert "project_id" in todo.model_fields_set
        assert todo.project_id is None
        assert user_id == USER


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
        with patch(f"{MODULE}.log") as log:
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
        done = [c for c in log.info.call_args_list if "workflow spec done" in str(c)]
        assert done, "no workflow spec completion line emitted"
        assert done[-1].kwargs["user_id"] == USER
        assert done[-1].kwargs["step"] == "workflows_spec"
        assert done[-1].kwargs["spec_index"] == 0
        assert done[-1].kwargs["spec_title"] == "Daily brief"
        assert done[-1].kwargs["trigger_type"] == "schedule"
        assert done[-1].kwargs["workflow_id"] == "w1"
        assert isinstance(done[-1].kwargs["prompt_duration_s"], float)
        assert isinstance(done[-1].kwargs["create_duration_s"], float)
        assert isinstance(done[-1].kwargs["duration_s"], float)

    async def test_the_spec_title_is_trimmed_in_the_log(self, workflow_stack: Any) -> None:
        # The log caps the spec title at 60 chars; an off-by-one slice would
        # leak the tail of a long title into the wide-event stream.
        long_title = "t" * 100
        with (
            patch(f"{MODULE}.log") as log,
        ):
            await _build_one_workflow(USER, 0, _WorkflowSpec(title=long_title, description="d"), "UTC")

        done = [c for c in log.info.call_args_list if "workflow spec done" in str(c)]
        assert done[-1].kwargs["spec_title"] == "t" * 60

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

        with patch(f"{MODULE}.log") as log:
            result = await _build_one_workflow(
                USER, 0, _WorkflowSpec(title="t", description="d"), "UTC"
            )

        assert result is None
        warns = [c for c in log.warning.call_args_list if "workflow spec failed" in str(c)]
        assert warns, "workflow spec failure was not logged"
        assert warns[-1].kwargs["user_id"] == USER
        assert warns[-1].kwargs["step"] == "workflows_spec"
        assert warns[-1].kwargs["spec_index"] == 0
        assert warns[-1].kwargs["spec_title"] == "t"
        assert warns[-1].kwargs["error"] == "mongo"
        assert warns[-1].kwargs["error_type"] == "RuntimeError"
        assert isinstance(warns[-1].kwargs["duration_s"], float)

    async def test_a_long_error_is_trimmed_in_the_failure_log(self, workflow_stack: Any) -> None:
        # The log caps the error at 200 chars; an off-by-one slice would leak
        # the tail of a long traceback message into the wide-event stream.
        _, service = workflow_stack
        long_error = "e" * 300
        service.create_workflow = AsyncMock(side_effect=RuntimeError(long_error))

        with patch(f"{MODULE}.log") as log:
            await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        warns = [c for c in log.warning.call_args_list if "workflow spec failed" in str(c)]
        assert warns[-1].kwargs["error"] == "e" * 200

    async def test_a_prompt_generation_failure_yields_none(self, workflow_stack: Any) -> None:
        generation, _ = workflow_stack
        generation.generate_workflow_prompt = AsyncMock(side_effect=RuntimeError("llm"))

        assert (
            await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")
            is None
        )

    async def test_the_prompt_generator_is_called_with_the_spec(self, workflow_stack: Any) -> None:
        generation, _ = workflow_stack
        await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        assert generation.generate_workflow_prompt.await_args.kwargs == {
            "title": "t",
            "description": "d",
            "user_id": USER,
        }

    async def test_the_request_carries_every_field(self, workflow_stack: Any) -> None:
        _, service = workflow_stack
        await _build_one_workflow(
            USER, 0, _WorkflowSpec(title="t", description="d", categories=["gmail"]), "UTC", ["slack"]
        )

        request, user_id = service.create_workflow.await_args.args
        assert request.title == "t"
        assert request.description == "d"
        assert request.prompt == "generated prompt"
        assert request.trigger_config == TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON
        )
        assert request.generate_immediately is True
        assert request.integration_ids == ["gmail"]
        assert user_id == USER
        assert service.create_workflow.await_args.kwargs["user_timezone"] == "UTC"

    async def test_a_whitespace_only_generated_prompt_is_rejected(self, workflow_stack: Any) -> None:
        # "   " is truthy so it never reaches the `or spec.description` fallback;
        # after the strip it is empty, which CreateWorkflowRequest rejects
        # (prompt min_length=1) and the spec is dropped rather than persisted.
        generation, _ = workflow_stack
        generation.generate_workflow_prompt = AsyncMock(
            return_value={"prompt": "   ", "suggested_trigger": None}
        )

        assert (
            await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="the desc"), "UTC")
            is None
        )

    async def test_integration_ids_fall_back_to_the_selection(self, workflow_stack: Any) -> None:
        _, service = workflow_stack
        await _build_one_workflow(
            USER, 0, _WorkflowSpec(title="t", description="d", categories=[]), "UTC", ["slack"]
        )

        assert service.create_workflow.await_args.args[0].integration_ids == ["slack"]

    async def test_integration_ids_are_none_when_nothing_is_known(
        self, workflow_stack: Any
    ) -> None:
        # [] would pin the workflow to zero integrations; None leaves step
        # generation unconstrained.
        _, service = workflow_stack
        await _build_one_workflow(
            USER, 0, _WorkflowSpec(title="t", description="d", categories=[]), "UTC", []
        )

        assert service.create_workflow.await_args.args[0].integration_ids is None

    async def test_missing_integration_computation_receives_the_persisted_workflow(
        self, workflow_stack: Any
    ) -> None:
        _, service = workflow_stack
        saved = _workflow()
        saved.steps = [MagicMock()]
        saved.trigger_config = TriggerConfig(type=TriggerType.MANUAL)
        service.create_workflow = AsyncMock(return_value=saved)

        with (
            patch(f"{MODULE}.compute_required_integrations", return_value=["req"]) as required,
            patch(f"{MODULE}.compute_missing_integrations", AsyncMock(return_value=[])) as missing,
        ):
            await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        assert required.call_args.args == (saved.steps, saved.trigger_config)
        assert missing.await_args.args == (["req"], USER)

    @pytest.mark.parametrize("cron", [None, "", "   "])
    async def test_a_blank_schedule_cron_falls_back_to_the_default(
        self, workflow_stack: Any, cron: str | None
    ) -> None:
        generation, service = workflow_stack
        generation.generate_workflow_prompt = AsyncMock(
            return_value={
                "prompt": "p",
                "suggested_trigger": SuggestedTrigger(type="schedule", cron_expression=cron),
            }
        )
        await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        assert service.create_workflow.await_args.args[0].trigger_config == TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON
        )

    async def test_a_schedule_suggestion_keeps_its_cron(self, workflow_stack: Any) -> None:
        generation, service = workflow_stack
        generation.generate_workflow_prompt = AsyncMock(
            return_value={
                "prompt": "p",
                "suggested_trigger": SuggestedTrigger(
                    type="schedule", cron_expression="30 7 * * 1-5"
                ),
            }
        )
        await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        assert service.create_workflow.await_args.args[0].trigger_config == TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression="30 7 * * 1-5"
        )

    @pytest.mark.parametrize("trigger_type", ["manual", "MANUAL", "Manual"])
    async def test_a_manual_suggestion_maps_to_a_manual_trigger(
        self, workflow_stack: Any, trigger_type: str
    ) -> None:
        generation, service = workflow_stack
        generation.generate_workflow_prompt = AsyncMock(
            return_value={
                "prompt": "p",
                "suggested_trigger": SuggestedTrigger(type=trigger_type),
            }
        )
        await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        assert service.create_workflow.await_args.args[0].trigger_config == TriggerConfig(
            type=TriggerType.MANUAL
        )

    async def test_an_integration_suggestion_without_a_name_falls_back(
        self, workflow_stack: Any
    ) -> None:
        generation, service = workflow_stack
        generation.generate_workflow_prompt = AsyncMock(
            return_value={"prompt": "p", "suggested_trigger": SuggestedTrigger(type="integration")}
        )
        await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        assert service.create_workflow.await_args.args[0].trigger_config == TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON
        )

    async def test_an_unknown_trigger_slug_falls_back(self, workflow_stack: Any) -> None:
        generation, service = workflow_stack
        generation.generate_workflow_prompt = AsyncMock(
            return_value={
                "prompt": "p",
                "suggested_trigger": SuggestedTrigger(
                    type="integration", trigger_name="NOT_A_REAL_TRIGGER"
                ),
            }
        )
        await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        assert service.create_workflow.await_args.args[0].trigger_config == TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON
        )

    async def test_a_config_free_integration_slug_becomes_an_integration_trigger(
        self, workflow_stack: Any
    ) -> None:
        generation, service = workflow_stack
        slug, _ = _registered_trigger_slugs()
        generation.generate_workflow_prompt = AsyncMock(
            return_value={
                "prompt": "p",
                "suggested_trigger": SuggestedTrigger(type="integration", trigger_name=slug),
            }
        )
        await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        assert service.create_workflow.await_args.args[0].trigger_config == TriggerConfig(
            type=TriggerType.INTEGRATION, trigger_name=slug
        )

    async def test_a_config_bearing_integration_slug_falls_back_to_a_schedule(
        self, workflow_stack: Any
    ) -> None:
        generation, service = workflow_stack
        _, slug = _registered_trigger_slugs()
        generation.generate_workflow_prompt = AsyncMock(
            return_value={
                "prompt": "p",
                "suggested_trigger": SuggestedTrigger(type="integration", trigger_name=slug),
            }
        )
        await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        assert service.create_workflow.await_args.args[0].trigger_config == TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON
        )

    async def test_an_unknown_suggestion_type_falls_back(self, workflow_stack: Any) -> None:
        generation, service = workflow_stack
        generation.generate_workflow_prompt = AsyncMock(
            return_value={
                "prompt": "p",
                "suggested_trigger": SuggestedTrigger(type="telepathy"),
            }
        )
        await _build_one_workflow(USER, 0, _WorkflowSpec(title="t", description="d"), "UTC")

        assert service.create_workflow.await_args.args[0].trigger_config == TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON
        )

    async def test_the_persisted_trigger_with_optional_fields_is_echoed(
        self, workflow_stack: Any
    ) -> None:
        _, service = workflow_stack
        saved = _workflow()
        saved.trigger_config = TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="GMAIL_NEW_GMAIL_MESSAGE",
            timezone="Europe/London",
        )
        service.create_workflow = AsyncMock(return_value=saved)

        result = await _build_one_workflow(
            USER, 0, _WorkflowSpec(title="t", description="d"), "UTC"
        )

        assert result is not None
        assert result.trigger.model_dump(mode="json", exclude_none=True) == {
            "type": "integration",
            "trigger_name": "GMAIL_NEW_GMAIL_MESSAGE",
            "timezone": "Europe/London",
        }


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
            patch(f"{MODULE}.log") as log,
        ):
            result = await _create_onboarding_workflows(USER, "dev", True)

        assert [r.id for r in result] == ["w0", "w1", "w2", "w3"]
        generated = [c for c in log.info.call_args_list if "workflow specs generated" in str(c)]
        assert generated, "no specs-generation line emitted"
        assert generated[-1].kwargs["user_id"] == USER
        assert generated[-1].kwargs["step"] == "workflows_specs_llm"
        assert generated[-1].kwargs["specs_count"] == 4
        assert isinstance(generated[-1].kwargs["llm_duration_s"], float)

    async def test_default_focus_and_timezone_are_used(self) -> None:
        # The signature defaults ("", "UTC") must behave exactly like explicit
        # blanks — mutated defaults would leak into the prompt or the spec build.
        calls: list[tuple[Any, ...]] = []

        async def build(user_id: str, idx: int, spec: Any, tz: str, selected: Any = None) -> dict:
            calls.append((user_id, idx, tz, selected))
            return {"id": f"w{idx}"}

        llm = AsyncMock(return_value=_specs())
        with (
            patch(f"{MODULE}._generate_workflow_specs", llm),
            patch(f"{MODULE}._build_one_workflow", AsyncMock(side_effect=build)),
        ):
            await _create_onboarding_workflows(USER, "", False)

        assert calls[0][2] == "UTC"
        assert NOT_SPECIFIED in llm.await_args.args[1]

    async def test_failed_specs_are_dropped_without_failing_the_batch(self) -> None:
        with (
            patch(f"{MODULE}._generate_workflow_specs", AsyncMock(return_value=_specs())),
            patch(
                f"{MODULE}._build_one_workflow",
                AsyncMock(side_effect=[_card("w0"), None, _card("w2"), None]),
            ),
        ):
            result = await _create_onboarding_workflows(USER, "dev", True)

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
                USER, "dev", False, selected_integrations=["slack", "not_real", "slack"]
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
            await _create_onboarding_workflows(USER, "dev", True, selected_integrations=["slack"])

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
            await _create_onboarding_workflows(
                USER, "dev", True, selected_integrations=["gmail", "slack"]
            )

        assert captured[0] == ["gmail", "slack"]

    async def test_spec_generation_failure_falls_back_to_one_workflow(self) -> None:
        long_error = "e" * 300
        with (
            patch(
                f"{MODULE}._generate_workflow_specs", AsyncMock(side_effect=RuntimeError(long_error))
            ),
            patch(
                f"{MODULE}._create_fallback_workflow", AsyncMock(return_value=_fallback_cards())
            ) as fallback,
            patch(f"{MODULE}.log") as log,
        ):
            result = await _create_onboarding_workflows(USER, "dev", True, "ship v2", "UTC")

        assert result == _fallback_cards()
        assert fallback.await_args.args == (USER, "ship v2", "UTC", ["gmail"])
        warns = [c for c in log.warning.call_args_list if "workflow LLM failed" in str(c)]
        assert warns, "spec-generation failure was not logged"
        assert warns[-1].kwargs["user_id"] == USER
        assert warns[-1].kwargs["step"] == "workflows"
        assert warns[-1].kwargs["error"] == "e" * 200
        assert warns[-1].kwargs["error_type"] == "RuntimeError"
        assert warns[-1].kwargs["fallback_used"] is True

    async def test_failed_specs_are_counted_in_the_log(self) -> None:
        with (
            patch(f"{MODULE}._generate_workflow_specs", AsyncMock(return_value=_specs())),
            patch(
                f"{MODULE}._build_one_workflow",
                AsyncMock(side_effect=[_card("w0"), None, _card("w2"), None]),
            ),
            patch(f"{MODULE}.log") as log,
        ):
            await _create_onboarding_workflows(USER, "dev", True)

        done = [c for c in log.info.call_args_list if "workflows specs done" in str(c)]
        assert done, "no spec-batch completion line emitted"
        assert done[-1].kwargs["user_id"] == USER
        assert done[-1].kwargs["step"] == "workflows_specs"
        assert done[-1].kwargs["specs_total"] == 4
        assert done[-1].kwargs["specs_created"] == 2
        assert done[-1].kwargs["specs_failed"] == 2
        assert done[-1].kwargs["fallback_used"] is False
        assert isinstance(done[-1].kwargs["specs_llm_duration_s"], float)
        assert isinstance(done[-1].kwargs["duration_s"], float)

    async def test_each_spec_is_built_in_order_with_full_context(self) -> None:
        calls: list[tuple[Any, ...]] = []

        async def build(user_id: str, idx: int, spec: Any, tz: str, selected: Any = None) -> dict:
            calls.append((user_id, idx, spec.title, tz, selected))
            return {"id": f"w{idx}"}

        with (
            patch(f"{MODULE}._generate_workflow_specs", AsyncMock(return_value=_specs())),
            patch(f"{MODULE}._build_one_workflow", AsyncMock(side_effect=build)),
        ):
            await _create_onboarding_workflows(
                USER, "dev", True, "", "Europe/London", None, None, None, ["slack"]
            )

        assert calls == [
            (USER, 0, "t0", "Europe/London", ["slack", "gmail"]),
            (USER, 1, "t1", "Europe/London", ["slack", "gmail"]),
            (USER, 2, "t2", "Europe/London", ["slack", "gmail"]),
            (USER, 3, "t3", "Europe/London", ["slack", "gmail"]),
        ]


class TestWorkflowPromptContextThroughCreator:
    """The prompt `_create_onboarding_workflows` feeds the spec LLM, exercised
    through the real `_build_workflow_prompt_context` so its rendering — not a
    stub — is what the model would actually read."""

    async def _capture(self, **overrides: Any) -> str:
        payload: dict[str, Any] = {
            "profession": "lawyer",
            "has_gmail": True,
            "focus": "close Q3",
            "user_timezone": "UTC",
            "triage": None,
            "writing_style": None,
            "clarify_answers": None,
            "selected_integrations": None,
        }
        payload.update(overrides)
        llm = AsyncMock(return_value=_specs())
        with (
            patch(f"{MODULE}._generate_workflow_specs", llm),
            patch(f"{MODULE}._build_one_workflow", AsyncMock(return_value=_card("w0"))),
        ):
            await _create_onboarding_workflows(USER, **payload)
        assert llm.await_args.args[0] == USER
        return llm.await_args.args[1]

    async def test_profession_focus_and_gmail_reach_the_prompt(self) -> None:
        prompt = await self._capture()
        assert "lawyer" in prompt
        assert "close Q3" in prompt
        assert "True" in prompt
        assert "False" not in prompt

    async def test_blank_profession_and_focus_are_labelled(self) -> None:
        prompt = await self._capture(profession="", focus="")
        assert "- Profession: professional\n" in prompt
        assert NOT_SPECIFIED in prompt

    async def test_gmail_false_is_reflected(self) -> None:
        prompt = await self._capture(has_gmail=False)
        assert "False" in prompt
        assert "True" not in prompt

    async def test_triage_patterns_are_joined_and_capped_at_three(self) -> None:
        triage = _triage(patterns=[f"p{i}" for i in range(5)])
        prompt = await self._capture(triage=triage)
        assert "p0; p1; p2" in prompt
        assert "p3" not in prompt

    async def test_senders_are_joined_and_capped_at_five(self) -> None:
        triage = _triage(
            important_emails=[
                EmailSummary(sender=f"s{i}@x.com", subject="s", why_important="w")
                for i in range(7)
            ]
        )
        prompt = await self._capture(triage=triage)
        assert "s0@x.com, s1@x.com, s2@x.com, s3@x.com, s4@x.com" in prompt
        assert "s5@x.com" not in prompt

    async def test_writing_style_summary_is_capped_at_150_chars(self) -> None:
        prompt = await self._capture(writing_style=_style(summary="z" * 300))
        assert "z" * 150 in prompt
        assert "z" * 151 not in prompt

    async def test_missing_learnings_fall_back_to_placeholders(self) -> None:
        prompt = await self._capture()
        assert "- Inbox patterns observed: no patterns detected\n" in prompt
        assert "- Frequent senders: no email data\n" in prompt
        assert "- Writing style: not analyzed\n" in prompt

    async def test_empty_triage_lists_are_labelled_too(self) -> None:
        prompt = await self._capture(triage=_triage(patterns=[], important_emails=[]))
        assert "- Inbox patterns observed: no patterns detected\n" in prompt
        assert "- Frequent senders: no email data\n" in prompt

    async def test_selected_integrations_render_a_section_with_friendly_names(self) -> None:
        prompt = await self._capture(
            selected_integrations=["slack", "gmail", "not_a_real_integration"]
        )
        friendly = [OAUTH_INTEGRATION_NAME_BY_ID["slack"], OAUTH_INTEGRATION_NAME_BY_ID["gmail"]]
        section = (
            "Preferred integrations (anchor at least half of the workflows to these tools):\n"
            + ", ".join(friendly)
            + "\n\n"
        )
        assert section in prompt
        assert "not_a_real_integration" not in prompt

    async def test_no_integration_section_when_none_selected(self) -> None:
        prompt = await self._capture(selected_integrations=[], has_gmail=False)
        assert "Preferred integrations" not in prompt
        assert "None" not in prompt
        assert "XXXX" not in prompt

    async def test_clarify_answers_reach_the_prompt(self) -> None:
        llm = AsyncMock(return_value=_specs())
        answers = [{"kind": "goal", "value": "grow the team"}]
        with (
            patch(f"{MODULE}._generate_workflow_specs", llm),
            patch(f"{MODULE}._build_one_workflow", AsyncMock(return_value=_card("w0"))),
            patch(f"{MODULE}.format_clarify_context", return_value="CLARIFY-BLOCK") as fmt,
        ):
            await _create_onboarding_workflows(
                USER, "dev", False, "", "UTC", None, None, answers, None
            )

        assert fmt.call_args.args == (answers,)
        assert "CLARIFY-BLOCK" in llm.await_args.args[1]


# ---------------------------------------------------------------------------
# _create_fallback_workflow
# ---------------------------------------------------------------------------


class TestCreateFallbackWorkflow:
    async def test_creates_a_daily_briefing(self) -> None:
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow("fb1"))
            result = await _create_fallback_workflow(USER)

        assert result[0].id == "fb1"
        assert result[0].title == "Daily Briefing"
        assert result[0].description == (
            "Every morning at 9am, summarize unread emails by priority, "
            "today's meetings, and open todos."
        )
        assert result[0].trigger.model_dump(mode="json", exclude_none=True) == {
            "type": "schedule",
            "cron_expression": _DEFAULT_WORKFLOW_CRON,
        }
        assert service.create_workflow.await_args.kwargs["user_timezone"] == "UTC"

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

    async def test_integration_ids_are_forwarded(self) -> None:
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow())
            await _create_fallback_workflow(USER, "", "UTC", ["gmail"])

        assert service.create_workflow.await_args.args[0].integration_ids == ["gmail"]

    async def test_the_generic_description_is_exact(self) -> None:
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow())
            result = await _create_fallback_workflow(USER, "")

        assert result[0].description == (
            "Every morning at 9am, summarize unread emails by priority, "
            "today's meetings, and open todos."
        )

    async def test_the_focus_description_is_exact(self) -> None:
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow())
            result = await _create_fallback_workflow(USER, "close Q3 deals")

        assert result[0].description == (
            "Every morning, summarize unread emails by priority, today's meetings, "
            "and open todos. Focus: close Q3 deals."
        )

    async def test_a_focus_over_100_chars_is_capped_in_the_description(self) -> None:
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow())
            result = await _create_fallback_workflow(USER, "x" * 150)

        assert result[0].description == (
            "Every morning, summarize unread emails by priority, today's meetings, "
            f"and open todos. Focus: {'x' * 100}."
        )

    async def test_the_request_is_built_exactly(self) -> None:
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow())
            await _create_fallback_workflow(USER, "focus", "Europe/London", ["gmail"])

        request, user_id = service.create_workflow.await_args.args
        assert request.title == "Daily Briefing"
        assert request.prompt == request.description
        assert request.trigger_config == TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression=_DEFAULT_WORKFLOW_CRON
        )
        assert request.generate_immediately is True
        assert request.integration_ids == ["gmail"]
        assert user_id == USER
        assert service.create_workflow.await_args.kwargs["user_timezone"] == "Europe/London"

    async def test_the_card_has_no_categories(self) -> None:
        with patch(f"{MODULE}.WorkflowService") as service:
            service.create_workflow = AsyncMock(return_value=_workflow())
            result = await _create_fallback_workflow(USER)

        assert result[0].categories == []

    async def test_a_failure_yields_an_empty_list(self) -> None:
        # This is the last resort; raising here would abort the whole pipeline.
        with (
            patch(f"{MODULE}.WorkflowService") as service,
            patch(f"{MODULE}.log") as log,
        ):
            service.create_workflow = AsyncMock(side_effect=RuntimeError("mongo"))
            assert await _create_fallback_workflow(USER) == []

        warns = [c for c in log.warning.call_args_list if "Fallback workflow creation failed" in str(c)]
        assert warns, "fallback failure was not logged"
        assert warns[-1].kwargs["error"] == "mongo"
        assert warns[-1].kwargs["error_type"] == "RuntimeError"


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
        await _run_holo_card(USER, UserDocument(id=USER), "focus", None, None)

        args = save.await_args.args
        assert args[0] == USER
        assert args[1] == "mistgrove"
        assert args[2] == "a phrase"
        assert emit.await_args.args[1] is OnboardingStage.HOLO_READY

    async def test_context_summary_gathers_every_available_signal(self, holo_stack: Any) -> None:
        content, _, _ = holo_stack
        await _run_holo_card(
            USER,
            UserDocument(id=USER),
            "ship v2",
            _triage(),
            WritingStyleProfile(summary="Terse", example=WritingStyleExampleBlocks(body=["x"])),
            [SocialProfile(platform="x", url="u1")],
            [{"kind": "goal", "value": "grow the team"}],
        )

        summary = content.await_args.args[1]
        assert "Busy inbox" in summary
        assert "newsletters" in summary
        assert "ann@x.com" in summary
        assert "Terse" in summary
        assert "x: u1" in summary
        assert "ship v2" in summary
        assert "Goal: grow the team" in summary

    async def test_blank_clarify_answers_are_skipped(self, holo_stack: Any) -> None:
        content, _, _ = holo_stack
        await _run_holo_card(
            USER,
            UserDocument(id=USER),
            "",
            None,
            None,
            None,
            [{"kind": "goal", "value": "   "}, {"value": ""}],
        )

        assert content.await_args.args[1] == ""

    async def test_a_clarify_answer_without_a_kind_defaults_to_context(
        self, holo_stack: Any
    ) -> None:
        content, _, _ = holo_stack
        await _run_holo_card(
            USER, UserDocument(id=USER), "", None, None, None, [{"value": "some note"}]
        )

        assert "Context: some note" in content.await_args.args[1]

    async def test_absent_signals_produce_an_empty_summary(self, holo_stack: Any) -> None:
        content, _, _ = holo_stack
        await _run_holo_card(USER, UserDocument(id=USER), "", None, None)

        assert content.await_args.args[1] == ""

    async def test_a_failure_still_announces_readiness(self, holo_stack: Any) -> None:
        # The frontend waits on HOLO_READY; skipping it leaves the card spinning.
        _, _, emit = holo_stack
        long_error = "e" * 300
        with (
            patch(
                f"{MODULE}.get_user_metadata", AsyncMock(side_effect=RuntimeError(long_error))
            ),
            patch(f"{MODULE}.log") as log,
        ):
            await _run_holo_card(USER, UserDocument(id=USER), "", None, None)

        assert emit.await_args.args[1] is OnboardingStage.HOLO_READY
        errors = [c for c in log.error.call_args_list if "holo_card failed" in str(c)]
        assert errors, "holo card failure was not logged"
        assert errors[-1].kwargs["user_id"] == USER
        assert errors[-1].kwargs["step"] == "holo_card"
        assert errors[-1].kwargs["outcome"] == "failed"
        assert errors[-1].kwargs["error"] == "e" * 200
        assert errors[-1].kwargs["error_type"] == "RuntimeError"
        assert isinstance(errors[-1].kwargs["duration_s"], float)

    async def test_save_receives_every_field_in_order(self, holo_stack: Any) -> None:
        _, save, _ = holo_stack
        await _run_holo_card(USER, UserDocument(id=USER), "", None, None)

        assert save.await_args.args == (USER, "mistgrove", "a phrase", "a bio", "ok", [], 1, "2026", "#fff", 20)

    async def test_the_context_summary_is_rendered_exactly(self, holo_stack: Any) -> None:
        # The exact joined text is what the LLM grounds the card on; a mutated
        # separator or a dropped section changes what the user's card says.
        content, _, _ = holo_stack
        triage = _triage(
            patterns=["newsletters", "digests"],
            important_emails=[
                EmailSummary(sender=f"s{i}@x.com", subject="sub", why_important="w")
                for i in range(3)
            ],
        )
        await _run_holo_card(
            USER,
            UserDocument(id=USER),
            "ship v2",
            triage,
            _style(summary="Terse"),
            [SocialProfile(platform="x", url="u1"), SocialProfile(platform="y", url="u2")],
            [{"kind": "goal", "value": "grow the team"}],
        )

        assert content.await_args.args[1] == (
            "Inbox summary: Busy inbox\n"
            "Inbox patterns: newsletters; digests\n"
            "Key contacts: s0@x.com, s1@x.com, s2@x.com\n"
            "Writing style: Terse\n"
            "Social profiles: x: u1, y: u2\n"
            "Current focus: ship v2\n"
            "Goal: grow the team"
        )

    async def test_key_contacts_are_capped_at_five(self, holo_stack: Any) -> None:
        content, _, _ = holo_stack
        triage = _triage(
            patterns=[],
            important_emails=[
                EmailSummary(sender=f"s{i}@x.com", subject="s", why_important="w")
                for i in range(7)
            ],
        )
        await _run_holo_card(USER, UserDocument(id=USER), "", triage, None)

        summary = content.await_args.args[1]
        assert "Key contacts: s0@x.com, s1@x.com, s2@x.com, s3@x.com, s4@x.com" in summary
        assert "s5@x.com" not in summary

    async def test_the_content_generator_receives_user_and_user_id(self, holo_stack: Any) -> None:
        content, _, _ = holo_stack
        user = UserDocument(id=USER)
        await _run_holo_card(USER, user, "ship v2", None, None)

        assert content.await_args.args[0] == USER
        assert content.await_args.kwargs["user"] is user

    async def test_metadata_is_fetched_for_the_user(self, holo_stack: Any) -> None:
        with patch(
            f"{MODULE}.get_user_metadata",
            AsyncMock(return_value=UserProfileMetadata(account_number=1, member_since="2026")),
        ) as meta:
            user = UserDocument(id=USER)
            await _run_holo_card(USER, user, "", None, None)

        assert meta.await_args.args == (USER,)
        assert meta.await_args.kwargs == {"user": user}

    async def test_a_blank_answer_does_not_suppress_later_answers(self, holo_stack: Any) -> None:
        content, _, _ = holo_stack
        await _run_holo_card(
            USER,
            UserDocument(id=USER),
            "",
            None,
            None,
            None,
            [{"value": "   "}, {"value": "keep me"}],
        )

        assert "Context: keep me" in content.await_args.args[1]

    async def test_readiness_is_announced_for_the_user(self, holo_stack: Any) -> None:
        _, _, emit = holo_stack
        await _run_holo_card(USER, UserDocument(id=USER), "", None, None)

        assert emit.await_args.args[0] == USER

    async def test_success_logs_the_card_details(self, holo_stack: Any) -> None:
        with patch(f"{MODULE}.log") as log:
            await _run_holo_card(USER, UserDocument(id=USER), "", None, None)

        done = [c for c in log.info.call_args_list if "holo_card done" in str(c)]
        assert done, "no holo_card completion line emitted"
        assert done[-1].kwargs["user_id"] == USER
        assert done[-1].kwargs["step"] == "holo_card"
        assert done[-1].kwargs["outcome"] == "ok"
        assert done[-1].kwargs["house"] == "mistgrove"
        assert done[-1].kwargs["bio_status"] == "ok"
        assert done[-1].kwargs["context_chars"] == 0
        assert isinstance(done[-1].kwargs["meta_duration_s"], float)
        assert isinstance(done[-1].kwargs["phrase_bio_duration_s"], float)
        assert isinstance(done[-1].kwargs["save_duration_s"], float)
        assert isinstance(done[-1].kwargs["duration_s"], float)


# ---------------------------------------------------------------------------
# _wait_for_early_phase
# ---------------------------------------------------------------------------


class TestWaitForEarlyPhase:
    async def test_returns_true_once_the_marker_appears(self) -> None:
        user = MagicMock()
        user.onboarding = {"early_intelligence_done_at": "2026-07-27T00:00:00Z"}
        clock = iter([0.0, 1.0, 2.0, 3.0])
        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
            patch(f"{MODULE}.time.monotonic", side_effect=lambda: next(clock)),
        ):
            repo.get = AsyncMock(return_value=user)
            assert await _wait_for_early_phase(USER) is True
            assert repo.get.await_args.args == (USER,)

    async def test_polls_until_the_marker_is_written(self) -> None:
        pending, done = MagicMock(), MagicMock()
        pending.onboarding = {}
        done.onboarding = {"early_intelligence_done_at": "t"}
        clock = iter([0.0, 1.0, 2.0, 3.0])

        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
            patch(f"{MODULE}.time.monotonic", side_effect=lambda: next(clock)),
        ):
            repo.get = AsyncMock(side_effect=[pending, pending, done])
            assert await _wait_for_early_phase(USER) is True
            assert repo.get.await_count == 3

    async def test_a_missing_user_keeps_polling(self) -> None:
        done = MagicMock()
        done.onboarding = {"early_intelligence_done_at": "t"}
        clock = iter([0.0, 1.0, 2.0, 3.0])
        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
            patch(f"{MODULE}.time.monotonic", side_effect=lambda: next(clock)),
        ):
            repo.get = AsyncMock(side_effect=[None, done])
            assert await _wait_for_early_phase(USER) is True
            assert repo.get.await_count == 2

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

    async def test_polling_stops_at_the_deadline_boundary(self) -> None:
        # With monotonic() == deadline the poll loop must not run again: a
        # <= instead of < would read the user one extra time.
        pending = MagicMock()
        pending.onboarding = {}
        clock = iter([0.0, 300.0, 400.0])

        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
            patch(f"{MODULE}.time.monotonic", side_effect=lambda: next(clock)),
        ):
            repo.get = AsyncMock(return_value=pending)
            assert await _wait_for_early_phase(USER) is False
            assert repo.get.await_count == 0

    async def test_polling_waits_the_configured_interval(self) -> None:
        # A mutated sleep delay (e.g. None) would break the pacing contract —
        # the poll cadence must be exactly the configured interval.
        pending = MagicMock()
        pending.onboarding = {}
        done = MagicMock()
        done.onboarding = {"early_intelligence_done_at": "t"}
        clock = iter([0.0, 1.0, 2.0, 3.0])
        delays: list[float] = []

        async def sleep(delay: float) -> None:
            delays.append(delay)

        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch(f"{MODULE}.asyncio.sleep", AsyncMock(side_effect=sleep)),
            patch(f"{MODULE}.time.monotonic", side_effect=lambda: next(clock)),
        ):
            repo.get = AsyncMock(side_effect=[pending, done])
            assert await _wait_for_early_phase(USER) is True

        assert delays == [EARLY_PHASE_POLL_INTERVAL_S]

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

    async def test_a_never_marked_user_polls_to_the_deadline(self) -> None:
        # The None branch must not crash or spin past the deadline — and the
        # deadline itself must still be honoured when the user never appears.
        clock = iter([0.0] + [float(i) for i in range(1, 700)])

        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
            patch(f"{MODULE}.time.monotonic", side_effect=lambda: next(clock)),
        ):
            repo.get = AsyncMock(return_value=None)
            assert await _wait_for_early_phase(USER) is False

    async def test_timeout_is_logged_with_the_configured_deadline(self) -> None:
        pending = MagicMock()
        pending.onboarding = {}
        clock = iter([0.0] + [1000.0] * 10)

        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
            patch(f"{MODULE}.time.monotonic", side_effect=lambda: next(clock)),
            patch(f"{MODULE}.log") as log,
        ):
            repo.get = AsyncMock(return_value=pending)
            await _wait_for_early_phase(USER)

        warns = [c for c in log.warning.call_args_list if "marker timeout" in str(c)]
        assert warns, "timeout was not logged"
        assert warns[-1].kwargs["timeout_s"] == EARLY_PHASE_WAIT_TIMEOUT_S
        assert warns[-1].kwargs["user_id"] == USER
