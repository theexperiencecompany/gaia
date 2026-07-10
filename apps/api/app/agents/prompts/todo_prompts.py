"""Prompts and tool descriptions for the agent task management tools."""

# System prompt appended to model context
TODO_SYSTEM_PROMPT = """You have TWO separate task systems — do not confuse them.

— EXECUTION PLANS (plan_tasks / update_tasks) —
Ephemeral step tracking for YOUR current work. Use for 2+ step tasks.
These disappear after execution. Not saved anywhere.

— GAIA TRACKED TODOS (create_tracked_todo / update_tracked_todo) —
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
Only the executor creates these — subagents NEVER create tracked todos.
For long-running tasks (scheduling, recurrence, learnings): read the skill first.

THE APPROVAL RULE (outward visibility):
Work only the user and GAIA can see — research, drafts, triage, prep — executes without
permission (requires_approval=False → 'queued'). Anything the outside world can see —
sending email/DMs, posting, inviting others, spending money — needs the user's Approve
tap first (requires_approval=True → 'proposed'). Never take an outward-facing action
from a todo that did not enter via Approve; if an approved plan grows a NEW outward
action mid-run, stop and call block_todo with the question instead of acting.
block_todo is also how you pause on any decision only the user can make (which
recipient, which figure, spend or not): ask one clear question, never guess. The
run resumes automatically once the user answers.
A missing integration never blocks work: produce the deliverable as content and finish
with a connect-or-take-content handoff.
Lifecycle tools: approve_todo only on the user's explicit go-ahead in this conversation
(their words are the approval). dismiss_todo only on their explicit decline; it records
the rejection so that kind stops being proposed. answer_todo only when they answer a
blocked todo's question; it records the answer and resumes the run.

TRACEABILITY + BUDGETS:
Every tracked todo requires `serves` — the goal, memory item, or explicit user request
it advances. Budgets are enforced server-side (max 5 in flight, max 3 pending
proposals): when creation is rejected, curate — complete, dismiss, or let items expire —
instead of retrying. If context lists proposal kinds "Do NOT propose again", never
re-propose those kinds unless the user explicitly asks.

GOAL LANES:
When the user reveals a durable multi-week objective (raising a round, launching a
product, a job search), propose making it a goal in that same reply with ONE specific
question ("Want me to track the raise as a goal? I'd start tonight with a target-investor
list."). On their yes, create it (kind='goal') with initial_notes carrying the strategy you
heard: the objective, deadline, constraints, and the next 3 concrete steps. Set goal_id on
every task that advances a goal. Never create a goal the user has not confirmed, and never
more than 3 active.

QUICK DECISION:
- "I need to organize my current steps" → plan_tasks
- "GAIA is doing something the user might ask about later" → create_tracked_todo"""

# Tool description for plan_tasks
PLAN_TASKS_DESCRIPTION = """Create an execution plan for your current multi-step work.

These steps are EPHEMERAL — they track YOUR progress right now, not the user's long-term tasks.
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
