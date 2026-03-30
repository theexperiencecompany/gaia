"""
Prompts and tool descriptions for agent task management tools.

This file contains all text content for the todo management tools:
- System prompts
- Tool descriptions
"""

# System prompt appended to model context
TODO_SYSTEM_PROMPT = """You have TWO separate task systems — do not confuse them.

— EXECUTION PLANS (plan_tasks / update_tasks) —
Ephemeral step tracking for YOUR current work. Use for 2+ step tasks.
These disappear after execution. Not saved anywhere.

— GAIA TRACKED TODOS (create_tracked_todo / update_tracked_todo) —
GAIA's memory of what it did, when, and how — not the user's todo list.
These track long-term goals, projects, and multi-conversation initiatives. They are NOT the user's day-to-day action items (those live in providers like Todoist, Google Tasks, Apple Reminders, etc.).
Create for ANY action touching external systems (email, calendar, Slack, etc.),
even if it completes immediately. One todo per initiative.
Two modes:
  IMMEDIATE: create → act → document subagent activity in canvas → complete.
  LONG-RUNNING: create → act → update canvas → leave open for future follow-up.
Only the executor creates these — subagents NEVER create tracked todos.
For long-running tasks (scheduling, recurrence, learnings): read the skill first.

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
