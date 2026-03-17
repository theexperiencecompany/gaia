---
name: gaia-task-tracking
description: Track multi-step work across time and channels using GaiaTasks. Auto-create tasks for work that expects responses, involves multiple steps, or needs monitoring. Manage task lifecycle with VFS-backed working memory.
target: executor
---

# GaiaTask Tracking

## When to Use

**CREATE a GaiaTask when:**
- You sent an email and expect a reply (e.g. "email Rahul about the contract")
- The request involves multiple steps across time (e.g. "plan the offsite and book everything")
- Work spans multiple providers (e.g. "create a Linear issue, then update the Notion doc when it's done")
- The user asks you to monitor or follow up on something
- You're coordinating something that won't resolve in this conversation

**DO NOT create a GaiaTask when:**
- The action is one-shot with no follow-up (e.g. "what's the weather?")
- The task completes entirely within this conversation
- It's a simple lookup or question

**UPDATE an existing GaiaTask when:**
- You take any action related to an active task (sent follow-up, received reply, made progress)
- The status changes (waiting for response, stalled, back to active)

**COMPLETE or CANCEL a GaiaTask when:**
- The goal has been fully achieved → complete_gaia_task
- The user says to stop tracking it or it's no longer relevant → cancel_gaia_task

## Strategy

### Check Before Creating
Before creating a new task, always call `list_gaia_tasks` first. If a related task already exists, update it instead of creating a duplicate.

### Context Is in the Active Tasks Block
Every conversation includes an `ACTIVE TASKS:` block in your context. When you see active tasks listed there:
1. Check if the user's current request relates to any active task
2. If yes, read the task's `progress.md` via `read_task_vfs` for full context before acting
3. After acting, update the task with notes about what you did

### Progressive Disclosure
- Start with `progress.md` for a quick summary of where things stand
- Read `log.md` for chronological history if you need details
- Read `context.json` for structured metadata (IDs, relationships)

### Status Transitions
- `active` → work is ongoing, you're taking actions
- `waiting` → you did something and are waiting for a response (e.g. sent email, waiting for reply)
- `stalled` → no progress has been made and something is blocking

## Workflow

### Step 1: Assess the Request
Determine if this request needs persistent tracking:
- Will it take multiple conversations to resolve?
- Does it involve waiting for external responses?
- Does the user need GAIA to follow up proactively?

### Step 2: Check Existing Tasks
```
list_gaia_tasks → check if related task exists
```
If a task exists, skip to Step 4 (update it). If not, continue.

### Step 3: Create the Task
```
create_gaia_task(
  title="Short descriptive title",
  description="What needs to happen and what the expected outcome is",
  expires_in_days=30  # or None for permanent
)
```
The task automatically gets a VFS directory with `progress.md`, `log.md`, and `context.json`.

### Step 4: Take Action and Update
After every significant action related to a task:
```
update_gaia_task(
  task_id="...",
  notes="Sent follow-up email to Rahul about the contract deadline",
  status="waiting"  # if now waiting for response
)
```

### Step 5: Complete When Done
When the goal is achieved:
```
complete_gaia_task(
  task_id="...",
  summary="Contract signed by all parties. Filed in Google Drive."
)
```

## Important Rules

1. **Always check active tasks** when starting a conversation — the ACTIVE TASKS block tells you what's in flight.
2. **Never create duplicate tasks** — check `list_gaia_tasks` first.
3. **Log every action** — use `update_gaia_task` with notes after taking any task-related action, even small ones.
4. **Set status to waiting** after actions that expect external responses.
5. **Read progress.md first** when resuming work on a task from a previous conversation.
6. **Don't over-create tasks** — quick one-off requests don't need tracking.

## Anti-Patterns

- Creating a task for "send an email" when there's no expected follow-up
- Creating multiple tasks for related sub-steps (one task can track the whole initiative)
- Forgetting to update task status after taking action
- Not reading existing task context before acting on a returning topic

## Workflow Ownership

When creating a workflow as part of a multi-step task:

1. Create the task first (or identify the existing task)
2. Create the workflow via `create_workflow`
3. Link it: `link_workflow_to_task(task_id=..., workflow_id=..., workflow_title=...)`

The task will be automatically updated when the workflow completes or fails:
- **Success**: Task log and progress.md updated with execution summary
- **Failure**: Task log updated with error; if task was "waiting", status changes to "stalled"
