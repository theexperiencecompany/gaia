"""The playbook grammar, and validation against the live tool registry.

Both are what the authoring agent argues with: a rejected write must say which
node is wrong and why, so every assertion here is on the offending name
appearing in the message, not merely on "it failed".

The grammar itself is enforced by the models, since the structured tool schema
is the only way a playbook is ever authored — nothing parses YAML back.
"""

from datetime import datetime
from typing import Annotated, Any
from unittest.mock import AsyncMock, call, patch

from langchain_core.tools import BaseTool, tool
from pydantic import Field, ValidationError, v1
import pytest
import yaml

from app.agents.core.subagents.call_record import ARG_TRUNCATION_MARKER
from app.models.mcp_config import SubAgentConfig
from app.models.playbook_models import (
    PlaybookBody,
    PlaybookHandoffStepInput,
    PlaybookStep,
    PlaybookStepInput,
    playbook_body_from_input,
)
from app.models.subagent_models import Subagent
from app.services.workflow.playbook.parser import (
    RecordedResult,
    dump_playbook,
    validate_playbook,
)
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
      subject:
        $ask: Write the agenda as a short note
      retries: 2
result_brief: Say what was sent.
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
                    "result_brief": "x",
                }
            )
        assert "both_shapes" in str(exc.value)

    def test_a_handoff_without_children_is_rejected_by_name(self) -> None:
        with pytest.raises(ValidationError) as exc:
            PlaybookBody.model_validate(
                {
                    "description": "Empty handoff",
                    "steps": [{"id": "delegate", "handoff": "mail_agent"}],
                    "result_brief": "x",
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
                    "result_brief": "x",
                }
            )
        assert "version" in str(exc.value)

    def test_a_playbook_with_no_steps_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlaybookBody.model_validate(
                {"description": "Nothing to do", "steps": [], "result_brief": "x"}
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
    args: {{"calendar_id": "primary", "query": "newsletters {ARG_TRUNCATION_MARKER}"}}
result_brief: x
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
      calendar_id: primary
      query: "newsletters {ARG_TRUNCATION_MARKER}"
      bogus: "x"
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
"""
        )
        with (
            patch(f"{MODULE}.get_tool_registry", return_value=_registry()),
            _retrieval_disabled_handoff_space(),
        ):
            result = await validate_playbook(body, USER_ID)

        assert result.issues == []

    async def test_a_dollar_ask_string_is_literal_text_and_is_type_checked_as_one(self) -> None:
        """``$ask`` left the placeholder vocabulary when asks moved inline, so
        ``$ask.headline`` is characters like ``$HOME`` is. It must neither be
        refused as an undeclared reference nor exempt the argument from the type
        check the way a real placeholder does — an author who writes it into an
        integer arg has written a string there."""
        body = _body(
            """
description: A dollar-ask string is just text
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: $ask.headline
      retries: $ask.count
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert [(issue.where, issue.problem) for issue in result.issues] == [
            ("steps[0].args.retries", "expected integer, got str")
        ]

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
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.issues == []

    async def test_a_placeholder_embedded_in_text_is_checked_like_a_whole_one(self) -> None:
        """The evaluator interpolates ``$x`` inside a larger string, so the
        validator has to read it there too. It only looked at values that
        START with ``$``, so ``"Sent $steps.headline.text"`` was accepted and
        then replayed against a step the playbook never declares."""
        body = _body(
            """
description: Embedded undeclared step reference
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: Sent $steps.headline.text about today
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert result.issues[0].where == "steps[0].args.subject"
        assert "$steps.headline.text" in result.issues[0].problem

    async def test_an_embedded_dollar_ask_is_literal_text_too(self) -> None:
        """The embedded scan reads every ``$word`` in a string; ``$ask`` is no
        longer one of the roots it knows, so text mentioning it must pass rather
        than being refused as a reference to a table that no longer exists."""
        body = _body(
            """
description: Text that mentions an ask
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: Sent $ask.headline about today
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.issues == []

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
result_brief: x
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
result_brief: x
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
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.issues == []

    async def test_an_ask_slot_standing_where_an_argument_goes_is_accepted(self) -> None:
        """The whole point of the inline shape: a value a model writes at replay
        sits in the argument that needs it, in whichever step needs it, and the
        validator lets it through. Refusing it would make the only way to author
        written text an unwritable playbook."""
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
      subject:
        $ask: Summarise the agenda
        max_tokens: 200
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert result.issues == []

    async def test_a_slot_nested_inside_a_structured_arg_is_accepted(self) -> None:
        """Slots reach as deep as arguments nest; a payload-shaped arg carrying
        one must validate exactly like a top-level one."""
        registry = _schema_registry(query_rows={"filter": {"type": "object"}})
        body = _body(
            """
description: A slot inside a payload
steps:
  - id: rows
    tool: query_rows
    args:
      filter:
        note:
          $ask: Say why this run matters
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID)

        assert result.issues == []

    async def test_a_slot_carrying_a_key_the_vocabulary_has_no_room_for_is_refused(self) -> None:
        """The slot vocabulary is two keys. A model that adds ``goal`` has
        written an instruction the runner will never read, so the refusal names
        the argument it sits in and spells out what a slot may hold — one issue,
        not a pydantic dump the author has to decode."""
        body = _body(
            """
description: A slot with an extra key
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject:
        $ask: Write a subject
        goal: sound friendly
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert result.valid is False
        assert [(issue.where, issue.problem) for issue in result.issues] == [
            (
                "steps[0].args.subject",
                "an $ask slot takes only '$ask' (what to write) and an optional "
                "max_tokens 1..8192; got ['$ask', 'goal']",
            )
        ]

    async def test_a_slot_on_a_step_with_no_id_is_refused_so_keys_cannot_collide(
        self,
    ) -> None:
        """A slot's key is its step's id plus the arg path; with no id the tool
        name stands in, so two id-less steps of one tool would share a key and
        the second would silently receive the first's text. Refusing at
        authoring time is the only place the author can still add the id."""
        body = _body(
            """
description: Two searches, neither named
steps:
  - tool: list_events
    args:
      calendar_id:
        $ask: which calendar to read
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert result.valid is False
        assert [issue.where for issue in result.issues] == ["steps[0].args.calendar_id"]
        assert "needs an id" in result.issues[0].problem
        assert "list_events" in result.issues[0].problem

    async def test_a_slot_with_an_empty_prompt_is_refused(self) -> None:
        """A slot with nothing to say is a model call with no instruction; the
        text it writes would be whatever the run happened to look like."""
        body = _body(
            """
description: A slot with no instruction
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject:
        $ask: ""
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert result.valid is False
        assert [issue.where for issue in result.issues] == ["steps[0].args.subject"]
        assert "$ask" in result.issues[0].problem

    async def test_a_slot_whose_max_tokens_is_out_of_range_is_refused(self) -> None:
        """The budget is what keeps one replay's token cost bounded; a slot
        asking for more than the cap must be refused at authoring time rather
        than turning a playbook into an open-ended generation."""
        body = _body(
            """
description: A slot with a runaway budget
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject:
        $ask: Write a subject
        max_tokens: 999999
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert result.valid is False
        assert [issue.where for issue in result.issues] == ["steps[0].args.subject"]
        assert "max_tokens 1..8192" in result.issues[0].problem

    async def test_an_arg_holding_a_slot_is_not_type_checked(self) -> None:
        """A slot is a dict now and the model's text at replay, exactly as a
        placeholder is a string now and whatever it resolves to later. Type-
        checking the unfilled slot would refuse every typed argument a model is
        meant to write."""
        body = _body(
            """
description: A written count
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: hi
      retries:
        $ask: How many retries this deserves
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert result.issues == []

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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
result_brief: x
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
      to: a@b.com
      subject: hi
      bcc: c@d.com
      cc: e@f.com
result_brief: x
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
result_brief: x
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
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID)
        assert result.valid is False
        assert "it takes: nothing" in result.issues[0].problem

    async def test_a_required_arg_the_step_never_sets_is_refused_by_name(self) -> None:
        """Nothing else catches this: the per-arg checks walk the args the step
        HAS, so a call missing a required one is accepted here and fails at
        replay before it starts."""
        body = _body(
            """
description: Mail with half the arguments
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert [(issue.where, issue.problem) for issue in result.issues] == [
            (
                "steps[0].args",
                "send_email requires 'subject' and this step does not set it; "
                "it takes: retries, subject, to",
            )
        ]

    async def test_every_missing_required_arg_is_named_in_sorted_order(self) -> None:
        """Naming one at a time costs the author a round trip each, and the
        order has to be the same every run or the message is not diffable."""
        body = _body(
            """
description: Mail with no arguments at all
steps:
  - id: mail
    tool: send_email
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert [issue.problem for issue in result.issues] == [
            "send_email requires 'subject' and this step does not set it; "
            "it takes: retries, subject, to",
            "send_email requires 'to' and this step does not set it; "
            "it takes: retries, subject, to",
        ]

    @pytest.mark.parametrize(
        "authored",
        ["$user.email", {"$ask": "who this goes to"}],
        ids=["placeholder", "ask-slot"],
    )
    async def test_a_required_arg_filled_at_replay_still_counts_as_set(
        self, authored: object
    ) -> None:
        """The arg is present; only its value is deferred. Refusing it would
        refuse every playbook that addresses the user or writes its own text."""
        body = PlaybookBody.model_validate(
            {
                "description": "Mail the agenda",
                "steps": [
                    {"id": "mail", "tool": "send_email", "args": {"to": authored, "subject": "hi"}}
                ],
                "result_brief": "x",
            }
        )

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert result.issues == []

    async def test_a_tool_that_requires_nothing_is_not_asked_for_anything(self) -> None:
        """An MCP schema with no ``required`` list is not a tool that requires
        every arg; a step calling it with none is complete."""
        registry = _schema_registry(ping={})
        body = _body(
            """
description: Ping
steps:
  - id: one
    tool: ping
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID)

        assert result.issues == []

    @pytest.mark.parametrize(
        "tool_kind",
        ["json-document", "pydantic-v1"],
    )
    async def test_a_required_arg_is_read_from_every_schema_shape_langchain_hands_back(
        self, tool_kind: str
    ) -> None:
        """Decorated tools carry a v2 model, MCP tools a raw JSON document and
        legacy tools a v1 model. ``required`` is spelled the same way on all
        three, but each is read through a different branch, and a branch that
        reads nothing would quietly stop refusing calls that cannot run."""

        class _JsonExec(BaseTool):
            name: str = "run_query"
            description: str = "Run a query"

            def _run(self, **kwargs: Any) -> dict[str, Any]:
                return {}

        json_document: dict[str, Any] = {
            "type": "object",
            "properties": {"code": {"type": "string"}, "lang": {"type": "string"}},
            "required": ["code"],
        }

        class _LegacyArgs(v1.BaseModel):
            code: str
            lang: str = ""

        class _LegacyExec(BaseTool):
            name: str = "run_query"
            description: str = "Run a query"
            args_schema: type[v1.BaseModel] = _LegacyArgs

            def _run(self, **kwargs: Any) -> dict[str, Any]:
                return {}

        exec_tool: BaseTool = (
            _JsonExec(args_schema=json_document) if tool_kind == "json-document" else _LegacyExec()
        )
        body = _body(
            """
description: Run a query with only the optional argument
steps:
  - id: query
    tool: run_query
    args:
      lang: sql
result_brief: x
"""
        )
        with patch(
            f"{MODULE}.get_tool_registry", return_value=_FakeRegistry({"run_query": exec_tool})
        ):
            result = await validate_playbook(body, USER_ID)

        assert [(issue.where, issue.problem) for issue in result.issues] == [
            (
                "steps[0].args",
                "run_query requires 'code' and this step does not set it; it takes: code, lang",
            )
        ]

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
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)
        assert result.issues == []


def _call(tool_name: str, args: dict[str, Any], result: object) -> RecordedResult:
    """One call as the authoring run made it, with what came back."""
    return RecordedResult(tool_name=tool_name, args=args, result=result)


@pytest.mark.unit
class TestValidateAgainstTheRunThatIsWritingIt:
    """The checks that read the authoring run's own results.

    Every case here was a playbook production accepted and then broke on:
    ``pb_c7d357db77dd`` froze a field its tool does not return, and two more
    were frozen from calls that came back empty. The run had every answer in
    hand at write time, and nothing looked at it.
    """

    async def test_a_step_is_matched_to_the_call_whose_literal_args_agree(self) -> None:
        """A tool called twice left two results. If the step is matched to the
        wrong one, this playbook is refused for an emptiness that belongs to the
        other calendar entirely."""
        body = _body(
            """
description: Read the work calendar
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: work
result_brief: x
"""
        )
        results = [
            _call("list_events", {"calendar_id": "work"}, {"events": [{"id": "e1"}]}),
            _call("list_events", {"calendar_id": "primary"}, {"events": []}),
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues == []

    async def test_a_non_string_arg_picks_the_call_that_used_that_value(self) -> None:
        """Numbers agree by equality like anything else. Matched the other way
        round the step is checked against the call it is NOT, and this playbook
        is refused for the emptiness of a run it never froze."""
        body = _body(
            """
description: Mail with two retries
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: hi
      retries: 2
result_brief: x
"""
        )
        results = [
            _call(
                "send_email",
                {"to": "a@b.com", "subject": "hi", "retries": 2},
                {"sent": [{"id": "1"}]},
            ),
            _call("send_email", {"to": "a@b.com", "subject": "hi", "retries": 5}, {"sent": []}),
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues == []

    async def test_an_arg_holding_a_placeholder_matches_any_recorded_value(self) -> None:
        """A placeholder has no value until replay, so it cannot disagree with a
        recorded arg. Treated as a literal it would agree with nothing and the
        step would be checked against the last call — here, the empty one."""
        body = _body(
            """
description: Mail the digest
steps:
  - id: mail
    tool: send_email
    args:
      to: $user.email
      subject: one
result_brief: x
"""
        )
        results = [
            _call("send_email", {"to": "a@b.com", "subject": "one"}, {"sent": [{"id": "1"}]}),
            _call("send_email", {"to": "z@z.com", "subject": "two"}, {"sent": []}),
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues == []

    async def test_a_step_agreeing_with_no_call_is_refused_with_the_args_that_did_run(
        self,
    ) -> None:
        """A step whose args match no recorded call is not a call the run made.
        Handing it the run's last call anyway validated that call's result as
        the step's own, so a `$steps` reference could be approved against a shape
        the replayed args will never return. The refusal shows the args the run
        actually used so the author can freeze the real call."""
        body = _body(
            """
description: Read a third calendar
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: other
result_brief: x
"""
        )
        results = [
            _call("list_events", {"calendar_id": "work"}, {"events": [{"id": "e1"}]}),
            _call("list_events", {"calendar_id": "primary"}, {"events": []}),
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert [(issue.where, issue.problem) for issue in result.issues] == [
            (
                "steps[0]",
                "list_events ran 2 time(s) in this run, but never with these args (the last "
                'call used {"calendar_id": "primary"}); freeze the call that ran, with the '
                "args that produced its result, or run it with these args",
            )
        ]

    async def test_the_refusal_shows_the_args_of_the_last_call_still_unfrozen(self) -> None:
        """Four calls, the first already frozen by an earlier step. The one to
        show is the LAST still-unfrozen call — the run's final attempt — not the
        first, not the second, and not the one another step already took."""
        body = _body(
            """
description: Freeze the work calendar, then a calendar nobody read
steps:
  - id: work
    tool: list_events
    args:
      calendar_id: work
  - id: other
    tool: list_events
    args:
      calendar_id: other
result_brief: x
"""
        )
        results = [
            _call("list_events", {"calendar_id": "work"}, {"events": [{"id": "e1"}]}),
            _call("list_events", {"calendar_id": "primary"}, {"events": [{"id": "e2"}]}),
            _call("list_events", {"calendar_id": "shared"}, {"events": [{"id": "e3"}]}),
            _call("list_events", {"calendar_id": "personal"}, {"events": [{"id": "e4"}]}),
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert [(issue.where, issue.problem) for issue in result.issues] == [
            (
                "steps[1]",
                "list_events ran 4 time(s) in this run, but never with these args (the last "
                'call used {"calendar_id": "personal"}); freeze the call that ran, with the '
                "args that produced its result, or run it with these args",
            )
        ]

    async def test_a_literal_nested_beside_a_placeholder_still_picks_the_call(self) -> None:
        """The two calls differ only inside ``filters``, which also carries a
        placeholder. Treating the whole arg as a wildcard matches the last call
        and refuses this playbook for the spam folder's emptiness."""
        body = _body(
            """
description: Read the inbox
steps:
  - id: mail
    tool: search_mail
    args:
      filters:
        label: INBOX
        after: $today
result_brief: x
"""
        )
        results = [
            _call(
                "search_mail",
                {"filters": {"label": "INBOX", "after": "2026-09-01"}},
                {"messages": [{"id": "m1"}]},
            ),
            _call(
                "search_mail",
                {"filters": {"label": "SPAM", "after": "2026-09-01"}},
                {"messages": []},
            ),
        ]

        registry = _schema_registry(search_mail={"filters": {"type": "object"}})
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues == []

    async def test_a_key_the_recorded_call_lacks_disagrees_with_it(self) -> None:
        """The last call never sent ``label`` at all, so it is not the call this
        step froze — an arg the step names and the record omits is a
        disagreement, not something to shrug at."""
        body = _body(
            """
description: Read the inbox
steps:
  - id: mail
    tool: search_mail
    args:
      filters:
        label: INBOX
        after: $today
result_brief: x
"""
        )
        results = [
            _call(
                "search_mail",
                {"filters": {"label": "INBOX", "after": "2026-09-01"}},
                {"messages": [{"id": "m1"}]},
            ),
            _call("search_mail", {"filters": {"after": "2026-09-01"}}, {"messages": []}),
        ]

        registry = _schema_registry(search_mail={"filters": {"type": "object"}})
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues == []

    async def test_an_ask_slot_nested_in_an_arg_matches_any_recorded_value(self) -> None:
        """Text a model writes at replay does not exist yet, so it agrees with
        whatever sat in that position — while the literal beside it still
        decides which call this is."""
        body = _body(
            """
description: Read the inbox
steps:
  - id: mail
    tool: search_mail
    args:
      filters:
        label: INBOX
        after:
          $ask: Which day to read from
result_brief: x
"""
        )
        results = [
            _call(
                "search_mail",
                {"filters": {"label": "INBOX", "after": "2026-09-01"}},
                {"messages": [{"id": "m1"}]},
            ),
            _call(
                "search_mail",
                {"filters": {"label": "SPAM", "after": "2026-08-01"}},
                {"messages": []},
            ),
        ]

        registry = _schema_registry(search_mail={"filters": {"type": "object"}})
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues == []

    async def test_a_list_arg_agrees_at_its_own_length_only(self) -> None:
        """A placeholder element stands for one value, not for any number of
        them, so a recorded list of another length is a different call."""
        body = _body(
            """
description: Tag the inbox
steps:
  - id: tagged
    tool: tag_mail
    args:
      labels:
        - INBOX
        - $today
result_brief: x
"""
        )
        results = [
            _call("tag_mail", {"labels": ["INBOX", "2026-09-01"]}, {"tagged": [{"id": "m1"}]}),
            _call("tag_mail", {"labels": ["INBOX", "2026-09-01", "SPAM"]}, {"tagged": []}),
        ]

        registry = _schema_registry(tag_mail={"labels": {"type": "array"}})
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues == []

    async def test_a_key_the_step_left_out_does_not_break_agreement(self) -> None:
        """The model writes the args it meant, not every default the tool
        filled in; a recorded key the step never mentions cannot be evidence
        that this is some other call."""
        body = _body(
            """
description: Read the inbox
steps:
  - id: mail
    tool: search_mail
    args:
      filters:
        label: INBOX
result_brief: x
"""
        )
        results = [
            _call(
                "search_mail",
                {"filters": {"label": "INBOX", "after": "2026-09-01"}},
                {"messages": [{"id": "m1"}]},
            ),
            _call("search_mail", {"filters": {"label": "SPAM"}}, {"messages": []}),
        ]

        registry = _schema_registry(search_mail={"filters": {"type": "object"}})
        with patch(f"{MODULE}.get_tool_registry", return_value=registry):
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues == []

    async def test_a_tool_the_run_never_called_is_refused(self) -> None:
        """A playbook freezes calls that ran. A step for a tool this run never
        touched was invented, and its args have never been proven to work."""
        body = _body(
            """
description: Mail an agenda that was never mailed
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: hi
result_brief: x
"""
        )
        results = [_call("list_events", {"calendar_id": "primary"}, {"events": [{"id": "e1"}]})]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert [issue.where for issue in result.issues] == ["steps[0]"]
        assert result.issues[0].problem == (
            "send_email did not run in this run; a playbook freezes calls that ran and "
            "produced their result — run it, or drop the step"
        )

    async def test_a_call_that_returned_no_items_is_refused(self) -> None:
        """Two production playbooks were frozen from a call that returned zero
        items and were marked SUSPECT one fire later. The list is nested under an
        envelope, so the check has to look past the top level."""
        body = _body(
            """
description: Read an empty calendar
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
result_brief: x
"""
        )
        results = [_call("list_events", {"calendar_id": "primary"}, {"data": {"events": []}})]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert [issue.where for issue in result.issues] == ["steps[0]"]
        assert result.issues[0].problem == (
            'list_events returned no items in this run (args: {"calendar_id": "primary"}); '
            "freeze a call that produced data — widen the args or decline the playbook"
        )

    async def test_a_call_that_reported_its_own_failure_is_refused_by_its_error(self) -> None:
        """A tool that catches its own failure answers with a success-shaped
        message carrying an error envelope. Freezing that call freezes a step
        that has never once worked, and the refusal has to name the error the
        author has to fix."""
        body = _body(
            """
description: Mail from an expired token
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: hi
result_brief: x
"""
        )
        results = [
            _call(
                "send_email",
                {"to": "a@b.com", "subject": "hi"},
                {"success": False, "error": "Gmail token expired"},
            )
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert [issue.where for issue in result.issues] == ["steps[0]"]
        assert result.issues[0].problem == (
            "send_email failed in this run (Gmail token expired); a playbook freezes "
            "calls that succeeded — fix the call and run it again, or drop the step"
        )

    @pytest.mark.parametrize(
        ("envelope", "said"),
        [
            ({"success": False, "message": "Gmail token expired"}, "Gmail token expired"),
            ({"success": False}, "the call reported success: false"),
        ],
        ids=["message-key", "said-nothing"],
    )
    async def test_a_failure_with_no_error_key_is_named_by_whatever_it_did_say(
        self, envelope: dict[str, Any], said: str
    ) -> None:
        """Tools spell their failure two ways — an ``error`` and a bare
        ``message`` — and some say only ``success: false``. The refusal is the
        author's only account of why the call failed, so it has to read the
        second spelling and say so plainly when there is no third."""
        body = _body(
            """
description: Mail from a failing tool
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: hi
result_brief: x
"""
        )
        results = [_call("send_email", {"to": "a@b.com", "subject": "hi"}, envelope)]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert [issue.where for issue in result.issues] == ["steps[0]"]
        assert result.issues[0].problem == (
            f"send_email failed in this run ({said}); a playbook freezes "
            "calls that succeeded — fix the call and run it again, or drop the step"
        )

    async def test_the_args_naming_the_empty_call_are_rendered_as_they_were_sent(self) -> None:
        """The args are there to say WHICH call came back empty. Escaped to
        ASCII the author cannot recognise their own query, and a value that is
        not JSON (a datetime the tool was handed) must render rather than crash
        the whole validation."""
        body = _body(
            """
description: Read an empty calendar
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
result_brief: x
"""
        )
        results = [
            _call(
                "list_events",
                {"calendar_id": "primary", "query": "café ☕", "after": datetime(2026, 9, 1)},
                {"events": []},
            )
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues[0].problem == (
            "list_events returned no items in this run "
            '(args: {"calendar_id": "primary", "query": "café ☕", "after": "2026-09-01 00:00:00"}); '
            "freeze a call that produced data — widen the args or decline the playbook"
        )

    @pytest.mark.parametrize(
        ("filler", "rendered"),
        [
            (165, '{"calendar_id": "primary", "q": "' + "x" * 165 + '"}'),
            (166, '{"calendar_id": "primary", "q": "' + "x" * 166 + '"...'),
        ],
        ids=["exactly-at-the-cap", "one-character-over"],
    )
    async def test_long_args_are_cut_at_the_cap_and_marked(
        self, filler: int, rendered: str
    ) -> None:
        """200 characters of args, then an ellipsis. The cap is inclusive: a
        rendering that lands exactly on it is complete and must not be marked as
        cut, or the author goes looking for args that were never dropped."""
        body = _body(
            """
description: Read an empty calendar
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
result_brief: x
"""
        )
        results = [
            _call("list_events", {"calendar_id": "primary", "q": "x" * filler}, {"events": []})
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues[0].problem == (
            f"list_events returned no items in this run (args: {rendered}); "
            "freeze a call that produced data — widen the args or decline the playbook"
        )

    async def test_a_reference_to_a_field_the_result_lacks_is_refused_with_its_keys(self) -> None:
        """``pb_c7d357db77dd`` exactly: a field frozen on a tool that does not
        return it. The keys are the whole point of the message — without them the
        author is told what is wrong and not what it could have written."""
        body = _body(
            """
description: Reply on a thread id that does not exist
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
  - id: mail
    tool: send_email
    args:
      to: $steps.agenda.threadId
      subject: hi
result_brief: x
"""
        )
        results = [
            _call(
                "list_events",
                {"calendar_id": "primary"},
                {"messages": [{"id": "m1"}], "nextPage": "abc"},
            ),
            _call("send_email", {"to": "a@b.com", "subject": "hi"}, {"sent": [{"id": "1"}]}),
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert [issue.where for issue in result.issues] == ["steps[1].args.to"]
        assert result.issues[0].problem == (
            "$steps.agenda.threadId is not in step 'agenda''s result"
            "; its result has keys: messages, nextPage"
        )

    @pytest.mark.parametrize(
        ("key_count", "expected_hint"),
        [
            (12, "; its result has keys: " + ", ".join(f"k{i:02d}" for i in range(12))),
            (13, "; its result has keys: " + ", ".join(f"k{i:02d}" for i in range(12)) + ", ..."),
        ],
        ids=["exactly-the-cap", "one-over-the-cap"],
    )
    async def test_the_keys_hint_lists_up_to_the_cap_and_marks_the_rest(
        self, key_count: int, expected_hint: str
    ) -> None:
        """A wide result must not bury the sentence that says what is wrong, so
        the hint stops at the cap and says there is more. Exactly at the cap
        there is nothing more to say, and the marker must not appear."""
        body = _body(
            """
description: Reply on a field that does not exist
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
  - id: mail
    tool: send_email
    args:
      to: $steps.agenda.threadId
      subject: hi
result_brief: x
"""
        )
        wide = {f"k{i:02d}": i for i in range(key_count)}
        results = [
            _call("list_events", {"calendar_id": "primary"}, wide),
            _call("send_email", {"to": "a@b.com", "subject": "hi"}, {"sent": [{"id": "1"}]}),
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert [issue.problem for issue in result.issues] == [
            "$steps.agenda.threadId is not in step 'agenda''s result" + expected_hint
        ]

    async def test_an_unknown_arg_is_answered_with_the_tools_whole_arg_list(self) -> None:
        """The list is what the author rewrites from, so it has to be the real
        one: every arg, sorted, comma-separated. A one-arg tool cannot show the
        separator, which is how a broken join went unnoticed."""
        body = _body(
            """
description: A misspelt recipient field
steps:
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: hi
      recipient: c@d.com
result_brief: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID)

        assert [(issue.where, issue.problem) for issue in result.issues] == [
            (
                "steps[0].args.recipient",
                "send_email takes no arg 'recipient'; it takes: retries, subject, to",
            )
        ]

    async def test_a_call_the_run_made_once_cannot_be_frozen_twice(self) -> None:
        """Two steps with one tool and the same args both matched the single
        recorded call, and the replay then sent the mail twice for a run that
        sent it once. The second step must be refused, and the message must say
        how many times the tool really ran so the author can tell a duplicate
        from a call that was dropped from the record."""
        body = _body(
            """
description: The same mail, listed twice
steps:
  - id: first
    tool: send_email
    args:
      to: a@b.com
      subject: hi
  - id: again
    tool: send_email
    args:
      to: a@b.com
      subject: hi
result_brief: x
"""
        )
        results = [_call("send_email", {"to": "a@b.com", "subject": "hi"}, {"sent": [{"id": "1"}]})]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert [(issue.where, issue.problem) for issue in result.issues] == [
            (
                "steps[1]",
                "send_email ran 1 time(s) in this run and earlier steps froze every one of "
                "them; a step cannot replay a call the run did not make — drop this step, "
                "or run it again",
            )
        ]

    async def test_a_handoff_child_never_takes_a_top_level_call_of_the_same_tool(self) -> None:
        """The run's results hold nothing for a subagent's calls (the handoff
        record carries their args, not their outputs), so a child is not matched
        at all. Matching it anyway let a child consume the one recorded top-level
        call of the same tool, and the real top-level step behind it was refused
        as a call the run never made."""
        body = _body(
            """
description: The subagent listed events, then the executor did too
steps:
  - id: delegated
    handoff: calendar_agent
    steps:
      - id: theirs
        tool: list_events
        args:
          calendar_id: primary
  - id: mine
    tool: list_events
    args:
      calendar_id: primary
result_brief: x
"""
        )
        results = [_call("list_events", {"calendar_id": "primary"}, {"events": [{"id": "e1"}]})]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()), _handoff_space():
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues == []

    async def test_a_tool_the_run_called_twice_can_be_frozen_twice(self) -> None:
        """The refusal above is about cardinality, not repetition: a run that
        genuinely made the call twice left two records, and two steps may each
        take one. A third step has nothing left and says so with the count."""
        body = _body(
            """
description: Two mails, then one too many
steps:
  - id: first
    tool: send_email
    args:
      to: a@b.com
      subject: hi
  - id: second
    tool: send_email
    args:
      to: a@b.com
      subject: hi
  - id: third
    tool: send_email
    args:
      to: a@b.com
      subject: hi
result_brief: x
"""
        )
        results = [
            _call("send_email", {"to": "a@b.com", "subject": "hi"}, {"sent": [{"id": "1"}]}),
            _call("send_email", {"to": "a@b.com", "subject": "hi"}, {"sent": [{"id": "2"}]}),
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert [issue.where for issue in result.issues] == ["steps[2]"]
        assert result.issues[0].problem.startswith("send_email ran 2 time(s) in this run")

    async def test_a_reference_deeper_than_one_field_is_still_read_from_its_step(self) -> None:
        """``$steps.agenda.organizer.email`` names the step ``agenda`` and the
        path ``organizer.email``. Split from the other end the step is called
        ``agenda.organizer``, nothing in the run answers to it, and a reference
        into a shape the tool does not return is waved through."""
        body = _body(
            """
description: Reply to the organizer
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
result_brief: x
"""
        )
        results = [
            _call("list_events", {"calendar_id": "primary"}, {"organizer": {"name": "Ada"}}),
            _call("send_email", {"to": "a@b.com", "subject": "hi"}, {"sent": [{"id": "1"}]}),
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert [issue.where for issue in result.issues] == ["steps[1].args.to"]
        assert result.issues[0].problem == (
            "$steps.agenda.organizer.email is not in step 'agenda''s result"
            "; its result has keys: organizer"
        )

    async def test_a_result_with_no_keys_to_offer_ends_the_refusal_where_it_is(self) -> None:
        """The keys are a hint, not a sentence: a result that is a bare list has
        none to give, and the refusal has to stop rather than trail off into an
        empty ``has keys:``."""
        body = _body(
            """
description: Reply on a thread id a list cannot carry
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
  - id: mail
    tool: send_email
    args:
      to: $steps.agenda.threadId
      subject: hi
result_brief: x
"""
        )
        results = [
            _call("list_events", {"calendar_id": "primary"}, ["m1", "m2"]),
            _call("send_email", {"to": "a@b.com", "subject": "hi"}, {"sent": [{"id": "1"}]}),
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert [issue.where for issue in result.issues] == ["steps[1].args.to"]
        assert result.issues[0].problem == (
            "$steps.agenda.threadId is not in step 'agenda''s result"
        )

    async def test_a_reference_the_recorded_result_resolves_is_accepted(self) -> None:
        """The check has to accept the shape the run actually produced, nested
        list index included; a refusal here refuses a playbook that replays."""
        body = _body(
            """
description: Reply to the first message
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
  - id: mail
    tool: send_email
    args:
      to: $steps.agenda.messages.0.id
      subject: hi
result_brief: x
"""
        )
        results = [
            _call("list_events", {"calendar_id": "primary"}, {"messages": [{"id": "m1"}]}),
            _call("send_email", {"to": "m1", "subject": "hi"}, {"sent": [{"id": "1"}]}),
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues == []

    async def test_a_reference_to_a_steps_offload_file_is_exempt(self) -> None:
        """``$steps.<id>.file`` addresses the workspace path a step offloaded its
        result to, which exists only at replay. Checked against the authoring
        run's result it is always absent, and every offloading playbook would be
        refused."""
        body = _body(
            """
description: Mail the offloaded agenda
steps:
  - id: agenda
    tool: list_events
    args:
      calendar_id: primary
  - id: mail
    tool: send_email
    args:
      to: a@b.com
      subject: $steps.agenda.file
result_brief: x
"""
        )
        results = [
            _call("list_events", {"calendar_id": "primary"}, {"messages": [{"id": "m1"}]}),
            _call("send_email", {"to": "a@b.com", "subject": "x"}, {"sent": [{"id": "1"}]}),
        ]

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body, USER_ID, results)

        assert result.issues == []

    async def test_without_results_the_verdict_is_the_one_it_was_before(self) -> None:
        """No results is not an empty run. The dev executor route and every
        caller with no graph behind it pass nothing, and must get exactly the
        registry checks they got before — while a run that genuinely made no
        calls is refused."""
        body = _body(VALID_YAML)

        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            without = await validate_playbook(body, USER_ID)
            empty_run = await validate_playbook(body, USER_ID, [])

        assert without.valid is True
        assert without.issues == []
        assert [issue.where for issue in empty_run.issues] == ["steps[0]", "steps[1]"]


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
result_brief: x
"""
        )
        rendered = dump_playbook(body)
        assert "Résumé für das Team" in rendered

    def test_keys_stay_in_authored_order_with_the_result_brief_last(self) -> None:
        """Alphabetising would put ``description`` after ``result_brief`` and
        scatter each step's ``id``/``tool``/``args``, so the document stops
        reading like the sequence it describes. ``result_brief`` comes last
        because it is written from what every step above it returned."""
        body = _body(VALID_YAML)
        rendered = dump_playbook(body)
        assert rendered.index("description:") < rendered.index("steps:")
        assert rendered.index("steps:") < rendered.index("result_brief:")
        assert rendered.index("id: agenda") < rendered.index("args:")

    def test_the_document_carries_no_ask_section_of_its_own(self) -> None:
        """Asks stopped being a section when they moved inline. Rendering one
        anyway would teach the agent reading its playbook back to author the
        shape whose dead entries this change exists to make impossible."""
        rendered = dump_playbook(_body(VALID_YAML))
        assert set(yaml.safe_load(rendered)) == {"description", "steps", "result_brief"}

    def test_an_ask_slot_renders_inside_the_argument_it_stands_in(self) -> None:
        """The agent revises the playbook from this YAML, so a slot has to read
        where its value belongs. Rendered anywhere else — or flattened to a
        marker — the agent could not tell which argument a model writes."""
        rendered = dump_playbook(_body(VALID_YAML))

        mail = yaml.safe_load(rendered)["steps"][1]
        assert mail["args"]["subject"] == {"$ask": "Write the agenda as a short note"}
        assert "$ask: Write the agenda as a short note" in rendered


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

    def test_an_ask_slot_written_into_an_arg_reaches_the_stored_body(self) -> None:
        """A slot is ordinary argument data all the way through the conversion.

        The tool boundary no longer has an ``ask`` parameter to drop, so a slot
        lost here would be lost silently: the playbook stores and replays, and
        the step simply sends nothing where the written text belonged.
        """
        body = playbook_body_from_input(
            description="Mail the agenda",
            steps=[
                PlaybookStepInput(id="events", tool="list_events", args={"calendar_id": "x"}),
                PlaybookStepInput(
                    id="mail",
                    tool="send_email",
                    args={"to": "a@b.com", "subject": {"$ask": "Write the digest."}},
                ),
            ],
            result_brief="Say how many events there were.",
        )

        assert body.steps[1].args["subject"] == {"$ask": "Write the digest."}
        assert body.result_brief == "Say how many events there were."

    def test_an_ask_slot_inside_a_handoff_child_survives_the_conversion(self) -> None:
        """A handoff's children are converted through their own model, so a slot
        in one has a second chance to be dropped on the way to the stored body."""
        child = PlaybookHandoffStepInput(
            id="mail", tool="send_email", args={"subject": {"$ask": "Write the digest."}}
        )

        assert child.to_step().args == {"subject": {"$ask": "Write the digest."}}
