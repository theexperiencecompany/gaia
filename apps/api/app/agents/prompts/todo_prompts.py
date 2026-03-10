"""
Prompts and tool descriptions for agent task management tools.

This file contains all text content for the todo management tools:
- System prompts
- Tool descriptions
"""

# System prompt appended to model context
TODO_SYSTEM_PROMPT = """You have task management tools (plan_tasks, update_tasks).
Use them for complex multi-step work requiring 3+ steps.
update_tasks handles both status changes and adding new tasks in one call.
Do not use these tools for simple tasks that can be done in 1-2 steps."""

# Tool description for plan_tasks
PLAN_TASKS_DESCRIPTION = """Create a structured task list for complex multi-step work.

Use when:
- Starting work that requires 3+ steps
- User provides multiple things to do
- You need to organize complex work

The first task will be automatically marked as in_progress.
Do NOT use this for simple tasks that can be done quickly."""

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
Valid statuses: in_progress, completed, cancelled."""
