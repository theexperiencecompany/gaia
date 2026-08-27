"""The playbook grammar, and validation against the live tool registry.

Both are what the authoring agent argues with: a rejected write must say which
node is wrong and why, so every assertion here is on the offending name
appearing in the message, not merely on "it failed".

The grammar itself is enforced by the models, since the structured tool schema
is the only way a playbook is ever authored — nothing parses YAML back.
"""

from typing import Annotated, Any
from unittest.mock import patch

from langchain_core.tools import BaseTool, tool
from pydantic import ValidationError
import pytest
import yaml

from app.models.playbook_models import PlaybookBody
from app.services.workflow.playbook.parser import validate_playbook

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
            result = await validate_playbook(body)
        assert result.valid is True
        assert result.issues == []

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
            result = await validate_playbook(body)
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
            result = await validate_playbook(body)
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
            result = await validate_playbook(body)
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
            result = await validate_playbook(body)
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
        with patch(f"{MODULE}.get_tool_registry", return_value=_registry()):
            result = await validate_playbook(body)
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
            result = await validate_playbook(body)
        assert result.valid is False
        assert "$ask.headline" in result.issues[0].problem

    async def test_unknown_placeholder_namespace_is_rejected(self) -> None:
        body = _body(
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
            result = await validate_playbook(body)
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
            result = await validate_playbook(body)
        assert result.valid is False
        assert result.issues[0].where == "ask.body.uses"
