"""Prompts and tool descriptions for the agent task management tools."""

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
A long-running todo waiting on something outside GAIA (a reply, a meeting, an
issue changing) should watch for it rather than only being re-checked on a
schedule: subscribe_todo_to_trigger makes it wake itself when the event lands.
Call list_trigger_fields first to see what a trigger actually delivers (call it with
a wrong name to list every subscribable trigger); conditions must name real payload fields.
Scope the watch to the specific thing you are waiting for, keyed on what identifies it
(a sender domain, an order or invoice number, a subject token), not broad generic words,
so it fires on the real event and little else. If it later proves noisy, tighten it.
Only the executor creates these; subagents NEVER create tracked todos.
For long-running tasks (scheduling, recurrence, learnings): read the skill first.

QUICK DECISION:
- "I need to organize my current steps" → plan_tasks
- "GAIA is doing something the user might ask about later" → create_tracked_todo"""

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


# Guidance shown to a tracked todo woken by a trigger it subscribed to. The watch was
# meant to be well scoped, but reality is the test: judge each fire, and if the same
# watch keeps waking the run on things that do not qualify, it is too loose and should
# be tightened rather than paying for an agent run on every false positive.
TRIGGERED_RELEVANCE_GUIDANCE = (
    "Before you act, decide whether this event is actually the thing this todo is "
    "watching for. Treat a fire as a candidate to verify, not proof. If it is not "
    "relevant, do not act on it: add a one-line non-match note to the canvas (what "
    "fired, why it did not qualify) and leave the todo unchanged. If the canvas shows "
    "this same watch has now woken you on two or three things that did not qualify, the "
    "watch is too loose: tighten it so it stops costing a run on noise. Unsubscribe the "
    "current watch and re-subscribe with narrower conditions keyed on what actually "
    "distinguishes the real thing (a specific sender domain, an order or invoice number, "
    "a subject token), then note what you tightened and why."
)
