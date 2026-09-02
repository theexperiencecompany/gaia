"""What GAIA can do, written from the code that does it.

The comms agent used to know nothing about todos, workflows or the built-in
workflows beyond what it improvised, so it either dumped a capability menu or
promised things that do not exist. This block is generated from the todo
model, the trigger enum and the system-workflow registry, so a new built-in
workflow or trigger type shows up here without anyone editing prose, and
nothing here can drift from what the product ships.

Prompt prose rules apply (no dashes, human voice); the hygiene tests scan the
rendered prompt.
"""

from app.config.oauth_config import get_integration_by_id
from app.models.trigger_configs import CalendarEventStartingSoonConfig
from app.models.workflow_models import CreateWorkflowRequest, TriggerConfig, TriggerType
from app.services.system_workflows.definitions import SYSTEM_WORKFLOWS_BY_INTEGRATION

CAPABILITY_SECTION_HEADER = "## What GAIA can do (written from the code, so it is ground truth)"

_TODOS = (
    "TODOS: a todo is a structured object GAIA can act on. Each one carries a title, a "
    "description, up to ten labels, a project, a priority (high, medium, low or none), a due "
    "date in the user's timezone and subtasks. The strong part: a todo can be TRACKED, which "
    "means GAIA works it rather than the user. A tracked todo has a scheduled time or a "
    "recurrence (daily, weekly, every few hours, or a cron expression, always in the user's "
    "timezone), and GAIA runs it then, keeping a canvas of the work product and a log of what "
    "it did. A todo can also generate its own workflow (a step-by-step plan) with one ask. "
    "Todos are created from chat, from email action items, or by workflows."
)

_WORKFLOWS = (
    "WORKFLOWS: a workflow is a multi-step plan GAIA executes on its own with the user's "
    "connected tools (read mail, draft replies, search the web, write todos, message the "
    "user). The user describes the outcome in plain words and GAIA generates the steps; they "
    "can edit, activate, pause, run on demand, or reset a built-in one to its default. A "
    "workflow that finishes reports back on whatever channel the user is on."
)

_TRIGGER_TEXT: dict[TriggerType, str] = {
    TriggerType.MANUAL: "manual, run when the user asks",
    TriggerType.SCHEDULE: "schedule, a cron cadence evaluated in the user's timezone (daily at 8am, weekdays at 9, every Monday)",
    TriggerType.INTEGRATION: "integration events, fired by a connected service (a calendar event starting soon, new mail, a repo event)",
    TriggerType.SCHEDULED_TODO: "scheduled_todo, a tracked todo firing on its own schedule",
    TriggerType.TODO_TRIGGER: "todo_trigger, a tracked todo woken by an integration event it watches",
}


def _describe_cron(cron: str) -> str:
    fields = cron.split()
    if len(fields) == 5 and fields[2] == "*" and fields[3] == "*":
        minute, hour, _, _, weekday = fields
        if minute.isdigit() and hour.isdigit():
            clock = f"{int(hour):02d}:{int(minute):02d}"
            if weekday == "*":
                return f"every day at {clock} in their timezone"
            return f"on cron days {weekday} at {clock} in their timezone"
    return f"on the cron schedule {cron} in their timezone"


def _describe_trigger(trigger: TriggerConfig) -> str:
    if trigger.type is TriggerType.SCHEDULE and trigger.cron_expression:
        return _describe_cron(trigger.cron_expression)
    if trigger.type is TriggerType.INTEGRATION:
        data = trigger.trigger_data
        if isinstance(data, CalendarEventStartingSoonConfig):
            return f"{data.minutes_before_start} minutes before any calendar event"
        return f"on the {trigger.trigger_name or 'integration'} event"
    return "when the user runs it"


def _describe_workflow(integration_name: str, workflow: CreateWorkflowRequest) -> str:
    steps = ", ".join(step.title.rstrip(".") for step in workflow.steps or [])
    description = (workflow.description or "").rstrip(".")
    line = f"- {integration_name}: {workflow.title}, {_describe_trigger(workflow.trigger_config)}. {description}."
    return f"{line} Steps: {steps}." if steps else line


def _integration_name(integration_id: str) -> str:
    integration = get_integration_by_id(integration_id)
    return integration.name if integration else integration_id


def build_capability_block() -> str:
    trigger_kinds = "; ".join(_TRIGGER_TEXT[kind] for kind in TriggerType)
    triggers = f"TRIGGERS: a run starts one of these ways: {trigger_kinds}."
    workflows = "\n".join(
        _describe_workflow(_integration_name(integration_id), factory())
        for integration_id, entries in SYSTEM_WORKFLOWS_BY_INTEGRATION.items()
        for _, factory in entries
    )
    built_in = (
        "BUILT-IN WORKFLOWS: the moment an integration is connected, GAIA provisions these for "
        f"the user automatically (each can be paused, edited or reset to default):\n{workflows}"
    )
    return f"{CAPABILITY_SECTION_HEADER}\n\n{_TODOS}\n\n{_WORKFLOWS}\n\n{triggers}\n\n{built_in}"


CAPABILITY_BLOCK = build_capability_block()
