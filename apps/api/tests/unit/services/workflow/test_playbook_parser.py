"""The playbook grammar, and validation against the live tool registry.

Both are what the authoring agent argues with: a rejected write must say which
node is wrong and why, so every assertion here is on the offending name
appearing in the message, not merely on "it failed".

The grammar itself is enforced by the models, since the structured tool schema
is the only way a playbook is ever authored — nothing parses YAML back.
"""

from typing import Annotated, Any
from unittest.mock import AsyncMock, call, patch

from langchain_core.tools import BaseTool, tool
from pydantic import Field, ValidationError
import pytest
import yaml

from app.agents.core.subagents.call_record import ARG_TRUNCATION_MARKER
from app.models.mcp_config import SubAgentConfig
from app.models.playbook_models import (
    PlaybookAsk,
    PlaybookBody,
    PlaybookHandoffStepInput,
    PlaybookStep,
    PlaybookStepInput,
    playbook_body_from_input,
)
from app.models.subagent_models import Subagent
from app.services.workflow.playbook.parser import dump_playbook, validate_playbook
from app.services.workflow.playbook.tool_space import SubagentTools

MODULE = "app.services.workflow.playbook.parser"
USER_ID = "user-1"


@tool
async def send_email(
    to: Annotated[str, "Recipient"], subject: Annotated[str, "Subject"], retries: int = 0
) -> dict[str, Any]:
    """Send an email."""
    return {}


@tool
async def list_events(calendar_id: Annotated[str, "Calendar"]) -> dict[str, Any]:
    """List calendar events."""
    return {}


class _FakeRegistry:
    """Stands in for the live tool registry: the seam, not the thing under test."""

    def __init__(self, tools: dict[str, BaseTool]) -> None:
        self._tools = tools

    def get_tool_dict(self) -> dict[str, BaseTool]:
        return self._tools


@tool("exec")
async def exec_query(code: Annotated[str, "Code to run"]) -> dict[str, Any]:
    """Run a query against the integration. Stands in for an MCP tool."""
    return {}


def _mcp_exec_tool() -> BaseTool:
    return exec_query


def _registry() -> _FakeRegistry:
    return _FakeRegistry({"send_email": send_email, "list_events": list_events})


class _SchemaTool(BaseTool):
    """A tool whose args are a raw JSON schema, the shape MCP tools arrive in.

    Unions and empty arg sets cannot be expressed with ``@tool`` decorators, and
    they are exactly the schemas a real integration hands the validator.
    """

    arg_schema: dict[str, Any] = Field(default_factory=dict)

    @property
    def args(self) -> dict[str, Any]:
        return self.arg_schema

    def _run(self, **kwargs: Any) -> dict[str, Any]:
        return {}


def _schema_registry(**schemas: dict[str, Any]) -> _FakeRegistry:
    tools: dict[str, BaseTool] = {
        name: _SchemaTool(name=name, description=f"{name} tool", arg_schema=schema)
        for name, schema in schemas.items()
    }
    return _FakeRegistry(tools)


def _body(raw_yaml: str) -> PlaybookBody:
    """Build a body from a YAML literal, so these cases stay readable as documents.

    Production authors playbooks through the structured tool schema; YAML here is
    only a convenient way to write the fixture.
    """
    return PlaybookBody.model_validate(yaml.safe_load(raw_yaml))


VALID_YAML = """
description: Mail the day's agenda
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
  - id: mail
    tool: send_email
    args:
      to: $user.email
      subject: Agenda for $today
      retries: 2
ask:
  body:
    prompt: Write the agenda as a short note
    uses: [agenda]
synthesize: Say what was sent.
"""


def _handoff_space(tools: dict[str, BaseTool] | None = None):
    """Stub the handoff tool space, standing in for a real subagent's tools.

    A handoff's children are validated against that subagent's own space, which
    for an MCP integration is fetched from the user's client. Tests declare that
    space explicitly rather than reaching for a live subagent registry.
    """
    space = SubagentTools(
        tools=_registry().get_tool_dict() if tools is None else tools, initial_tool_ids=[]
    )
    return patch(f"{MODULE}.resolve_subagent_tools", AsyncMock(return_value=space))


def _retrieval_disabled_handoff_space():
    """A handoff to a subagent shaped like ``docgen``: direct tools, no retrieval.

    Its scoped dict holds both the tool it binds (``list_events``) and one it
    can only see (``send_email``), the way the always-available tools sit in
    every subagent's dict without being in its initial set.
    """
    subagent = Subagent(
        id="calendar_agent",
        name="Calendar",
        provider="calendar",
        managed_by="internal",
        config=SubAgentConfig(
            agent_name="calendar_agent",
            tool_space="calendar",
            handoff_tool_name="handoff_to_calendar",
            domain="calendar",
            capabilities="c",
            use_cases="u",
            system_prompt="p",
            use_direct_tools=True,
            disable_retrieve_tools=True,
            include_finish_task=False,
        ),
    )
    space = SubagentTools(
        tools={"list_events": list_events, "send_email": send_email},
        initial_tool_ids=["list_events"],
        subagent=subagent,
    )
    return patch(f"{MODULE}.resolve_subagent_tools", AsyncMock(return_value=space))


@pytest.mark.unit
class TestPlaybookGrammar:
    """A step is a tool call or a handoff, never both and never neither."""

    def test_a_step_carrying_both_a_tool_and_a_handoff_is_rejected_by_name(self) -> None:
        with pytest.raises(ValidationError) as exc:
            PlaybookBody.model_validate(
                {
                    "description": "Confused",
                    "steps": [
                        {
                            "id": "both_shapes",
                            "tool": "send_email",
                            "handoff": "mail_agent",
                            "steps": [{"id": "inner", "tool": "send_email"}],
                        }
                    ],
                    "synthesize": "x",
                }
            )
        assert "both_shapes" in str(exc.value)

    def test_a_handoff_without_children_is_rejected_by_name(self) -> None:
        with pytest.raises(ValidationError) as exc:
            PlaybookBody.model_validate(
                {
                    "description": "Empty handoff",
                    "steps": [{"id": "delegate", "handoff": "mail_agent"}],
                    "synthesize": "x",
                }
            )
        assert "mail_agent" in str(exc.value)

    def test_an_unknown_top_level_key_is_rejected_by_name(self) -> None:
        with pytest.raises(ValidationError) as exc:
            PlaybookBody.model_validate(
                {
                    "description": "Extra key",
                    "version": 3,
                    "steps": [{"id": "one", "tool": "send_email"}],
                    "synthesize": "x",
                }
            )
        assert "version" in str(exc.value)

    def test_a_playbook_with_no_steps_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlaybookBody.model_validate(
                {"description": "Nothing to do", "steps": [], "synthesize": "x"}
            )


@pytest.mark.unit
class TestValidatePlaybook:
    async def test_valid_playbook_has_no_issues(self) -> None:
        body = _body(VALID_YAML)
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is True
        assert result.issues == []

    async def test_an_arg_carrying_the_records_cut_marker_is_refused(self) -> None:
        """The call record cuts long args and marks them; a step copied from the
        record would replay the stub forever. This check was dead until
        ensure_ascii=False: json.dumps escaped the marker ellipsis to a
        backslash-u2026 sequence and the containment test could never fire."""
        body = _body(
            f"""
description: Copied from the record
steps:
  - id: one
    tool: list_events
    args: {{"query": "newsletters {ARG_TRUNCATION_MARKER}"}}
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert [issue.problem for issue in result.issues] == [
            "'query' was cut short in the call record; pass the full value "
            "you actually sent, not the recorded stub"
        ]

    async def test_a_cut_arg_does_not_stop_the_rest_of_the_args_being_checked(self) -> None:
        """One stubbed arg must not silence the report on its siblings."""
        from app.agents.core.subagents.call_record import ARG_TRUNCATION_MARKER

        body = _body(
            f"""
description: Copied from the record
steps:
  - id: one
    tool: list_events
    args:
      query: "newsletters {ARG_TRUNCATION_MARKER}"
      bogus: "x"
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        problems = sorted(issue.problem for issue in result.issues)
        assert len(problems) == 2
        assert problems[0].startswith("'query' was cut short in the call record")
        assert problems[1].startswith("list_events takes no arg 'bogus'")

    async def test_a_shapeless_step_does_not_stop_its_siblings_being_checked(self) -> None:
        """exactly_one_shape forbids a step with neither tool nor handoff; if one
        is conjured anyway (model_construct), the walk skips it and still checks
        the steps after it."""
        ghost = PlaybookStep.model_construct(id="ghost", tool=None, handoff=None, steps=[], args={})
        real = PlaybookStep(id="one", tool="send_owl", args={})
        body = _body(VALID_YAML)
        patched = body.model_copy(update={"steps": [ghost, real]})

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(patched, USER_ID)

        assert any("send_owl" in issue.problem for issue in result.issues)

    async def test_unknown_tool_is_rejected_by_name(self) -> None:
        body = _body(
            """
description: Bogus tool
steps:
  - id: one
    tool: send_owl
    args: {}
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert any("send_owl" in issue.problem for issue in result.issues)

    async def test_unknown_arg_key_is_rejected(self) -> None:
        body = _body(
            """
description: Bad arg
steps:
  - id: one
    tool: send_email
    args:
      to: a@b.com
      subject: hi
      bcc: c@d.com
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert [issue.where for issue in result.issues] == ["steps[0].args.bcc"]
        assert "bcc" in result.issues[0].problem

    async def test_wrong_arg_type_is_rejected(self) -> None:
        body = _body(
            """
description: Bad type
steps:
  - id: one
    tool: send_email
    args:
      to: a@b.com
      subject: hi
      retries: soon
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert result.issues[0].where == "steps[0].args.retries"
        assert "integer" in result.issues[0].problem

    async def test_forward_step_reference_is_rejected(self) -> None:
        body = _body(
            """
description: Reads a step that has not run
steps:
  - id: mail
    tool: send_email
    args:
      to: $steps.agenda.organizer
      subject: hi
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert result.issues[0].where == "steps[0].args.to"
        assert "$steps.agenda" in result.issues[0].problem

    async def test_backward_step_reference_inside_handoff_resolves(self) -> None:
        body = _body(
            """
description: A handoff reading an earlier step
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
  - id: delegate
    handoff: mail_agent
    steps:
      - id: mail
        tool: send_email
        args:
          to: $steps.agenda.organizer
          subject: hi
synthesize: x
"""
        )
        with (
            patch(f"{MODULE}.get_tool_registry", return_value=_registry()),
            _handoff_space(),
        ):
            result = await validate_playbook(body, USER_ID)
        assert result.issues == []

    async def test_a_handoff_to_an_unknown_subagent_is_rejected_by_name(self) -> None:
        """Regression: handoff children used to be checked against the executor's
        registry, which refused every MCP integration whose tools are fetched per
        user. Now the subagent is resolved, so a missing one must say so."""
        body = _body(
            """
description: Hand off to nobody
steps:
  - id: delegate
    handoff: no_such_agent
    steps:
      - id: inner
        tool: send_email
        args:
          to: a@b.com
synthesize: x
"""
        )
        with (
            patch(f"{MODULE}.get_tool_registry", return_value=_registry()),
            patch(f"{MODULE}.resolve_subagent_tools", AsyncMock(return_value=None)),
        ):
            result = await validate_playbook(body, USER_ID)

        assert result.valid is False
        assert "no_such_agent" in result.issues[0].problem

    async def test_a_tool_only_the_integration_has_is_accepted(self) -> None:
        """The PostHog case: `exec` exists on the user's MCP client and nowhere in
        the executor's registry. Validating it against the registry refused every
        playbook an integration-backed workflow could ever write."""
        body = _body(
            """
description: Read PostHog
steps:
  - id: delegate
    handoff: posthog
    steps:
      - id: query
        tool: exec
        args:
          code: "1"
synthesize: x
"""
        )
        mcp_only = {"exec": _mcp_exec_tool()}
        with (
            patch(f"{MODULE}.get_tool_registry", return_value=_registry()),
            _handoff_space(mcp_only),
        ):
            result = await validate_playbook(body, USER_ID)

        assert result.issues == []

    async def test_a_child_the_subagent_can_see_but_not_bind_is_refused_as_the_runner_would(
        self,
    ) -> None:
        """A subagent that cannot retrieve (``docgen``, ``gaia_knowledge_guide``)
        runs only the tools it bound at startup, yet its scoped dict also holds
        the always-available ones. Validating children against the dict alone
        accepted a playbook the replay then stopped at that very step. The
        refusal has to be the runner's own wording, so the author reads one
        message whether it comes at write time or at replay."""
        body = _body(
            """
description: Delegate a send the subagent could never make
steps:
  - id: delegate
    handoff: calendar_agent
    steps:
      - id: mail
        tool: send_email
        args:
          to: a@b.com
          subject: hi
synthesize: x
"""
        )
        with (
            patch(f"{MODULE}.get_tool_registry", return_value=_registry()),
            _retrieval_disabled_handoff_space(),
        ):
            result = await validate_playbook(body, USER_ID)

        assert result.valid is False
        assert [(issue.where, issue.problem) for issue in result.issues] == [
            (
                "steps[0].steps[0]",
                "send_email is outside the bound tool set of this handoff, which cannot retrieve",
            )
        ]

    async def test_a_child_the_subagent_binds_at_startup_is_accepted(self) -> None:
        body = _body(
            """
description: Delegate a read the subagent binds
steps:
  - id: delegate
    handoff: calendar_agent
    steps:
      - id: agenda
        tool: list_events
        args:
          calendar_id: primary
synthesize: x
"""
        )
        with (
            patch(f"{MODULE}.get_tool_registry", return_value=_registry()),
            _retrieval_disabled_handoff_space(),
        ):
            result = await validate_playbook(body, USER_ID)

        assert result.issues == []

    async def test_undeclared_ask_reference_is_rejected(self) -> None:
        body = _body(
            """
description: Reads an ask nobody declared
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: $ask.headline
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert "$ask.headline" in result.issues[0].problem

    async def test_an_unknown_dollar_word_is_literal_text_not_a_placeholder(self) -> None:
        """Only the closed namespaces are placeholders. A recorded ``bash`` step
        says ``echo $HOME``; refusing every ``$identifier`` would refuse it."""
        body = _body(
            """
description: Shell variable in a recorded command
steps:
  - id: mail
    tool: send_email
    args:
      to: $sender.email
      subject: echo $HOME $1
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.issues == []

    async def test_a_placeholder_embedded_in_text_is_checked_like_a_whole_one(self) -> None:
        """The evaluator interpolates ``$x`` inside a larger string, so the
        validator has to read it there too. It only looked at values that
        START with ``$``, so ``"Sent $ask.headline"`` was accepted and then
        replayed against an ask the playbook never declares."""
        body = _body(
            """
description: Embedded undeclared ask
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: Sent $ask.headline about today
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert result.issues[0].where == "steps[0].args.subject"
        assert "$ask.headline" in result.issues[0].problem

    async def test_an_embedded_reference_to_an_undeclared_step_is_refused(self) -> None:
        body = _body(
            """
description: Embedded stale step reference
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: Found $steps.agenda.count events
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert "$steps.agenda.count" in result.issues[0].problem

    async def test_an_embedded_reference_to_a_declared_step_is_accepted(self) -> None:
        body = _body(
            """
description: Embedded valid reference
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: Found $steps.agenda.count events on $today
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.issues == []

    async def test_last_run_reference_is_accepted_unresolved(self) -> None:
        body = _body(
            """
description: Picks up where the last run stopped
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: $last_run.LIST_EVENTS.calendar_id
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.issues == []

    async def test_ask_uses_an_undeclared_step_is_rejected(self) -> None:
        body = _body(
            """
description: Ask reading a step that does not exist
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
ask:
  body:
    prompt: Write it up
    uses: [inbox]
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert result.issues[0].where == "ask.body.uses"

    async def test_an_ask_reading_a_step_that_runs_after_the_asks_are_filled_is_refused(
        self,
    ) -> None:
        """The runner narrates at the FIRST step addressing any ``$ask``, from the
        steps completed by then. ``uses`` was only checked against the steps the
        whole document declares, so an ask reading a later step validated and
        was then written from nothing at replay, silently."""
        body = _body(
            """
description: Summarise the agenda before fetching it
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: $ask.summary
  - id: calendar
    tool: list_events
    args:
      calendar_id: primary
ask:
  summary:
    prompt: Summarise the agenda
    uses: [calendar]
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert result.valid is False
        # Whole message, not fragments of it: the author is told which ask, where
        # the asks are filled, which step runs too late, and both ways out.
        assert [(issue.where, issue.problem) for issue in result.issues] == [
            (
                "ask.summary.uses",
                "ask 'summary' reads step 'calendar', but the asks are filled at step 'mail' "
                "(the first to address $ask), before 'calendar' runs; move 'calendar' ahead "
                "of 'mail' or drop it from uses",
            )
        ]

    async def test_every_ask_is_filled_at_the_first_ask_step_not_only_the_one_addressed(
        self,
    ) -> None:
        """One model call writes every ask. An ask whose own reference comes
        late enough is still written at the first ``$ask`` step, before the step
        it reads has run."""
        body = _body(
            """
description: Two asks, one filled too early
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: $ask.greeting
  - id: calendar
    tool: list_events
    args:
      calendar_id: primary
  - id: followup
    tool: send_email
    args:
      to: a@b.com
      subject: $ask.summary
ask:
  greeting:
    prompt: Say hello
  summary:
    prompt: Summarise the agenda
    uses: [calendar]
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert result.valid is False
        assert [issue.where for issue in result.issues] == ["ask.summary.uses"]
        assert "'mail'" in result.issues[0].problem

    async def test_an_ask_is_checked_past_the_uses_entries_that_are_already_fine(self) -> None:
        """``uses`` is checked entry by entry, not up to the first acceptable one.

        Stopping at the first entry that already ran would clear the whole ask,
        and the later step behind it would be written from nothing at replay.
        """
        body = _body(
            """
description: An ask reading one earlier step and one later one
steps:
  - id: inbox
    tool: list_events
    args:
      calendar_id: primary
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: $ask.summary
  - id: calendar
    tool: list_events
    args:
      calendar_id: work
ask:
  summary:
    prompt: Summarise both
    uses: [inbox, calendar]
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert result.valid is False
        assert [issue.where for issue in result.issues] == ["ask.summary.uses"]
        assert "'calendar'" in result.issues[0].problem

    async def test_an_ask_reading_only_earlier_steps_is_accepted(self) -> None:
        body = _body(
            """
description: Summarise the agenda after fetching it
steps:
  - id: calendar
    tool: list_events
    args:
      calendar_id: primary
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: $ask.summary
ask:
  summary:
    prompt: Summarise the agenda
    uses: [calendar]
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert result.issues == []

    async def test_an_ask_reading_a_step_nobody_declares_is_reported_once(self) -> None:
        """The ordering check must not double up with the existence check."""
        body = _body(
            """
description: Ask reading a ghost step
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: $ask.summary
ask:
  summary:
    prompt: Summarise
    uses: [inbox]
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert [(issue.where, issue.problem) for issue in result.issues] == [
            ("ask.summary.uses", "no step is declared with id 'inbox'")
        ]

    async def test_a_duplicate_step_id_is_refused_by_name(self) -> None:
        """The runner records results by id, so a second ``agenda`` overwrites
        the first and every ``$steps.agenda`` silently reads whichever ran last."""
        body = _body(
            """
description: Two steps called agenda
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
  - id: delegate
    handoff: calendar_agent
    steps:
      - id: agenda
        tool: list_events
        args:
          calendar_id: work
synthesize: x
"""
        )
        with (
            patch(f"{MODULE}.get_tool_registry", return_value=_registry()),
            _handoff_space(),
        ):
            result = await validate_playbook(body, USER_ID)

        assert result.valid is False
        assert [(issue.where, issue.problem) for issue in result.issues] == [
            (
                "steps[1].steps[0]",
                "step id 'agenda' is already used by an earlier step; ids must be unique so "
                "$steps references and the run's record point at one step",
            )
        ]

    async def test_a_handoff_is_resolved_by_its_own_name_for_this_user_and_registry(self) -> None:
        """Which tools a child step is checked against is decided by all three
        arguments: an MCP integration's tools are fetched from THAT user's own
        client, so resolving with anything else validates the playbook against a
        tool space the replay never has — accepted at write time, refused at
        replay, or worse, the reverse.
        """
        body = _body(
            """
description: Delegate a send
steps:
  - id: delegate
    handoff: mail_agent
    steps:
      - id: mail
        tool: send_email
        args:
          to: a@b.com
          subject: hi
synthesize: x
"""
        )
        registry = _registry()
        resolve = AsyncMock(
            return_value=SubagentTools(tools=registry.get_tool_dict(), initial_tool_ids=[])
        )
        with (
            patch(f"{MODULE}.get_tool_registry", return_value=registry),
            patch(f"{MODULE}.resolve_subagent_tools", resolve),
        ):
            result = await validate_playbook(body, USER_ID)

        assert result.issues == []
        assert resolve.await_args_list == [call("mail_agent", USER_ID, registry)]

    async def test_an_arg_json_cannot_serialise_is_type_checked_not_a_crash(self) -> None:
        """A recorded arg can hold a value ``json.dumps`` refuses — a YAML date is
        the everyday one. Scanning it for the truncation marker must fall back to
        its text rather than raise, or authoring dies with a TypeError instead of
        telling the author their date belongs in a string field.
        """
        body = _body(
            """
description: Send with a date where a string belongs
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: 2026-03-14
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert [(issue.where, issue.problem) for issue in result.issues] == [
            ("steps[0].args.subject", "expected string, got date")
        ]

    async def test_a_step_id_keeps_every_leading_character(self) -> None:
        """Only the separating dot is stripped from a reference's path.

        Trimming anything else silently renames the step, and a reference to a
        step the document really does declare is refused at authoring time.
        """
        body = _body(
            """
description: Reference a step whose id starts with X
steps:
  - id: XERO_SYNC
    tool: list_events
    args:
      calendar_id: primary
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: Synced $steps.XERO_SYNC.organizer
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert result.issues == []

    async def test_a_union_member_whose_type_has_no_python_mapping_is_skipped(self) -> None:
        """An MCP schema can declare a JSON type this validator has no mapping
        for. The unmapped member contributes nothing and the members it does know
        still decide the check; treating the unknown one as "no types at all"
        would blow up the walk over a union that is otherwise perfectly checkable.
        """
        registry = _schema_registry(
            query_rows={"cursor": {"anyOf": [{"type": "widget"}, {"type": "string"}]}}
        )
        accepted = _body(
            """
description: A cursor the union does accept
steps:
  - id: rows
    tool: query_rows
    args:
      cursor: tok_1
synthesize: x
"""
        )
        refused = _body(
            """
description: A cursor the union does not accept
steps:
  - id: rows
    tool: query_rows
    args:
      cursor: 7
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            assert (await validate_playbook(accepted, USER_ID)).issues == []
            result = await validate_playbook(refused, USER_ID)

        assert [(issue.where, issue.problem) for issue in result.issues] == [
            ("steps[0].args.cursor", "expected widget or string, got int")
        ]

    async def test_a_union_typed_arg_accepts_every_member_of_the_union(self) -> None:
        """An optional arg is declared as anyOf[string, null].

        Reading only the ``type`` key would treat the whole union as untyped and
        wave through any value; reading the wrong union key would reject a
        perfectly valid playbook at authoring time.
        """
        registry = _schema_registry(
            query_rows={"cursor": {"anyOf": [{"type": "string"}, {"type": "null"}]}}
        )
        for value in ("tok_1", "null"):
            body = _body(
                f"""
description: Optional cursor
steps:
  - id: rows
    tool: query_rows
    args:
      cursor: {value}
synthesize: x
"""
            )
            with patch(f"{MODULE}.get_tool_registry", return_value=registry):
                result = await validate_playbook(body, USER_ID)
            assert result.issues == []

    async def test_a_union_typed_arg_rejects_a_value_outside_the_union(self) -> None:
        """The message has to name the union, or the agent cannot repair the arg."""
        registry = _schema_registry(
            query_rows={"cursor": {"anyOf": [{"type": "string"}, {"type": "null"}]}}
        )
        body = _body(
            """
description: Wrong union member
steps:
  - id: rows
    tool: query_rows
    args:
      cursor: 7
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert result.issues[0].where == "steps[0].args.cursor"
        assert "expected string or null, got int" in result.issues[0].problem

    async def test_a_oneof_union_is_checked_exactly_like_anyof(self) -> None:
        """JSON Schema spells a union both ways and integrations use both."""
        registry = _schema_registry(
            query_rows={"limit": {"oneOf": [{"type": "integer"}, {"type": "string"}]}}
        )
        body = _body(
            """
description: oneOf union
steps:
  - id: rows
    tool: query_rows
    args:
      limit: [1, 2]
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert "expected integer or string, got list" in result.issues[0].problem

    async def test_a_union_whose_members_are_themselves_unions_still_reports_a_type(
        self,
    ) -> None:
        """A nested union has accepted types but no name to print for them.

        The message must still be a sentence the agent can act on rather than
        crashing the whole validation on a schema shape it did not expect.
        """
        registry = _schema_registry(
            query_rows={"limit": {"anyOf": [{"anyOf": [{"type": "integer"}]}]}}
        )
        body = _body(
            """
description: Nested union
steps:
  - id: rows
    tool: query_rows
    args:
      limit: nope
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert "expected another type, got str" in result.issues[0].problem

    async def test_a_boolean_is_not_accepted_for_an_integer_arg(self) -> None:
        """Python says ``isinstance(True, int)``; the tool's API does not.

        Letting ``true`` through as a count sends a live integration a 1 the
        author never wrote.
        """
        body = _body(
            """
description: Boolean count
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: hi
      retries: true
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert "expected integer, got bool" in result.issues[0].problem

    async def test_a_placeholder_in_a_typed_arg_is_not_type_checked(self) -> None:
        """``$steps.agenda.count`` is a string now and an int at replay time.

        Type-checking the unresolved token would make every dynamic argument
        unauthorable.
        """
        body = _body(
            """
description: Count comes from an earlier step
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: hi
      retries: $steps.agenda.count
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.issues == []

    async def test_a_placeholder_nested_inside_a_list_arg_is_still_checked(self) -> None:
        """Placeholders hide inside structured args, and a stale reference in one
        breaks the replay just as hard as a top-level one."""
        registry = _schema_registry(query_rows={"ids": {"type": "array"}})
        body = _body(
            """
description: Nested reference
steps:
  - id: rows
    tool: query_rows
    args:
      ids: [$steps.nowhere.id]
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert "$steps.nowhere.id" in result.issues[0].problem

    async def test_a_placeholder_nested_inside_an_object_arg_is_still_checked(self) -> None:
        """Same for a mapping arg, which is how most integrations take a payload."""
        registry = _schema_registry(query_rows={"filter": {"type": "object"}})
        body = _body(
            """
description: Nested reference in a mapping
steps:
  - id: rows
    tool: query_rows
    args:
      filter:
        owner: $steps.nowhere.id
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert "$steps.nowhere.id" in result.issues[0].problem

    async def test_every_bad_arg_on_a_step_is_reported_not_just_the_first(self) -> None:
        """The author fixes what the report lists. Stopping at the first bad arg
        turns one rejected write into a round trip per arg."""
        body = _body(
            """
description: Two bad args
steps:
  - id: one
    tool: send_email
    args:
      bcc: c@d.com
      cc: e@f.com
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert sorted(issue.where for issue in result.issues) == [
            "steps[0].args.bcc",
            "steps[0].args.cc",
        ]

    async def test_an_unknown_arg_lists_the_args_the_tool_does_take(self) -> None:
        """Naming the real args is what lets the agent fix the call in one turn."""
        body = _body(
            """
description: Bad arg
steps:
  - id: one
    tool: send_email
    args:
      bcc: c@d.com
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert "it takes: retries, subject, to" in result.issues[0].problem

    async def test_a_tool_that_takes_no_args_says_nothing_rather_than_an_empty_list(
        self,
    ) -> None:
        """An empty list after "it takes:" reads like a truncated message."""
        registry = _schema_registry(ping={})
        body = _body(
            """
description: Arg on an argless tool
steps:
  - id: one
    tool: ping
    args:
      loud: true
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert "it takes: nothing" in result.issues[0].problem

    async def test_a_deep_step_reference_resolves_against_the_step_id(self) -> None:
        """``$steps.agenda.organizer.email`` names step ``agenda``, not
        ``agenda.organizer``. Splitting from the wrong end rejects a playbook
        that would replay perfectly."""
        body = _body(
            """
description: Deep reference
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
  - id: mail
    tool: send_email
    args:
      to: $steps.agenda.organizer.email
      subject: hi
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.issues == []


@pytest.mark.unit
class TestDumpPlaybook:
    """The YAML rendering is what the agent reads its own playbook back from."""

    def test_non_ascii_text_survives_the_rendering(self) -> None:
        """Descriptions are written by users in their own language. Escaping the
        accented characters makes the playbook unreadable for the person who
        wrote it and for the agent that has to edit it."""
        body = _body(
            """
description: Résumé für das Team
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
synthesize: x
"""
        )
        rendered = dump_playbook(body)
        assert "Résumé für das Team" in rendered

    def test_keys_stay_in_authored_order(self) -> None:
        """Alphabetising would put ``description`` after ``ask`` and scatter each
        step's ``id``/``tool``/``args``, so the document stops reading like the
        sequence it describes."""
        body = _body(VALID_YAML)
        rendered = dump_playbook(body)
        assert rendered.index("description:") < rendered.index("steps:")
        assert rendered.index("steps:") < rendered.index("ask:")
        assert rendered.index("id: agenda") < rendered.index("args:")


def _messages(exc: pytest.ExceptionInfo[ValidationError]) -> list[str]:
    """Just the validator's own messages.

    ``str(ValidationError)`` also renders the offending input, so a message
    asserted against the whole string passes on the strength of the input echo
    even when the message says something else entirely.
    """
    return [error["msg"] for error in exc.value.errors()]


class TestStepShapeMessages:
    """What a rejected step actually tells the agent that wrote it.

    These messages are the authoring loop: the write fails, the agent reads the
    message, and rewrites the step. A message that does not name the offending
    node leaves it to guess which of a dozen steps to change, and a message that
    names the wrong thing sends it to rewrite a step that was fine. Both models
    carry the same rule because a playbook is authored through the input models
    and stored through ``PlaybookStep``, and the two must refuse the same shapes.
    """

    def test_a_stored_step_that_is_both_shapes_is_named(self) -> None:
        with pytest.raises(ValidationError) as exc:
            PlaybookStep.model_validate(
                {
                    "id": "both_shapes",
                    "tool": "send_email",
                    "handoff": "mail_agent",
                    "steps": [{"id": "inner", "tool": "send_email"}],
                }
            )

        assert any(
            "step both_shapes: set exactly one of 'tool' or 'handoff'" in message
            for message in _messages(exc)
        )

    def test_a_stored_step_that_is_neither_shape_is_called_unnamed(self) -> None:
        """A step with no id has to be described somehow, and "" is not a description."""
        with pytest.raises(ValidationError) as exc:
            PlaybookStep.model_validate({"args": {"to": "x@example.com"}})

        assert any(
            "step <unnamed>: set exactly one of 'tool' or 'handoff'" in message
            for message in _messages(exc)
        )

    def test_a_stored_handoff_with_no_children_says_it_would_do_nothing(self) -> None:
        with pytest.raises(ValidationError) as exc:
            PlaybookStep.model_validate({"id": "delegate", "handoff": "mail_agent"})

        assert any(
            "handoff mail_agent: carries no steps, so it would do nothing; list the calls that "
            "subagent ran (its handoff result records them) in this step's 'steps' field" in message
            for message in _messages(exc)
        )

    def test_a_stored_tool_step_carrying_children_is_named_by_its_id(self) -> None:
        """Only a handoff nests, and the message names the step, not the tool.

        The agent addresses the step it has to fix by id, so naming the tool
        instead points it at every step that calls that tool.
        """
        with pytest.raises(ValidationError) as exc:
            PlaybookStep.model_validate(
                {
                    "id": "notify",
                    "tool": "send_email",
                    "steps": [{"id": "inner", "tool": "send_email"}],
                }
            )

        assert any(
            "step notify: only a handoff may carry nested steps" in message
            for message in _messages(exc)
        )

    def test_an_authored_step_that_is_both_shapes_is_named(self) -> None:
        with pytest.raises(ValidationError) as exc:
            PlaybookStepInput.model_validate(
                {
                    "id": "both_shapes",
                    "tool": "send_email",
                    "handoff": "mail_agent",
                    "steps": [{"id": "inner", "tool": "send_email"}],
                }
            )

        assert any(
            "step both_shapes: set exactly one of 'tool' or 'handoff'" in message
            for message in _messages(exc)
        )

    def test_an_authored_step_that_is_neither_shape_is_called_unnamed(self) -> None:
        with pytest.raises(ValidationError) as exc:
            PlaybookStepInput.model_validate({"args": {"to": "x@example.com"}})

        assert any(
            "step <unnamed>: set exactly one of 'tool' or 'handoff'" in message
            for message in _messages(exc)
        )

    def test_an_authored_handoff_with_no_children_says_it_would_do_nothing(self) -> None:
        with pytest.raises(ValidationError) as exc:
            PlaybookStepInput.model_validate({"id": "delegate", "handoff": "mail_agent"})

        assert any(
            "handoff mail_agent: carries no steps, so it would do nothing; list the calls that "
            "subagent ran (its handoff result records them) in this step's 'steps' field" in message
            for message in _messages(exc)
        )

    def test_an_authored_tool_step_carrying_children_is_named_by_its_id(self) -> None:
        with pytest.raises(ValidationError) as exc:
            PlaybookStepInput.model_validate(
                {
                    "id": "notify",
                    "tool": "send_email",
                    "steps": [{"id": "inner", "tool": "send_email"}],
                }
            )

        assert any(
            "step notify: only a handoff may carry nested steps" in message
            for message in _messages(exc)
        )


class TestAuthoredPlaybookBecomesTheStoredOne:
    """The tool boundary's flat arguments, turned into the body that is stored.

    Everything dropped here is dropped silently: the playbook validates, stores
    and replays, and only the arguments the recorded call actually needed are
    missing. The replay then calls the right tool with the wrong arguments.
    """

    def test_a_handoff_childs_arguments_survive_the_conversion(self) -> None:
        child = PlaybookHandoffStepInput(
            id="mail", tool="send_email", args={"to": "team@example.com", "subject": "Agenda"}
        )

        step = child.to_step()

        assert step.id == "mail"
        assert step.tool == "send_email"
        assert step.args == {"to": "team@example.com", "subject": "Agenda"}

    def test_the_declared_asks_reach_the_stored_body(self) -> None:
        ask = PlaybookAsk(prompt="Write the digest.", uses=["events"])

        body = playbook_body_from_input(
            description="Mail the agenda",
            steps=[PlaybookStepInput(id="events", tool="list_events", args={"calendar_id": "x"})],
            synthesize="Say how many events there were.",
            ask={"body": ask},
        )

        assert body.ask == {"body": ask}
        assert [step.tool for step in body.steps] == ["list_events"]

    def test_a_playbook_with_no_asks_stores_an_empty_mapping(self) -> None:
        """``None`` is what the tool boundary sends for "no asks", and it is not storable."""
        body = playbook_body_from_input(
            description="Mail the agenda",
            steps=[PlaybookStepInput(id="events", tool="list_events", args={"calendar_id": "x"})],
            synthesize="Say how many events there were.",
            ask=None,
        )

        assert body.ask == {}
