"""Parsing and validating a playbook document.

The parser is what the authoring agent argues with: a rejected write must say
which node is wrong and why, so every assertion here is on the offending name
appearing in the message, not merely on "it failed".
"""

from typing import Annotated, Any
from unittest.mock import patch

from langchain_core.tools import BaseTool, tool
import pytest

from app.services.workflow.playbook.parser import (
    PlaybookParseError,
    parse_playbook,
    validate_playbook,
)

MODULE = "app.services.workflow.playbook.parser"


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


def _registry() -> _FakeRegistry:
    return _FakeRegistry({"send_email": send_email, "list_events": list_events})


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


@pytest.mark.unit
class TestParsePlaybook:
    def test_valid_yaml_round_trips(self) -> None:
        body = parse_playbook(VALID_YAML)
        assert body.description == "Mail the day's agenda"
        assert [step.id for step in body.steps] == ["agenda", "mail"]
        assert body.steps[1].args["subject"] == "Agenda for $today"
        assert body.ask["body"].uses == ["agenda"]
        assert body.synthesize == "Say what was sent."

    def test_step_with_both_tool_and_handoff_is_rejected_by_name(self) -> None:
        raw = """
description: Confused
steps:
  - id: both_shapes
    tool: send_email
    handoff: mail_agent
    steps:
      - id: inner
        tool: send_email
synthesize: x
"""
        with pytest.raises(PlaybookParseError) as exc:
            parse_playbook(raw)
        assert "both_shapes" in exc.value.message

    def test_handoff_without_children_is_rejected(self) -> None:
        raw = """
description: Empty handoff
steps:
  - id: delegate
    handoff: mail_agent
synthesize: x
"""
        with pytest.raises(PlaybookParseError) as exc:
            parse_playbook(raw)
        assert "mail_agent" in exc.value.message

    def test_unknown_top_level_key_is_rejected_by_name(self) -> None:
        raw = """
description: Extra key
version: 3
steps:
  - id: one
    tool: send_email
synthesize: x
"""
        with pytest.raises(PlaybookParseError) as exc:
            parse_playbook(raw)
        assert "version" in exc.value.message

    def test_broken_yaml_is_rejected(self) -> None:
        with pytest.raises(PlaybookParseError):
            parse_playbook("description: [unclosed\nsteps:")


@pytest.mark.unit
class TestValidatePlaybook:
    async def test_valid_playbook_has_no_issues(self) -> None:
        body = parse_playbook(VALID_YAML)
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body)
        assert result.valid is True
        assert result.issues == []

    async def test_unknown_tool_is_rejected_by_name(self) -> None:
        body = parse_playbook(
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
            result = await validate_playbook(body)
        assert result.valid is False
        assert any("send_owl" in issue.problem for issue in result.issues)

    async def test_unknown_arg_key_is_rejected(self) -> None:
        body = parse_playbook(
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
            result = await validate_playbook(body)
        assert result.valid is False
        assert [issue.where for issue in result.issues] == ["steps[0].args.bcc"]
        assert "bcc" in result.issues[0].problem

    async def test_wrong_arg_type_is_rejected(self) -> None:
        body = parse_playbook(
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
            result = await validate_playbook(body)
        assert result.valid is False
        assert result.issues[0].where == "steps[0].args.retries"
        assert "integer" in result.issues[0].problem

    async def test_forward_step_reference_is_rejected(self) -> None:
        body = parse_playbook(
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
            result = await validate_playbook(body)
        assert result.valid is False
        assert result.issues[0].where == "steps[0].args.to"
        assert "$steps.agenda" in result.issues[0].problem

    async def test_backward_step_reference_inside_handoff_resolves(self) -> None:
        body = parse_playbook(
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
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body)
        assert result.issues == []

    async def test_undeclared_ask_reference_is_rejected(self) -> None:
        body = parse_playbook(
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
            result = await validate_playbook(body)
        assert result.valid is False
        assert "$ask.headline" in result.issues[0].problem

    async def test_unknown_placeholder_namespace_is_rejected(self) -> None:
        body = parse_playbook(
            """
description: Invented namespace
steps:
  - id: mail
    tool: send_email
    args:
      to: $sender.email
      subject: hi
synthesize: x
"""
        )
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body)
        assert result.valid is False
        assert "$sender.email" in result.issues[0].problem

    async def test_last_run_reference_is_accepted_unresolved(self) -> None:
        body = parse_playbook(
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
            result = await validate_playbook(body)
        assert result.issues == []

    async def test_ask_uses_an_undeclared_step_is_rejected(self) -> None:
        body = parse_playbook(
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
            result = await validate_playbook(body)
        assert result.valid is False
        assert result.issues[0].where == "ask.body.uses"
