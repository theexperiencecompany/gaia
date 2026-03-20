---
name: tracked-todo-working-memory
description: Track multi-step work across time and channels using tracked todos with VFS canvas. Create tracked todos for work that expects responses, involves multiple steps, or needs monitoring. Manage todo lifecycle with canvas.md working memory and ChromaDB-indexed context.
target: executor
---

# Tracked Todo Working Memory

## When to Use

**CREATE a tracked todo when:**
- You sent an email and expect a reply (e.g. "email Rahul about the contract")
- The request involves multiple steps across time (e.g. "plan the offsite and book everything")
- Work spans multiple providers (e.g. "create a Linear issue, then update the Notion doc when it's done")
- The user asks you to monitor or follow up on something
- You're coordinating something that won't resolve in this conversation

**DO NOT create a tracked todo when:**
- The action is one-shot with no follow-up (e.g. "what's the weather?")
- The task completes entirely within this conversation
- It's a simple lookup or question

## due_date vs expires_at

These serve different purposes and can both be set:

- **due_date** = **deadline** ("this needs to be done by Friday"). If overdue, the task still needs doing. Use for actionable deadlines.
- **expires_at** = **relevance window** ("this only matters for the next 3 days"). If expired, the task is no longer worth tracking. Use for time-sensitive context.

**Examples:**
- "Book restaurant for anniversary dinner" → `due_date` = anniversary eve. No `expires_at`.
- "Check if Amazon package arrived" → `expires_at` = 3 days from now. No `due_date`.
- "Send cold follow-up if Sarah doesn't reply" → `expires_at` = 14 days (lead gone cold). No `due_date`.
- "File taxes" → `due_date` = April 15, `expires_at` = April 15 (both: deadline AND hard cutoff).

**When NOT to set `expires_at`:** Open-ended tasks with no natural expiry ("research competitors", "improve test coverage"). Only set it when there's a genuine time window after which the task becomes meaningless.

## Strategy

### Search Before Creating
Before creating a new tracked todo, use `search_todo_context` to check if related work already exists. If so, update the existing canvas instead of creating a duplicate.

### Context Is in the Active Tracked Todos Block
Every conversation includes an `ACTIVE TRACKED TODOS:` block in your context. When you see tracked todos listed there:
1. Check if the user's current request relates to any active tracked todo
2. If yes, read the todo's `canvas.md` via `vfs_read` for full context before acting
3. After acting, update `canvas.md` with what you did and the current state

### Canvas.md Is Your Brain
The canvas is YOUR working memory — write to it after every significant action:
- Key details: email addresses, thread IDs, calendar IDs, issue URLs
- Current state: what's true RIGHT NOW
- Timeline: chronological list of actions taken
- Context: accumulated context from signals and decisions

### Log.md Is System-Written
The system appends to `log.md` automatically (creation, completion). Don't write to it directly.

## Workflow

### Step 1: Assess the Request
Determine if this request needs persistent tracking:
- Will it take multiple conversations to resolve?
- Does it involve waiting for external responses?
- Does the user need GAIA to follow up proactively?

### Step 2: Search Existing Context
```
search_todo_context(query="relevant keywords")
```
If a tracked todo exists, read its canvas and update it. If not, continue.

### Step 3: Create the Tracked Todo
```
create_tracked_todo(
  title="Short descriptive title",
  description="What needs to happen and what the expected outcome is",
  initial_canvas="# Title\n\n## Key Details\n- Email: ...\n- Thread ID: ...\n\n## Current State\nWaiting for reply from Rahul.\n\n## Timeline\n- 2026-03-19: Sent initial email"
)
```

### Step 4: Take Action and Update Canvas
After every significant action:
```
update_tracked_todo_canvas(
  todo_id="...",
  canvas_content="...full updated canvas with new state..."
)
```

### Step 4b: Update Tracked Todo Properties

Use `update_tracked_todo` to change properties after creation:

```
update_tracked_todo(todo_id="abc123", labels=["gaia-tracked", "waiting-for-reply"])
update_tracked_todo(todo_id="abc123", scheduled_at="2026-03-25T09:00:00Z")
update_tracked_todo(todo_id="abc123", recurrence="", scheduled_at="")  # Clear scheduling
```

**Available fields:** `labels`, `due_date`, `priority`, `scheduled_at`, `recurrence`.

For canvas content updates, use `update_tracked_todo_canvas` instead.

### Step 5: Complete When Done
When the todo's goal is fully achieved:
```
complete_tracked_todo(
  todo_id="...",
  summary="One or two sentences describing what was achieved"
)
```

### Listing All Tracked Todos

Use `list_tracked_todos` when you need a complete view beyond the ACTIVE TRACKED TODOS context block:

```
list_tracked_todos()
```

Returns all active tracked todos with full metadata: ID, title, labels, priority, due dates, scheduling, recurrence, expiry, retry count, and VFS paths.

### Writing Learnings on Completion

Before calling `complete_tracked_todo`, write a thorough **Learnings** section in the canvas via `update_tracked_todo_canvas`. This is GAIA's institutional memory — future similar tasks will reference these learnings.

Good learnings include:
- What approach worked (and what didn't)
- Timing insights ("Sarah responds in 2-3 days", "approval takes 1 week")
- Key decisions and why they were made
- Shortcuts or optimizations discovered
- Templates or patterns that can be reused

Bad learnings: vague summaries ("went well"), restating the timeline, or obvious observations.

### References to Past Work

When you create a tracked todo, the system automatically searches completed todos for similar past work and attaches them as `references`. You can read these referenced canvases via `vfs_read` to understand past approaches.

You can also manually add references:
```
update_tracked_todo(todo_id="abc", references=["old_todo_id_1", "old_todo_id_2"])
```

## Important Rules

1. **Always check active tracked todos** when starting a conversation — the ACTIVE TRACKED TODOS block tells you what's in flight.
2. **Never create duplicates** — search with `search_todo_context` first.
3. **Update canvas after every action** — your future self depends on it.
4. **Write canvas for your future self** — include IDs, links, and exact state, not vague summaries.
5. **Don't over-create** — quick one-off requests don't need tracking.

## Anti-Patterns

- Creating a tracked todo for "send an email" when there's no expected follow-up
- Creating multiple tracked todos for related sub-steps (one todo can track the whole initiative)
- Forgetting to update canvas.md after taking action
- Not reading existing canvas before acting on a returning topic
- Writing vague canvas entries like "made progress" instead of specific details
