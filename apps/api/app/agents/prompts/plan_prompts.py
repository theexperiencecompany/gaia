"""Tool descriptions for the executor's ephemeral execution plan (plan_tasks / update_tasks)."""

PLAN_TASKS_DESCRIPTION = """Create an execution plan for your current multi-step work.

These steps are EPHEMERAL: they track YOUR progress right now, not the user's tasks.
The first step is automatically marked as in_progress.

Use when: 2+ steps needed for the current request.
Do NOT use for: work that outlives this turn or a to-do of the user's (use create_task instead)."""

UPDATE_TASKS_DESCRIPTION = """Update step statuses and/or add new steps in a single call.

Each entry in `updates` can either:
- Update an existing step: provide task_id + status
- Add a new step: provide only content (no task_id)

Mix both in one call as needed.

Examples:
  # Mark current done, start next, and add a discovered step
  update_tasks(updates=[
    {"task_id": "abc123", "status": "completed"},
    {"task_id": "def456", "status": "in_progress"},
    {"content": "Also fix the related bug"},
  ])

  # Just add a new step
  update_tasks(updates=[{"content": "Review output before sending"}])

Use the step IDs shown in brackets in your plan, e.g., (abc123).
Those IDs are wiring for tool calls only: never repeat one in user-visible text.
Valid statuses: in_progress, completed, cancelled.

NOTE: These update execution plan steps, not the user's tasks.
To create or change a task, use create_task / update_task."""
