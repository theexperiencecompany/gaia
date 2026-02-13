"""
Prompts and tool descriptions for TodoMiddleware.

This file contains all text content for the todo management tools:
- System prompts
- Tool descriptions
"""

# System prompt appended to model context
TODO_SYSTEM_PROMPT = """You have task management tools (plan_tasks, mark_task, add_task).
Use them for complex multi-step work requiring 3+ steps.
mark_task accepts a list — batch status changes in one call (e.g., mark current completed + next in_progress).
Do not use these tools for simple tasks that can be done in 1-2 steps."""

# Tool description for plan_tasks
PLAN_TASKS_DESCRIPTION = """Create a structured task list for complex multi-step work.

Use when:
- Starting work that requires 3+ steps
- User provides multiple things to do
- You need to organize complex work

The first task will be automatically marked as in_progress.
Do NOT use this for simple tasks that can be done quickly."""

# Tool description for mark_task
MARK_TASK_DESCRIPTION = """Update one or more task statuses in a single call.

Accepts a list of updates — batch transitions together.
Common pattern: mark current task completed + next task in_progress in one call.

Example:
  mark_task(updates=[
    {"task_id": "abc123", "status": "completed"},
    {"task_id": "def456", "status": "in_progress"}
  ])

Use the task IDs shown in brackets, e.g., (abc123)."""

# Tool description for add_task
ADD_TASK_DESCRIPTION = """Add a new task discovered during execution.

Use when you discover additional work is needed that wasn't in the original plan.
The task is added to the end of the list as pending."""
