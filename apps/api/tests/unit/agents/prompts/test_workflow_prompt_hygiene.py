"""A workflow's `prompt` is instructions, not a copy of its own config.

The scheduler has already fired the run and the trigger data is already handed
over by the time the executor reads `prompt`, so "Every morning at 9am:" and
"When a new email arrives in Gmail:" are inert text the run cannot act on. Two
separate LLMs write that field, and they had drifted: the editor's generator
banned schedule and trigger language outright while the chat assistant said
nothing about it and demonstrated the opposite in all three of its worked
examples. The examples are the stronger signal, so that is what shipped.

These tests pin both halves: one contract, spliced into both authors, and no
worked example that contradicts it.
"""

import json
import re

import pytest

from app.agents.prompts.subagent_prompts import WORKFLOW_AGENT_SYSTEM_PROMPT
from app.agents.prompts.workflow_prompts import (
    TODO_WORKFLOW_PROMPT_TEMPLATE,
    WORKFLOW_INSTRUCTIONS_CONTRACT,
    WORKFLOW_PROMPT_GENERATION_SYSTEM,
)

#: Every LLM that authors a workflow's `prompt`. Both must carry the contract,
#: or the one that doesn't drifts back to writing config into the field.
PROMPT_AUTHORS = {
    "workflow assistant (chat)": WORKFLOW_AGENT_SYSTEM_PROMPT,
    "instructions generator (editor)": WORKFLOW_PROMPT_GENERATION_SYSTEM,
}

#: Config text that says WHEN a run happens. The value it carries is already on
#: the workflow's trigger_config, so in the instructions it is pure noise.
SCHEDULE_TELLS = (
    re.compile(r"\bevery (morning|day|night|week|month|hour|monday|weekday)", re.I),
    re.compile(r"\bat \d{1,2}\s*(am|pm|:\d{2})", re.I),
    re.compile(r"\b\d{1,2}\s*(am|pm)\b", re.I),
    re.compile(r"\b(daily|weekly|hourly|cron)\b", re.I),
)

#: Config text that says WHAT STARTED the run. Same story: it lives on the
#: trigger, and the executor is told why it was invoked.
TRIGGER_TELLS = (
    re.compile(r"^\s*when\b", re.I),
    re.compile(r"^\s*before (each|every)\b", re.I),
    re.compile(r"\bwhen (a|an|the) .{0,40}(arrives|is opened|is created|fires)", re.I),
)


def _finalized_example_prompts(system_prompt: str) -> list[str]:
    """The `prompt` value of every finalized workflow the prompt demonstrates."""
    prompts: list[str] = []
    for block in re.findall(r"```json\s*(.*?)```", system_prompt, re.DOTALL):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("type") == "finalized":
            prompts.append(str(payload.get("prompt", "")))
    return prompts


@pytest.mark.unit
class TestWorkflowInstructionsContract:
    def test_every_prompt_author_carries_the_same_contract(self) -> None:
        """One copy, spliced into both. Two hand-maintained copies is how the
        assistant ended up with no rule at all while the generator had one."""
        for name, prompt in PROMPT_AUTHORS.items():
            assert WORKFLOW_INSTRUCTIONS_CONTRACT in prompt, (
                f"{name} does not carry WORKFLOW_INSTRUCTIONS_CONTRACT"
            )

    def test_the_assistant_demonstrates_at_least_one_finalized_workflow(self) -> None:
        """Guards the two tests below: if the examples stop parsing, those pass
        vacuously and stop protecting anything."""
        assert len(_finalized_example_prompts(WORKFLOW_AGENT_SYSTEM_PROMPT)) >= 3


@pytest.mark.unit
class TestWorkedExamplesMatchTheContract:
    def test_no_example_prompt_states_when_the_run_happens(self) -> None:
        for prompt in _finalized_example_prompts(WORKFLOW_AGENT_SYSTEM_PROMPT):
            for tell in SCHEDULE_TELLS:
                assert not tell.search(prompt), (
                    f"example prompt states its own schedule ({tell.pattern!r}): {prompt[:120]!r}"
                )

    def test_no_example_prompt_restates_its_trigger(self) -> None:
        for prompt in _finalized_example_prompts(WORKFLOW_AGENT_SYSTEM_PROMPT):
            for tell in TRIGGER_TELLS:
                assert not tell.search(prompt), (
                    f"example prompt restates its trigger ({tell.pattern!r}): {prompt[:120]!r}"
                )


@pytest.mark.unit
class TestTodoWorkflowPrompt:
    def test_it_carries_the_task_and_not_how_the_workflow_was_made(self) -> None:
        """This template IS the stored prompt for a todo-generated workflow, so
        every word about where the workflow came from and when the user runs it
        is config the executor reads as its goal."""
        rendered = TODO_WORKFLOW_PROMPT_TEMPLATE.format(
            title="Book the venue for the offsite",
            details_section="**Details:** capacity 40, budget 2k",
        )
        assert "Book the venue for the offsite" in rendered
        assert "capacity 40, budget 2k" in rendered
        for config_text in ("automatically generated", "Run Workflow", "todo-driven"):
            assert config_text not in rendered, f"prompt narrates its own config: {config_text!r}"
