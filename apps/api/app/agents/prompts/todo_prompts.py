"""Prompts and tool descriptions for the agent task management tools."""

import re

# "remind/check/follow up N <units> before <deadline>" anchors work to a future
# deadline. A fire-once reminder cannot do that work; only a tracked todo with
# due_date (the deadline) + scheduled_at (the lead-time run) can.
DEADLINE_ANCHORED_PATTERN = re.compile(
    r"\b(?:remind|reminder|check|follow\s+up|notify|alert)\b"
    r"[^?!.\n]{0,120}?"
    r"\b(?:\d+|one|two|three|four|five|six|a|an)\s+"
    r"(?:day|week|month|hour)s?\s+(?:before|prior\s+to|ahead\s+of)\b",
    re.IGNORECASE,
)

DEADLINE_ROUTING_NUDGE = (
    "ROUTING NOTE: this request anchors work to a future deadline ('N days before X'). "
    "A one-shot reminder can only ping once and holds no context. If GAIA should verify, "
    "prepare, collect, or follow up before that deadline, use create_tracked_todo: "
    "due_date = the deadline itself, scheduled_at = when GAIA should act."
)


def deadline_routing_nudge(latest_human_text: str | None) -> str:
    """Return the creation-routing nudge when the message is deadline-anchored."""
    if latest_human_text and DEADLINE_ANCHORED_PATTERN.search(latest_human_text):
        return DEADLINE_ROUTING_NUDGE
    return ""


# System prompt appended to model context
TODO_SYSTEM_PROMPT = """You have TWO separate task systems: do not confuse them.

## EXECUTION PLANS (plan_tasks / update_tasks)
Ephemeral step tracking for YOUR current work. Use for 2+ step tasks.
These disappear after execution. Not saved anywhere.

## GAIA TRACKED TODOS (create_tracked_todo / update_tracked_todo)
GAIA-managed todos that show on the user's todos page but carry a canvas of GAIA's working
notes. They are distinct from the user's own day-to-day action items (those live in providers
like Todoist, Google Tasks, Apple Reminders, etc.).
Create only when GAIA itself performs or schedules a real action on an external system that it
needs to remember, follow up on, or repeat (sent an email, created an issue, posted to Slack,
scheduled recurring work). Reads never qualify: fetching, listing, searching, or summarizing
data never creates a tracked todo, no matter how complex it is or how often it runs, and saving
a summary as a todo is not tracking. One todo per initiative.
Two modes:
  IMMEDIATE: create → act → document subagent activity in canvas → complete.
  LONG-RUNNING: create → act → update canvas → leave open for future follow-up.
Only the executor creates these; subagents NEVER create tracked todos.
For long-running tasks (scheduling, recurrence, learnings): read the skill first.

QUICK DECISION:
- "I need to organize my current steps" → plan_tasks
- "GAIA is doing something the user might ask about later" → create_tracked_todo

DEADLINE-ANCHORED REQUESTS:
"Remind me 3 days before my visa appointment", "check my documents a week before
the filing date": these are NOT reminders. A reminder fires one notification and
forgets. Create a tracked todo instead: due_date = the deadline itself (the
appointment, filing, or expiry date), scheduled_at = the lead time when GAIA
should act. GAIA then runs before the deadline with full canvas context and can
ask the user questions.
Examples:
  User: "Renew my passport before my visa interview on 2026-03-20, remind me 5 days prior"
  → create_tracked_todo(title="Passport renewal for visa interview",
    due_date="2026-03-20T09:00:00+05:30", scheduled_at="2026-03-15T09:00:00+05:30")
  User: "Remind me in 10 minutes to join the call"
  → create_reminder_tool(delay_seconds=600). Plain ping, nothing to do first,
    no tracking needed."""

# Tool description for plan_tasks
PLAN_TASKS_DESCRIPTION = """Create an execution plan for your current multi-step work.

These steps are EPHEMERAL: they track YOUR progress right now, not the user's long-term tasks.
The first task is automatically marked as in_progress.

Use when: 2+ steps needed for the current request.
Do NOT use for: persistent user tasks (use create_tracked_todo instead)."""

# Tool description for update_tasks
UPDATE_TASKS_DESCRIPTION = """Update task statuses and/or add new tasks in a single call.

Each entry in `updates` can either:
- Update an existing task: provide task_id + status
- Add a new task: provide only content (no task_id)

Mix both in one call as needed.

Examples:
  # Mark current done, start next, and add a discovered task
  update_tasks(updates=[
    {"task_id": "abc123", "status": "completed"},
    {"task_id": "def456", "status": "in_progress"},
    {"content": "Also fix the related bug"},
  ])

  # Just add a new task
  update_tasks(updates=[{"content": "Review output before sending"}])

Use the task IDs shown in brackets in your task list, e.g., (abc123).
Valid statuses: in_progress, completed, cancelled.

NOTE: These update execution plan steps, not user-facing todos.
To create/update persistent tasks, use create_tracked_todo / update_tracked_todo."""
