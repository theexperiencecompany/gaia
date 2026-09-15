"""Unit tests for the pure helpers behind workflow step generation.

These pin the four helpers extracted out of ``WorkflowGenerationService`` in
``app/services/workflow/generation_service.py``: the user-facing failure
summary, the structured one-shot's call shape, and the two category collectors
that decide what the generator is allowed to reach for. Each is a pure function
over a seam (an exception, the LLM lane, the tool registry, the OAuth catalog),
so every branch is provable without touching a model.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError
import pytest

from app.agents.prompts.workflow_prompts import WORKFLOW_PROMPT_GENERATION_SYSTEM
from app.constants.integrations import MANAGED_BY_INTERNAL
from app.constants.log_tags import LogTag
from app.models.workflow_models import (
    GeneratedPromptOutput,
    GeneratedStep,
    GeneratedWorkflow,
    PromptTriggerHint,
    SuggestedTrigger,
    TriggerConfig,
    WorkflowStep,
)
from app.services.workflow.generation_service import (
    _MAX_GENERATION_ATTEMPTS,
    _MAX_REASON_CHARS,
    WorkflowGenerationService,
    WorkflowPromptRequest,
    WorkflowStepGenerationError,
    _build_integration_hints,
    _collect_custom_integration_categories,
    _collect_registry_categories,
    _collect_subagent_categories,
    _failure_reason,
    _run_generation_attempt,
    _structured_one_shot,
    _validated_steps,
)

MODULE = "app.services.workflow.generation_service"


# ---------------------------------------------------------------------------
# _failure_reason
# ---------------------------------------------------------------------------


class TestFailureReason:
    """The one line the workflow modal shows when generation dies."""

    def test_it_names_the_exception_type_and_its_message(self):
        """A bare "This request requires more credits" reads as if the user's own
        account is at fault; the type is what says the provider refused."""
        assert _failure_reason(ValueError("no route to model")) == ("ValueError: no route to model")

    def test_the_type_is_the_concrete_subclass_not_its_base(self):
        class ProviderRefused(RuntimeError):
            pass

        assert _failure_reason(ProviderRefused("402")) == "ProviderRefused: 402"

    def test_a_multi_line_provider_body_is_collapsed_to_one_line(self):
        """The modal renders this inline — a raw JSON body would break it."""
        assert _failure_reason(RuntimeError("credits\n  low\tnow")) == (
            "RuntimeError: credits low now"
        )

    def test_an_empty_message_falls_back_to_the_class_name(self):
        """``raise TimeoutError`` carries no message at all; "TimeoutError: "
        with nothing after it tells the user nothing."""
        assert _failure_reason(TimeoutError()) == "TimeoutError: TimeoutError"
        assert _failure_reason(TimeoutError("   ")) == "TimeoutError: TimeoutError"

    def test_a_message_exactly_at_the_limit_is_kept_whole(self):
        """The cut is for messages LONGER than the limit — truncating one that
        already fits would drop a character for nothing."""
        message = "a" * _MAX_REASON_CHARS

        assert _failure_reason(ValueError(message)) == f"ValueError: {message}"

    def test_a_longer_message_is_cut_to_the_limit_with_an_ellipsis(self):
        reason = _failure_reason(ValueError("a" * (_MAX_REASON_CHARS + 50)))

        assert reason == "ValueError: " + "a" * (_MAX_REASON_CHARS - 1) + "…"
        assert len(reason.removeprefix("ValueError: ")) == _MAX_REASON_CHARS

    def test_the_cut_never_leaves_a_space_before_the_ellipsis(self):
        """Cutting mid-sentence lands on a space as often as not; " …" reads as
        a typo rather than as elision."""
        message = "a" * (_MAX_REASON_CHARS - 2) + " " + "b" * 50

        assert _failure_reason(ValueError(message)) == (
            "ValueError: " + "a" * (_MAX_REASON_CHARS - 2) + "…"
        )


# ---------------------------------------------------------------------------
# _structured_one_shot
# ---------------------------------------------------------------------------


class _Draft(BaseModel):
    title: str = ""


class TestStructuredOneShot:
    """The lane a workflow draft is actually asked for."""

    async def test_it_meters_the_user_and_runs_the_schema_on_this_deployments_lane(self):
        """``metered_config`` is what bills the request to the user, and the SAME
        config has to reach both the runnable and the invoke: a deployment on a
        custom endpoint has no OpenRouter route, and a lost config sends the
        call back to the lane that does not exist here."""
        prompt = [HumanMessage(content="make me a workflow")]
        config = {"metadata": {"user_id": "user-1"}}
        runnable = MagicMock(name="structured_runnable")
        drafted = _Draft(title="Daily digest")

        with (
            patch(f"{MODULE}.metered_config", return_value=config) as mock_metered,
            patch(
                f"{MODULE}.background_structured_runnable", return_value=runnable
            ) as mock_runnable,
            patch(
                f"{MODULE}.ainvoke_llm", new_callable=AsyncMock, return_value=drafted
            ) as mock_llm,
        ):
            result = await _structured_one_shot(
                _Draft, prompt, label="workflow_steps", user_id="user-1"
            )

        assert result is drafted
        mock_metered.assert_called_once_with("user-1")
        mock_runnable.assert_called_once_with(_Draft, config=config)
        mock_llm.assert_awaited_once_with(runnable, prompt, label="workflow_steps", config=config)

    async def test_the_label_reaches_the_call_verbatim(self):
        """The label is how a generation shows up in the model-cost ledger; two
        call sites sharing one label make the spend unattributable."""
        with (
            patch(f"{MODULE}.metered_config", return_value={}),
            patch(f"{MODULE}.background_structured_runnable", return_value=MagicMock()),
            patch(
                f"{MODULE}.ainvoke_llm", new_callable=AsyncMock, return_value=_Draft()
            ) as mock_llm,
        ):
            await _structured_one_shot(
                _Draft, [HumanMessage(content="x")], label="workflow_prompt", user_id="user-1"
            )

        assert mock_llm.await_args.kwargs["label"] == "workflow_prompt"

    async def test_an_empty_draft_is_returned_as_is_rather_than_repaired(self):
        """The one-shot does not validate or substitute — the caller's retry loop
        owns the empty draft, so a silent fallback here would hide it."""
        empty = _Draft()

        with (
            patch(f"{MODULE}.metered_config", return_value={}),
            patch(f"{MODULE}.background_structured_runnable", return_value=MagicMock()),
            patch(f"{MODULE}.ainvoke_llm", new_callable=AsyncMock, return_value=empty),
        ):
            result = await _structured_one_shot(
                _Draft, [HumanMessage(content="x")], label="workflow_steps", user_id="user-1"
            )

        assert result is empty
        assert result.title == ""

    async def test_a_provider_error_propagates_instead_of_becoming_a_blank_draft(self):
        with (
            patch(f"{MODULE}.metered_config", return_value={}),
            patch(f"{MODULE}.background_structured_runnable", return_value=MagicMock()),
            patch(
                f"{MODULE}.ainvoke_llm",
                new_callable=AsyncMock,
                side_effect=RuntimeError("402 credits"),
            ),
        ):
            with pytest.raises(RuntimeError, match="402 credits"):
                await _structured_one_shot(
                    _Draft, [HumanMessage(content="x")], label="workflow_steps", user_id="user-1"
                )


# ---------------------------------------------------------------------------
# _collect_registry_categories
# ---------------------------------------------------------------------------


class _FakeTool:
    """A tool object carrying a name, whose ``str()`` is deliberately different."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return f"<tool object {self.name}>"


class _FakeCategory:
    def __init__(
        self,
        tools: list[object],
        require_integration: bool = False,
        integration_name: str | None = None,
    ) -> None:
        self.require_integration = require_integration
        self.integration_name = integration_name
        self._tools = tools

    def get_tool_objects(self) -> list[object]:
        return self._tools


def _registry(categories: dict[str, _FakeCategory]) -> MagicMock:
    registry = MagicMock()
    registry.get_all_category_objects.return_value = categories
    return registry


class TestCollectRegistryCategories:
    """What the generator is told it may build steps out of."""

    def test_core_categories_are_always_offered_with_their_tool_names(self):
        """A tool is named to the model by ``.name``; its repr would be a string
        the model cannot call."""
        registry = _registry(
            {"productivity": _FakeCategory([_FakeTool("create_todo"), _FakeTool("list_todos")])}
        )

        names, lines = _collect_registry_categories(registry, set())

        assert names == ["productivity"]
        assert lines == ["productivity: create_todo, list_todos"]

    def test_a_tool_without_a_name_falls_back_to_its_string_form(self):
        registry = _registry({"misc": _FakeCategory([_FakeTool("named"), "raw_tool"])})

        names, lines = _collect_registry_categories(registry, set())

        assert names == ["misc"]
        assert lines == ["misc: named, raw_tool"]

    def test_a_provider_category_is_offered_only_when_its_integration_is_active(self):
        """Offering an unconnected provider produces a workflow that fails on its
        first run, so the active set is the whole gate."""
        registry = _registry(
            {
                "gh_tools": _FakeCategory(
                    [_FakeTool("open_pr")], require_integration=True, integration_name="GitHub"
                )
            }
        )

        assert _collect_registry_categories(registry, {"github"}) == (
            ["gh_tools"],
            ["gh_tools: open_pr"],
        )
        assert _collect_registry_categories(registry, {"notion"}) == ([], [])

    def test_the_active_set_is_matched_on_the_integration_name_not_the_category(self):
        """The category key and the integration slug differ (``gh_tools`` vs
        ``github``); matching on the wrong one hides every connected provider."""
        registry = _registry(
            {
                "gh_tools": _FakeCategory(
                    [_FakeTool("open_pr")], require_integration=True, integration_name="GitHub"
                )
            }
        )

        assert _collect_registry_categories(registry, {"gh_tools"}) == ([], [])

    def test_a_provider_category_with_no_integration_name_falls_back_to_its_key(self):
        registry = _registry(
            {"notion": _FakeCategory([_FakeTool("search")], require_integration=True)}
        )

        assert _collect_registry_categories(registry, {"notion"}) == (
            ["notion"],
            ["notion: search"],
        )
        assert _collect_registry_categories(registry, set()) == ([], [])

    def test_one_skipped_provider_does_not_hide_the_categories_after_it(self):
        """The skip is a `continue`, not a `break`: a single unconnected provider
        early in the registry must not cost the model every category behind it."""
        registry = _registry(
            {
                "notion_tools": _FakeCategory(
                    [_FakeTool("search")], require_integration=True, integration_name="notion"
                ),
                "productivity": _FakeCategory([_FakeTool("create_todo")]),
            }
        )

        names, lines = _collect_registry_categories(registry, set())

        assert names == ["productivity"]
        assert lines == ["productivity: create_todo"]


# ---------------------------------------------------------------------------
# _collect_subagent_categories
# ---------------------------------------------------------------------------


@dataclass
class _FakeSubagentConfig:
    has_subagent: bool
    capabilities: str = ""


@dataclass
class _FakeIntegration:
    """A stand-in for an ``OAUTH_INTEGRATIONS`` entry.

    Carries every attribute the module reads off the catalog — the subagent
    collector, the friendly-name lookup, the explicit-mention scan and the
    trigger list all walk the same list.
    """

    id: str
    managed_by: str = "composio"
    subagent_config: _FakeSubagentConfig | None = None
    name: str = ""
    associated_triggers: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.id


def _catalog(*integrations: _FakeIntegration):
    return patch(f"{MODULE}.OAUTH_INTEGRATIONS", list(integrations))


class TestCollectSubagentCategories:
    """Which subagents the generator may delegate a step to."""

    def test_an_internal_subagent_is_offered_even_with_nothing_connected(self):
        """Todos/reminders/skills are core capabilities — gating them behind the
        active set would leave a brand-new user unable to generate anything."""
        with _catalog(
            _FakeIntegration(
                "todos", MANAGED_BY_INTERNAL, _FakeSubagentConfig(True, "creating todos")
            )
        ):
            assert _collect_subagent_categories(set()) == (
                ["todos"],
                ["todos (subagent): creating todos"],
            )

    def test_a_provider_subagent_is_offered_only_once_its_integration_is_active(self):
        gmail = _FakeIntegration("gmail", "composio", _FakeSubagentConfig(True, "sending mail"))

        with _catalog(gmail):
            assert _collect_subagent_categories({"gmail"}) == (
                ["gmail"],
                ["gmail (subagent): sending mail"],
            )
            assert _collect_subagent_categories(set()) == ([], [])
            assert _collect_subagent_categories({"notion"}) == ([], [])

    def test_the_active_set_is_matched_in_lower_case(self):
        """Integration ids arrive lower-cased in the active set; upper-casing the
        lookup would hide every connected provider subagent."""
        with _catalog(
            _FakeIntegration("GitHub", "composio", _FakeSubagentConfig(True, "opening PRs"))
        ):
            assert _collect_subagent_categories({"github"}) == (
                ["GitHub"],
                ["GitHub (subagent): opening PRs"],
            )

    def test_an_integration_with_no_subagent_is_skipped_without_reading_its_config(self):
        """Most of the catalog has no subagent at all — reaching into a missing
        config is an AttributeError on every generation."""
        with _catalog(
            _FakeIntegration("dropbox", "composio", None),
            _FakeIntegration("figma", "composio", _FakeSubagentConfig(has_subagent=False)),
            _FakeIntegration("gmail", "composio", _FakeSubagentConfig(True, "sending mail")),
        ):
            assert _collect_subagent_categories({"dropbox", "figma", "gmail"}) == (
                ["gmail"],
                ["gmail (subagent): sending mail"],
            )

    def test_one_unconnected_provider_does_not_hide_the_subagents_after_it(self):
        """The skip is a `continue`, not a `break`: the catalog is mostly
        unconnected providers, so stopping at the first one would leave the
        generator with nothing — including the internal capabilities."""
        with _catalog(
            _FakeIntegration("notion", "composio", _FakeSubagentConfig(True, "pages")),
            _FakeIntegration("todos", MANAGED_BY_INTERNAL, _FakeSubagentConfig(True, "todos")),
        ):
            assert _collect_subagent_categories(set()) == (
                ["todos"],
                ["todos (subagent): todos"],
            )

    def test_the_catalog_order_is_preserved(self):
        with _catalog(
            _FakeIntegration("todos", MANAGED_BY_INTERNAL, _FakeSubagentConfig(True, "a")),
            _FakeIntegration("gmail", "composio", _FakeSubagentConfig(True, "b")),
            _FakeIntegration("skills", MANAGED_BY_INTERNAL, _FakeSubagentConfig(True, "c")),
        ):
            names, lines = _collect_subagent_categories({"gmail"})

        assert names == ["todos", "gmail", "skills"]
        assert lines == [
            "todos (subagent): a",
            "gmail (subagent): b",
            "skills (subagent): c",
        ]


# ---------------------------------------------------------------------------
# WorkflowStepGenerationError
# ---------------------------------------------------------------------------


class TestWorkflowStepGenerationError:
    """The typed error the API turns into a message the modal can render."""

    def test_the_reason_is_readable_off_the_error_and_off_its_str(self):
        """The endpoint reads ``.reason``; a logger that only str()s the
        exception must not print an empty line instead."""
        error = WorkflowStepGenerationError("the provider refused")

        assert error.reason == "the provider refused"
        assert str(error) == "the provider refused"
        assert isinstance(error, RuntimeError)


# ---------------------------------------------------------------------------
# _validated_steps
# ---------------------------------------------------------------------------


class TestValidatedSteps:
    """Whether a candidate draft is usable, or worth one more attempt."""

    def test_a_draft_with_steps_is_enriched_with_positional_ids(self):
        result = GeneratedWorkflow(
            steps=[
                GeneratedStep(title="Fetch mail", category="gmail", description="read inbox"),
                GeneratedStep(title="Summarize", category="gaia", description="write a brief"),
            ]
        )

        steps = _validated_steps(result)

        assert steps == [
            WorkflowStep(
                id="step_0", title="Fetch mail", category="gmail", description="read inbox"
            ),
            WorkflowStep(
                id="step_1", title="Summarize", category="gaia", description="write a brief"
            ),
        ]

    def test_a_missing_draft_is_absence_not_an_exception(self):
        """An empty generation is regenerable; raising here would spend the
        user's second attempt on a traceback."""
        assert _validated_steps(None) is None

    def test_a_draft_with_no_steps_is_absence_too(self):
        assert _validated_steps(GeneratedWorkflow(steps=[])) is None


# ---------------------------------------------------------------------------
# _build_integration_hints
# ---------------------------------------------------------------------------


class TestBuildIntegrationHints:
    """The two hint lines appended to the workflow description."""

    def test_no_integrations_produces_no_hint_at_all(self):
        """An empty hint block would still cost the prompt two blank lines."""
        assert _build_integration_hints(set(), set(), {}) == []

    def test_preferred_integrations_are_named_with_their_category_id(self):
        """The name tells the model what the user meant; the id is what a step's
        ``category`` must be set to for that integration's tools to resolve."""
        with _catalog(_FakeIntegration("gmail", name="Gmail")):
            assert _build_integration_hints({"gmail"}, set(), {}) == [
                "Preferred integrations (use where the workflow makes sense): "
                "Gmail (category: gmail)"
            ]

    def test_explicit_integrations_carry_the_must_appear_wording(self):
        """Preferred is a soft hint, explicit is a hard requirement — the two
        lines have to read differently or the model treats them the same."""
        with _catalog(_FakeIntegration("notion", name="Notion")):
            assert _build_integration_hints(set(), {"notion"}, {}) == [
                "Integrations the user explicitly named — MUST appear in the steps: "
                "Notion (category: notion)"
            ]

    def test_preferred_comes_before_explicit_when_both_are_present(self):
        with _catalog(
            _FakeIntegration("gmail", name="Gmail"), _FakeIntegration("notion", name="Notion")
        ):
            hints = _build_integration_hints({"gmail"}, {"notion"}, {})

        assert hints == [
            "Preferred integrations (use where the workflow makes sense): Gmail (category: gmail)",
            "Integrations the user explicitly named — MUST appear in the steps: "
            "Notion (category: notion)",
        ]

    def test_each_line_lists_its_slugs_sorted_and_comma_separated(self):
        """A set has no order — without the sort the same request produces a
        different prompt on every run and nothing is reproducible."""
        with _catalog(
            _FakeIntegration("gmail", name="Gmail"),
            _FakeIntegration("notion", name="Notion"),
            _FakeIntegration("slack", name="Slack"),
        ):
            hints = _build_integration_hints({"slack", "gmail", "notion"}, set(), {})

        assert hints == [
            "Preferred integrations (use where the workflow makes sense): "
            "Gmail (category: gmail), Notion (category: notion), Slack (category: slack)"
        ]

    def test_the_explicit_line_lists_its_slugs_sorted_and_comma_separated_too(self):
        """The two lines are built separately, so the explicit one can lose its
        separator on its own and collapse into a single unusable token."""
        with _catalog(
            _FakeIntegration("gmail", name="Gmail"), _FakeIntegration("notion", name="Notion")
        ):
            hints = _build_integration_hints(set(), {"notion", "gmail"}, {})

        assert hints == [
            "Integrations the user explicitly named — MUST appear in the steps: "
            "Gmail (category: gmail), Notion (category: notion)"
        ]

    def test_a_custom_integrations_uuid_is_labelled_from_the_display_names_map(self):
        """Custom integrations are keyed by an opaque uuid ``OAUTH_INTEGRATIONS``
        knows nothing about; without the map the model is shown the raw uuid."""
        with _catalog(_FakeIntegration("gmail", name="Gmail")):
            assert _build_integration_hints({"abc-123"}, set(), {"abc-123": "My CRM"}) == [
                "Preferred integrations (use where the workflow makes sense): "
                "My CRM (category: abc-123)"
            ]

    def test_the_display_name_wins_over_the_static_catalog(self):
        with _catalog(_FakeIntegration("gmail", name="Gmail")):
            assert _build_integration_hints({"gmail"}, set(), {"gmail": "Work Mail"}) == [
                "Preferred integrations (use where the workflow makes sense): "
                "Work Mail (category: gmail)"
            ]

    def test_an_unknown_slug_is_printed_once_instead_of_twice(self):
        """``_slug_to_friendly_name`` returns the slug itself when it resolves
        nothing; "foo (category: foo)" is noise the model has to parse."""
        with _catalog(_FakeIntegration("gmail", name="Gmail")):
            assert _build_integration_hints({"mystery"}, set(), {}) == [
                "Preferred integrations (use where the workflow makes sense): mystery"
            ]


# ---------------------------------------------------------------------------
# _collect_custom_integration_categories
# ---------------------------------------------------------------------------


@dataclass
class _FakeCustomIntegration:
    id: str
    name: str
    source: str = "custom"
    description: str | None = None


def _my_integrations(*integrations):
    payload = MagicMock()
    payload.integrations = list(integrations)
    return patch(
        "app.services.integrations.my_integrations.get_my_integrations",
        new_callable=AsyncMock,
        return_value=payload,
    )


class TestCollectCustomIntegrationCategories:
    """The user's own MCP / self-added integrations, offered as categories."""

    async def test_a_selected_custom_integration_becomes_a_category_and_a_display_name(self):
        with _my_integrations(
            _FakeCustomIntegration("abc-123", "My CRM", description="Customer records")
        ):
            names, lines, display = await _collect_custom_integration_categories(
                "user-1", {"abc-123"}
            )

        assert names == ["abc-123"]
        assert lines == ["abc-123 (custom integration): My CRM. Customer records"]
        assert display == {"abc-123": "My CRM"}

    async def test_without_a_description_the_name_is_reused_as_the_summary(self):
        """An empty summary would leave the model a dangling ". " and nothing
        to decide what the integration is for."""
        with _my_integrations(_FakeCustomIntegration("abc-123", "My CRM", description=None)):
            _, lines, _ = await _collect_custom_integration_categories("user-1", {"abc-123"})

        assert lines == ["abc-123 (custom integration): My CRM. My CRM"]

    async def test_a_built_in_integration_is_not_re_offered_as_a_custom_one(self):
        """``get_my_integrations`` returns the whole catalog; only ``source ==
        "custom"`` entries are missing from the static registry."""
        with _my_integrations(
            _FakeCustomIntegration("gmail", "Gmail", source="oauth"),
            _FakeCustomIntegration("abc-123", "My CRM"),
        ):
            names, lines, display = await _collect_custom_integration_categories(
                "user-1", {"gmail", "abc-123"}
            )

        assert names == ["abc-123"]
        assert lines == ["abc-123 (custom integration): My CRM. My CRM"]
        assert display == {"abc-123": "My CRM"}

    async def test_an_unselected_custom_integration_is_left_out(self):
        with _my_integrations(_FakeCustomIntegration("abc-123", "My CRM")):
            assert await _collect_custom_integration_categories("user-1", set()) == (
                [],
                [],
                {},
            )
            assert await _collect_custom_integration_categories("user-1", {"other"}) == (
                [],
                [],
                {},
            )

    async def test_the_active_set_is_matched_in_lower_case_but_the_id_keeps_its_case(self):
        """Ids arrive lower-cased in the active set; the category the model is
        told to use must still be the id the tool router will accept."""
        with _my_integrations(_FakeCustomIntegration("ABC-123", "My CRM")):
            names, lines, display = await _collect_custom_integration_categories(
                "user-1", {"abc-123"}
            )

        assert names == ["ABC-123"]
        assert lines == ["ABC-123 (custom integration): My CRM. My CRM"]
        assert display == {"abc-123": "My CRM"}

    async def test_one_unselected_integration_does_not_hide_the_ones_after_it(self):
        """The skips are `continue`, not `break`: most of the list is neither
        custom nor selected."""
        with _my_integrations(
            _FakeCustomIntegration("gmail", "Gmail", source="oauth"),
            _FakeCustomIntegration("unpicked", "Unpicked"),
            _FakeCustomIntegration("abc-123", "My CRM"),
            _FakeCustomIntegration("def-456", "My ERP"),
        ):
            names, lines, display = await _collect_custom_integration_categories(
                "user-1", {"abc-123", "def-456"}
            )

        assert names == ["abc-123", "def-456"]
        assert lines == [
            "abc-123 (custom integration): My CRM. My CRM",
            "def-456 (custom integration): My ERP. My ERP",
        ]
        assert display == {"abc-123": "My CRM", "def-456": "My ERP"}

    async def test_the_user_id_is_what_the_lookup_is_made_for(self):
        with _my_integrations(_FakeCustomIntegration("abc-123", "My CRM")) as mock_get:
            await _collect_custom_integration_categories("user-42", {"abc-123"})

        mock_get.assert_awaited_once_with("user-42")

    async def test_a_failed_lookup_degrades_to_the_built_in_catalog(self):
        """Custom integrations are an enrichment — losing them must not cost the
        user the whole generation."""
        with (
            patch(
                "app.services.integrations.my_integrations.get_my_integrations",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo down"),
            ),
            patch(f"{MODULE}.log") as mock_log,
        ):
            assert await _collect_custom_integration_categories("user-1", {"abc-123"}) == (
                [],
                [],
                {},
            )

        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.args == (
            f"{LogTag.WORKFLOW} Could not load custom integrations for user",
        )
        kwargs = mock_log.warning.call_args.kwargs
        assert kwargs == {
            "user_id": "user-1",
            "error": "mongo down",
            "error_type": "RuntimeError",
        }

    async def test_a_partial_failure_keeps_what_was_already_collected(self):
        """The lists are built as the loop runs; discarding them on a late error
        would silently drop integrations that resolved fine."""
        good = _FakeCustomIntegration("abc-123", "My CRM")
        exploding = MagicMock()
        type(exploding).source = property(lambda _self: (_ for _ in ()).throw(ValueError("boom")))
        with _my_integrations(good, exploding), patch(f"{MODULE}.log"):
            names, lines, display = await _collect_custom_integration_categories(
                "user-1", {"abc-123"}
            )

        assert names == ["abc-123"]
        assert lines == ["abc-123 (custom integration): My CRM. My CRM"]
        assert display == {"abc-123": "My CRM"}


# ---------------------------------------------------------------------------
# _run_generation_attempt
# ---------------------------------------------------------------------------


def _llm(**kwargs):
    """Patch the LLM seam ``_structured_one_shot`` actually calls."""
    return patch(f"{MODULE}.ainvoke_llm", new_callable=AsyncMock, **kwargs)


def _llm_plumbing():
    return (
        patch(f"{MODULE}.metered_config", return_value={"cfg": 1}),
        patch(f"{MODULE}.background_structured_runnable", return_value=MagicMock()),
    )


def _draft(*steps: tuple[str, str, str]) -> GeneratedWorkflow:
    return GeneratedWorkflow(
        steps=[
            GeneratedStep(title=title, category=category, description=description)
            for title, category, description in steps
        ]
    )


def _invalid_output_error() -> ValidationError:
    try:
        GeneratedStep.model_validate({})
    except ValidationError as e:
        return e
    raise AssertionError("GeneratedStep({}) was expected to be invalid")


class TestRunGenerationAttempt:
    """One attempt at a draft, and how its outcome is classified."""

    async def test_a_usable_draft_comes_back_as_enriched_steps_and_no_error(self):
        metered, runnable = _llm_plumbing()
        with (
            metered,
            runnable,
            _llm(return_value=_draft(("Fetch mail", "gmail", "read the inbox"))),
        ):
            steps, error = await _run_generation_attempt("the prompt", user_id="user-1", attempt=0)

        assert error is None
        assert steps == [
            WorkflowStep(
                id="step_0", title="Fetch mail", category="gmail", description="read the inbox"
            )
        ]

    async def test_the_draft_is_asked_for_with_the_workflow_schema_and_prompt(self):
        """The schema is what makes the output structured, the prompt is the whole
        request, and the label is how this generation is billed and found."""
        metered, runnable = _llm_plumbing()
        with (
            metered,
            runnable,
            patch(f"{MODULE}.background_structured_runnable") as mock_runnable,
            _llm(return_value=_draft(("Step", "gaia", "do it"))) as mock_llm,
        ):
            await _run_generation_attempt("the prompt", user_id="user-42", attempt=0)

        mock_runnable.assert_called_once_with(GeneratedWorkflow, config={"cfg": 1})
        assert mock_llm.await_args.args[1] == "the prompt"
        assert mock_llm.await_args.kwargs["label"] == "workflow_generation"

    async def test_the_attempt_is_metered_to_the_user_who_asked_for_it(self):
        metered, runnable = _llm_plumbing()
        with (
            patch(f"{MODULE}.metered_config", return_value={"cfg": 1}) as mock_metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do it"))),
        ):
            await _run_generation_attempt("the prompt", user_id="user-42", attempt=0)

        mock_metered.assert_called_once_with("user-42")

    async def test_a_success_logs_how_many_steps_came_back(self):
        metered, runnable = _llm_plumbing()
        with (
            metered,
            runnable,
            _llm(return_value=_draft(("A", "gaia", "a"), ("B", "gaia", "b"))),
            patch(f"{MODULE}.log") as mock_log,
        ):
            await _run_generation_attempt("the prompt", user_id="user-1", attempt=0)

        assert mock_log.info.call_args.kwargs == {"steps_data_count": 2}
        mock_log.warning.assert_not_called()

    async def test_an_empty_draft_is_regenerable_and_says_why(self):
        """Empty output is the model misunderstanding, not the provider failing —
        the caller gets a reason to retry with, not an exception."""
        metered, runnable = _llm_plumbing()
        with metered, runnable, _llm(return_value=_draft()):
            steps, error = await _run_generation_attempt("the prompt", user_id="user-1", attempt=0)

        assert steps is None
        assert isinstance(error, ValueError)
        assert str(error) == (
            "LLM returned a workflow with no steps — the model may not have understood the request"
        )

    async def test_a_missing_draft_is_treated_the_same_as_an_empty_one(self):
        metered, runnable = _llm_plumbing()
        with metered, runnable, _llm(return_value=None):
            steps, error = await _run_generation_attempt("the prompt", user_id="user-1", attempt=0)

        assert steps is None
        assert isinstance(error, ValueError)

    async def test_an_empty_draft_logs_the_attempt_number_one_based(self):
        """``attempt`` is a zero-based loop index; logging it raw makes the first
        attempt read as attempt 0 in every incident thread."""
        metered, runnable = _llm_plumbing()
        with metered, runnable, _llm(return_value=_draft()), patch(f"{MODULE}.log") as mock_log:
            await _run_generation_attempt("the prompt", user_id="user-1", attempt=1)

        assert mock_log.warning.call_args.args == (f"{LogTag.WORKFLOW} No steps; regenerating",)
        assert mock_log.warning.call_args.kwargs == {
            "attempt": 2,
            "max_attempts": _MAX_GENERATION_ATTEMPTS,
        }

    async def test_schema_invalid_output_is_returned_for_a_retry_not_raised(self):
        """The provider's own retry already ran inside ``ainvoke_llm``; a
        malformed structured payload is worth asking the model again."""
        invalid = _invalid_output_error()
        metered, runnable = _llm_plumbing()
        with metered, runnable, _llm(side_effect=invalid):
            steps, error = await _run_generation_attempt("the prompt", user_id="user-1", attempt=0)

        assert steps is None
        assert error is invalid

    async def test_an_unparseable_response_is_regenerable_too(self):
        parser_error = OutputParserException("could not parse")
        metered, runnable = _llm_plumbing()
        with metered, runnable, _llm(side_effect=parser_error):
            steps, error = await _run_generation_attempt("the prompt", user_id="user-1", attempt=0)

        assert steps is None
        assert error is parser_error

    async def test_schema_invalid_output_logs_the_attempt_and_the_error_type(self):
        metered, runnable = _llm_plumbing()
        with (
            metered,
            runnable,
            _llm(side_effect=OutputParserException("nope")),
            patch(f"{MODULE}.log") as mock_log,
        ):
            await _run_generation_attempt("the prompt", user_id="user-1", attempt=0)

        assert mock_log.warning.call_args.args == (
            f"{LogTag.WORKFLOW} Structured output invalid; regenerating",
        )
        assert mock_log.warning.call_args.kwargs == {
            "attempt": 1,
            "max_attempts": _MAX_GENERATION_ATTEMPTS,
            "error_type": "OutputParserException",
        }
        mock_log.error.assert_not_called()

    async def test_a_provider_failure_becomes_the_typed_error_with_a_showable_reason(self):
        """Not regenerable: retrying a 402 burns the user's second attempt on the
        same refusal. The reason is what turns a blank 500 into a message."""
        provider_error = RuntimeError("This request requires more credits")
        metered, runnable = _llm_plumbing()
        with metered, runnable, _llm(side_effect=provider_error):
            with pytest.raises(WorkflowStepGenerationError) as caught:
                await _run_generation_attempt("the prompt", user_id="user-1", attempt=0)

        assert caught.value.reason == "RuntimeError: This request requires more credits"
        assert caught.value.__cause__ is provider_error

    async def test_a_provider_failure_is_logged_as_an_error_with_the_user_and_attempt(self):
        """This one ends the generation, so it has to be findable in the wide
        event by user — a warning would be filtered out of the error list."""
        metered, runnable = _llm_plumbing()
        with (
            metered,
            runnable,
            _llm(side_effect=RuntimeError("402")),
            patch(f"{MODULE}.log") as mock_log,
        ):
            with pytest.raises(WorkflowStepGenerationError):
                await _run_generation_attempt("the prompt", user_id="user-7", attempt=1)

        assert mock_log.error.call_args.args == (
            f"{LogTag.WORKFLOW} ========== FAILED: provider error",
        )
        assert mock_log.error.call_args.kwargs == {
            "attempt": 2,
            "error_type": "RuntimeError",
            "error": "402",
            "user_id": "user-7",
        }


# ---------------------------------------------------------------------------
# WorkflowGenerationService.generate_steps_with_llm
# ---------------------------------------------------------------------------


def _tool_registry(categories=None, core_tools=()):
    registry = MagicMock()
    registry.get_all_category_objects.return_value = categories or {}
    registry.get_core_tools.return_value = list(core_tools)
    return patch(f"{MODULE}.get_tool_registry", new_callable=AsyncMock, return_value=registry)


def _no_custom_integrations():
    payload = MagicMock()
    payload.integrations = []
    return patch(
        "app.services.integrations.my_integrations.get_my_integrations",
        new_callable=AsyncMock,
        return_value=payload,
    )


async def _generate_steps(**kwargs):
    return await WorkflowGenerationService.generate_steps_with_llm(**kwargs)


class TestGenerateStepsWithLlm:
    """The whole step-generation flow, from catalog to steps."""

    async def test_it_returns_the_enriched_steps_the_model_drafted(self):
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(),
            _catalog(),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(return_value=_draft(("Fetch", "gmail", "read"), ("Write", "gaia", "draft"))),
        ):
            steps = await _generate_steps(
                prompt="summarize my inbox", title="Inbox digest", user_id="user-1"
            )

        assert steps == [
            WorkflowStep(id="step_0", title="Fetch", category="gmail", description="read"),
            WorkflowStep(id="step_1", title="Write", category="gaia", description="draft"),
        ]

    async def test_gaia_is_always_a_category_so_pure_reasoning_steps_are_legal(self):
        """Without it the model has to route "summarize this" through some
        integration's tools, which is a step that cannot run."""
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(),
            _catalog(),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))) as mock_llm,
        ):
            await _generate_steps(prompt="p", title="t", user_id="user-1")

        prompt = mock_llm.await_args.args[1]
        assert "gaia: GAIA reasoning" in prompt
        assert "No external tool call." in prompt

    async def test_the_registry_the_subagents_and_gaia_all_reach_the_prompt_in_order(self):
        """Categories are a comma-separated list the model picks from; a lost
        section is a whole class of steps it can never produce."""
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(
                categories={"productivity": _FakeCategory([_FakeTool("create_todo")])},
                core_tools=[_FakeTool("web_search")],
            ),
            _catalog(
                _FakeIntegration("todos", MANAGED_BY_INTERNAL, _FakeSubagentConfig(True, "todos")),
                _FakeIntegration("gmail", subagent_config=_FakeSubagentConfig(True, "mail")),
                _FakeIntegration("notion", subagent_config=_FakeSubagentConfig(True, "pages")),
            ),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))) as mock_llm,
        ):
            await _generate_steps(
                prompt="p", title="t", integration_ids=["gmail"], user_id="user-1"
            )

        prompt = mock_llm.await_args.args[1]
        assert "productivity, todos, gmail, gaia" in prompt
        assert "gmail (subagent): mail" in prompt
        assert "notion (subagent)" not in prompt
        assert "productivity: create_todo" in prompt
        assert "todos (subagent): todos" in prompt
        assert "Always Available: web_search" in prompt

    async def test_a_core_tool_without_a_name_is_still_offered_by_its_string_form(self):
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(core_tools=["raw_core_tool"]),
            _catalog(),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))) as mock_llm,
        ):
            await _generate_steps(prompt="p", title="t", user_id="user-1")

        assert "Always Available: raw_core_tool" in mock_llm.await_args.args[1]

    async def test_the_title_and_the_trigger_context_reach_the_prompt(self):
        metered, runnable = _llm_plumbing()
        trigger = TriggerConfig(type="manual")
        with (
            _tool_registry(),
            _catalog(),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))) as mock_llm,
            patch(
                f"{MODULE}.generate_trigger_context", return_value="TRIGGER-CONTEXT"
            ) as mock_trigger,
        ):
            await _generate_steps(
                prompt="p", title="Inbox digest", trigger_config=trigger, user_id="user-1"
            )

        mock_trigger.assert_called_once_with(trigger)
        prompt = mock_llm.await_args.args[1]
        assert "Inbox digest" in prompt
        assert "TRIGGER-CONTEXT" in prompt

    async def test_the_description_is_appended_to_the_prompt_as_extra_context(self):
        """The description is a display summary, not the instruction — it must
        not replace the prompt the user wrote."""
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(),
            _catalog(),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))) as mock_llm,
        ):
            await _generate_steps(
                prompt="summarize my inbox",
                title="t",
                description="A daily digest",
                user_id="user-1",
            )

        assert (
            "summarize my inbox\n\nShort display summary for additional context: A daily digest"
            in mock_llm.await_args.args[1]
        )

    async def test_without_a_description_no_summary_line_is_invented(self):
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(),
            _catalog(),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))) as mock_llm,
        ):
            await _generate_steps(prompt="summarize my inbox", title="t", user_id="user-1")

        assert "Short display summary" not in mock_llm.await_args.args[1]

    async def test_preferred_integrations_are_normalized_and_hinted(self):
        """The ids arrive from the frontend with whatever casing and whitespace
        the form had; the hint and the category gate both key on the slug."""
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(
                categories={"gmail": _FakeCategory([_FakeTool("send")], require_integration=True)}
            ),
            _catalog(_FakeIntegration("gmail", name="Gmail")),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))) as mock_llm,
        ):
            await _generate_steps(
                prompt="p", title="t", integration_ids=[" GMAIL ", "gmail"], user_id="user-1"
            )

        prompt = mock_llm.await_args.args[1]
        assert (
            "Preferred integrations (use where the workflow makes sense): Gmail (category: gmail)"
            in prompt
        )
        assert "gmail: send" in prompt

    async def test_an_integration_named_in_the_prompt_is_a_hard_requirement(self):
        """An explicit mention unlocks the integration's category even when the
        user never ticked it in the picker."""
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(
                categories={
                    "notion": _FakeCategory([_FakeTool("search")], require_integration=True)
                }
            ),
            _catalog(_FakeIntegration("notion", name="Notion")),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))) as mock_llm,
        ):
            await _generate_steps(prompt="save it to notion", title="t", user_id="user-1")

        prompt = mock_llm.await_args.args[1]
        assert (
            "Integrations the user explicitly named — MUST appear in the steps: "
            "Notion (category: notion)" in prompt
        )
        assert "notion: search" in prompt

    async def test_with_no_integrations_at_all_no_hint_block_is_appended(self):
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(),
            _catalog(),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))) as mock_llm,
        ):
            await _generate_steps(prompt="p", title="t", user_id="user-1")

        prompt = mock_llm.await_args.args[1]
        assert "Preferred integrations" not in prompt
        assert "explicitly named" not in prompt

    async def test_a_selected_custom_integration_becomes_a_category_and_a_named_hint(self):
        metered, runnable = _llm_plumbing()
        payload = MagicMock()
        payload.integrations = [_FakeCustomIntegration("abc-123", "My CRM")]
        with (
            _tool_registry(),
            _catalog(),
            patch(
                "app.services.integrations.my_integrations.get_my_integrations",
                new_callable=AsyncMock,
                return_value=payload,
            ) as mock_custom,
            metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))) as mock_llm,
        ):
            await _generate_steps(
                prompt="p", title="t", integration_ids=["abc-123"], user_id="user-9"
            )

        mock_custom.assert_awaited_once_with("user-9")
        prompt = mock_llm.await_args.args[1]
        assert "abc-123 (custom integration): My CRM. My CRM" in prompt
        assert "My CRM (category: abc-123)" in prompt
        assert "gaia, abc-123" in prompt

    async def test_without_a_user_id_the_custom_catalog_is_not_consulted(self):
        """There is nobody to look integrations up for; calling anyway would be a
        lookup for the empty string."""
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(),
            _catalog(_FakeIntegration("gmail", name="Gmail")),
            patch(
                "app.services.integrations.my_integrations.get_my_integrations",
                new_callable=AsyncMock,
            ) as mock_custom,
            metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))) as mock_llm,
        ):
            await _generate_steps(prompt="p", title="t", integration_ids=["gmail"], user_id="")

        mock_custom.assert_not_awaited()
        assert "Gmail (category: gmail)" in mock_llm.await_args.args[1]

    async def test_an_empty_first_draft_is_regenerated_and_the_second_one_is_returned(self):
        """Two attempts is the whole point of the loop — giving up on the first
        empty draft would fail a request that succeeds on a retry."""
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(),
            _catalog(),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(side_effect=[_draft(), _draft(("Step", "gaia", "do"))]) as mock_llm,
        ):
            steps = await _generate_steps(prompt="p", title="t", user_id="user-1")

        assert steps == [WorkflowStep(id="step_0", title="Step", category="gaia", description="do")]
        assert mock_llm.await_count == 2

    async def test_a_first_attempt_that_works_is_not_retried(self):
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(),
            _catalog(),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))) as mock_llm,
        ):
            await _generate_steps(prompt="p", title="t", user_id="user-1")

        assert mock_llm.await_count == 1

    async def test_the_attempt_is_billed_to_the_user_who_asked_for_it(self):
        """The generation is metered per user; losing the id on the way into the
        attempt bills it to nobody and the spend stops being attributable."""
        _, runnable = _llm_plumbing()
        with (
            _tool_registry(),
            _catalog(),
            _no_custom_integrations(),
            patch(f"{MODULE}.metered_config", return_value={"cfg": 1}) as mock_metered,
            runnable,
            _llm(return_value=_draft(("Step", "gaia", "do"))),
        ):
            await _generate_steps(prompt="p", title="t", user_id="user-42")

        mock_metered.assert_called_once_with("user-42")

    async def test_every_attempt_empty_raises_the_typed_error_naming_the_attempt_count(self):
        """The modal renders this string; "generation failed" with no count reads
        as a bug rather than as the model not cooperating."""
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(),
            _catalog(),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(return_value=_draft()) as mock_llm,
        ):
            with pytest.raises(WorkflowStepGenerationError) as caught:
                await _generate_steps(prompt="p", title="t", user_id="user-1")

        assert mock_llm.await_count == _MAX_GENERATION_ATTEMPTS
        assert caught.value.reason == (
            f"the model returned no usable steps after {_MAX_GENERATION_ATTEMPTS} attempts "
            "(ValueError: LLM returned a workflow with no steps — the model may not have "
            "understood the request)"
        )

    async def test_the_last_error_is_the_cause_of_the_raised_failure(self):
        invalid = _invalid_output_error()
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(),
            _catalog(),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(side_effect=invalid),
        ):
            with pytest.raises(WorkflowStepGenerationError) as caught:
                await _generate_steps(prompt="p", title="t", user_id="user-1")

        assert caught.value.__cause__ is invalid
        assert "ValidationError" in caught.value.reason

    async def test_a_provider_failure_stops_the_loop_instead_of_burning_the_retry(self):
        metered, runnable = _llm_plumbing()
        with (
            _tool_registry(),
            _catalog(),
            _no_custom_integrations(),
            metered,
            runnable,
            _llm(side_effect=RuntimeError("402 credits")) as mock_llm,
        ):
            with pytest.raises(WorkflowStepGenerationError) as caught:
                await _generate_steps(prompt="p", title="t", user_id="user-1")

        assert mock_llm.await_count == 1
        assert caught.value.reason == "RuntimeError: 402 credits"


# ---------------------------------------------------------------------------
# WorkflowGenerationService.generate_workflow_prompt
# ---------------------------------------------------------------------------


class TestGenerateWorkflowPrompt:
    """The magic-prompt generator behind the workflow editor's wand button."""

    @staticmethod
    def _output(**kwargs) -> GeneratedPromptOutput:
        return GeneratedPromptOutput(
            **{
                "instructions": "Fetch the unread mail and summarize it.",
                "trigger_type": "manual",
                "cron_expression": None,
                "trigger_name": None,
                **kwargs,
            }
        )

    async def _run(self, request, output, user_id="user-1"):
        metered, runnable = _llm_plumbing()
        with metered, runnable, _llm(return_value=output) as mock_llm:
            result = await WorkflowGenerationService.generate_workflow_prompt(
                request, user_id=user_id
            )
        return result, mock_llm

    async def test_it_returns_the_instructions_and_the_suggested_trigger(self):
        result, _ = await self._run(
            WorkflowPromptRequest(title="Inbox digest"),
            self._output(trigger_type="schedule", cron_expression="0 9 * * *"),
        )

        assert result == {
            "prompt": "Fetch the unread mail and summarize it.",
            "suggested_trigger": SuggestedTrigger(
                type="schedule", cron_expression="0 9 * * *", trigger_name=None
            ),
        }

    async def test_an_integration_suggestion_keeps_its_trigger_slug(self):
        result, _ = await self._run(
            WorkflowPromptRequest(),
            self._output(trigger_type="integration", trigger_name="gmail_new_message"),
        )

        assert result["suggested_trigger"] == SuggestedTrigger(
            type="integration", cron_expression=None, trigger_name="gmail_new_message"
        )

    async def test_an_unrecognised_trigger_type_suggests_nothing(self):
        """The editor renders the suggestion straight into the trigger form; a
        type it has no UI for would leave the user with an unusable workflow."""
        result, _ = await self._run(WorkflowPromptRequest(), self._output(trigger_type="webhook"))

        assert result["suggested_trigger"] is None
        assert result["prompt"] == "Fetch the unread mail and summarize it."

    async def test_the_title_and_description_reach_the_prompt_labelled(self):
        _, mock_llm = await self._run(
            WorkflowPromptRequest(title="Inbox digest", description="Every weekday"),
            self._output(),
        )

        human = mock_llm.await_args.args[1][1].content
        assert "Title: Inbox digest\n" in human
        assert "Description: Every weekday" in human

    async def test_a_missing_title_leaves_no_empty_label_behind(self):
        _, mock_llm = await self._run(WorkflowPromptRequest(), self._output())

        human = mock_llm.await_args.args[1][1].content
        assert "Title:" not in human
        assert "Description:" not in human

    async def test_the_system_message_carries_the_generation_rules(self):
        _, mock_llm = await self._run(WorkflowPromptRequest(), self._output())

        messages = mock_llm.await_args.args[1]
        assert isinstance(messages[0], SystemMessage)
        assert messages[0].content == WORKFLOW_PROMPT_GENERATION_SYSTEM
        assert isinstance(messages[1], HumanMessage)
        assert mock_llm.await_args.kwargs["label"] == "workflow_prompt"

    async def test_existing_instructions_switch_the_call_into_improve_mode(self):
        """Regenerating from scratch over instructions the user already edited
        throws their work away."""
        _, mock_llm = await self._run(
            WorkflowPromptRequest(existing_prompt="Summarize my mail."), self._output()
        )

        human = mock_llm.await_args.args[1][1].content
        assert "Existing instructions to improve:\nSummarize my mail." in human
        assert "Improve these instructions" in human
        assert "from scratch" not in human

    async def test_with_no_existing_instructions_it_generates_from_scratch(self):
        _, mock_llm = await self._run(WorkflowPromptRequest(), self._output())

        human = mock_llm.await_args.args[1][1].content
        assert "Generate comprehensive workflow instructions from scratch." in human
        assert "Existing instructions to improve" not in human

    async def test_the_trigger_hint_describes_what_the_user_already_chose(self):
        _, mock_llm = await self._run(
            WorkflowPromptRequest(
                trigger_config=PromptTriggerHint(type="schedule", cron_expression="0 9 * * *")
            ),
            self._output(),
        )

        human = mock_llm.await_args.args[1][1].content
        assert "User has selected a scheduled trigger (current cron: 0 9 * * *)" in human

    async def test_preferred_integrations_are_named_in_the_hint(self):
        with _catalog(
            _FakeIntegration("gmail", name="Gmail"), _FakeIntegration("notion", name="Notion")
        ):
            _, mock_llm = await self._run(
                WorkflowPromptRequest(integration_ids=[" NOTION ", "gmail"]), self._output()
            )

        human = mock_llm.await_args.args[1][1].content
        assert (
            "User has selected these integrations as preferred tools for this workflow: "
            "Notion, Gmail. Name them naturally in the instructions and prefer "
            "triggers/actions that use them." in human
        )

    async def test_with_no_preferred_integrations_the_hint_is_empty(self):
        with _catalog(_FakeIntegration("gmail", name="Gmail")):
            _, mock_llm = await self._run(WorkflowPromptRequest(), self._output())

        assert "preferred tools" not in mock_llm.await_args.args[1][1].content

    async def test_the_available_triggers_are_limited_to_connected_integrations(self):
        """Suggesting a trigger from an integration the user never connected
        produces a workflow that can never fire."""
        request = WorkflowPromptRequest(connected_integration_ids={"gmail"})
        with patch(f"{MODULE}._build_available_triggers", return_value="TRIGGERS") as mock_triggers:
            _, mock_llm = await self._run(request, self._output())

        mock_triggers.assert_called_once_with({"gmail"})
        assert "TRIGGERS" in mock_llm.await_args.args[1][1].content

    async def test_the_generation_is_metered_to_the_requesting_user(self):
        with patch(f"{MODULE}.metered_config", return_value={}) as mock_metered:
            with (
                patch(f"{MODULE}.background_structured_runnable", return_value=MagicMock()),
                _llm(return_value=self._output()),
            ):
                await WorkflowGenerationService.generate_workflow_prompt(
                    WorkflowPromptRequest(), user_id="user-42"
                )

        mock_metered.assert_called_once_with("user-42")

    async def test_the_prompt_output_schema_is_what_the_model_is_asked_for(self):
        with (
            patch(f"{MODULE}.metered_config", return_value={"cfg": 2}),
            patch(f"{MODULE}.background_structured_runnable") as mock_runnable,
            _llm(return_value=self._output()),
        ):
            await WorkflowGenerationService.generate_workflow_prompt(
                WorkflowPromptRequest(), user_id="user-1"
            )

        mock_runnable.assert_called_once_with(GeneratedPromptOutput, config={"cfg": 2})
