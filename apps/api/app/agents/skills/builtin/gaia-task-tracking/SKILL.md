---
name: tracked-todo-working-memory
description: Complete guide for GAIA tracked todos — philosophy, two modes (immediate/long-running), canvas activity logging, scheduling/recurrence, and institutional memory.
target: executor
---

# Tracked Todo Working Memory

## Philosophy

Tracked todos are **GAIA's memory** — not the user's todo list. They record what GAIA did, when, how, and why, so future conversations can find and build on past work.

When the user says "email Rahul about the contract" and months later asks "what happened with Rahul's contract?", the tracked todo and its canvas surface the answer.

**One todo per initiative.** "Email Rahul, create a Linear issue, follow up Friday" = ONE tracked todo ("Contract negotiation with Rahul") with a canvas holding the email thread ID, Linear issue URL, and follow-up schedule.

## Tools

Always available to the executor — no `retrieve_tools` needed:

- `create_tracked_todo` — create todo with VFS canvas
- `update_tracked_todo` — update labels, due_date, priority, scheduled_at, recurrence, expires_at, references
- `update_tracked_todo_canvas` — write to canvas.md; modes: append (default), section, replace
- `complete_tracked_todo` — mark done, archive VFS, requires completion summary
- `search_todo_context` — semantic search across all canvas embeddings (ChromaDB); includes completed
- `list_tracked_todos` — list all active tracked todos (up to 50) with full metadata

## Search First, Create Last

Creating a new todo is the **last step**, not the first. Always search before creating.

```
search_todo_context(query="relevant keywords")
```

- Active match → update its canvas; do NOT create. "Related action" = same initiative, person, system, or goal. Always update, even for follow-on steps.
- Completed match, same initiative resuming → create new ONLY if the user explicitly asked GAIA to DO something for this initiative again. Never create just because search returned a historical match during an unrelated request.
- No match → create — only if a write action was performed this turn.

**Create when** GAIA takes an action on an external system (email, calendar, Slack, Linear, Notion, etc.) and nothing relevant already exists in memory.

**Do NOT create for:**

- Pure lookups with no side effects ("what's the weather?", "summarize my emails")
- Steps in your current orchestration (use `plan_tasks`)
- Casual conversation or one-off questions
- Anything clearly continuing an existing tracked todo — update that one instead

Overusing tracked todos degrades search quality and clutters GAIA's memory.

## Two Modes

Once you've confirmed no existing todo covers this (see Search First above):

### Immediate

Completes in this conversation. Create → delegate → document → complete.

```
search_todo_context → (nothing relevant found) → create_tracked_todo
→ handoff to subagent → collect activity report
→ update_tracked_todo_canvas (append activity log)
→ complete_tracked_todo
```

### Long-Running

Spans conversations or needs follow-up. Create → act → update → leave open.

```
search_todo_context → (nothing relevant found) → create_tracked_todo(scheduled_at=..., ...)
→ act → update_tracked_todo_canvas → leave open
→ (future conversation) find via active todos or search → read canvas → act → update
→ eventually: complete_tracked_todo with learnings
```

- "Send Rahul the report" — search first; if nothing found: immediate todo.
- "Email Rahul about the meeting" — search first; if nothing found: long-running todo.
- "He replied, send thanks" — search finds existing todo → update canvas, no new todo.
- "What's the weather?" / "Summarize my emails" — no todo.

## Canvas

### Writing to the Canvas

`update_tracked_todo_canvas` has three modes — **pick the right one**, never default to `replace` out of habit:

- `append` (default) — pass only the new content. Use for activity log entries, timeline events, notes.
- `section` — pass only the new body of that section (no heading). Use for updating one named section (e.g. `Current State`).
- `replace` — pass the entire canvas markdown. Only for full restructure or initial setup.

`append` and `section` do **not require reading the file first** — the tool handles it internally.

```python
# Log what a subagent did — no read needed
update_tracked_todo_canvas(todo_id="...", mode="append", content="\n### 2026-03-26\n- **Gmail agent**: Sent email...")

# Update a single section — no read needed
update_tracked_todo_canvas(todo_id="...", mode="section", section="Current State", content="Waiting for Rahul's reply.")

# Full rewrite — only when restructuring
update_tracked_todo_canvas(todo_id="...", mode="replace", content="# Title\n\n## Key Details\n...")
```

### Structure

Default template (used when `initial_canvas` is omitted):

```markdown
# {title}

## Key Details

<!-- email addresses, thread IDs, calendar IDs, issue URLs — everything needed to act -->

## Current State

<!-- what's true RIGHT NOW — updated after every action -->

## Activity Log

<!-- which agent did what, which tools it used, what the outcome was — add entries HERE, not in Learnings -->

## Timeline

<!-- chronological list of actions with dates -->

## Context

<!-- accumulated context from signals, related information, decisions made -->

## Learnings

<!-- written ONLY at completion time: what worked, what didn't, timing insights, reusable patterns. DO NOT write activity log entries here -->
```

### Activity Log

After subagents return, record their structured reports in the canvas:

```markdown
## Activity Log

### 2026-03-26

- **Gmail agent**: Sent email to rahul@example.com re: Q2 contract renewal.
  Tools: GMAIL_CREATE_DRAFT → GMAIL_SEND_DRAFT. Thread ID: 18f3a2b.
  Subject: "Q2 Contract Renewal — Next Steps". Draft approved and sent.
- **Linear agent**: Created issue LIN-423 "Track Q2 contract renewal".
  Tools: LINEAR_CREATE_ISSUE. URL: https://linear.app/team/LIN-423.
```

### System Log

`log.md` is auto-written by the system (creation, canvas updates, completion). Don't write to it directly.

## Create Fields

- `title` (required) — short descriptive title
- `description` — what needs to happen and expected outcome
- `initial_canvas` — markdown content; default template if omitted
- `labels` — list of strings; `gaia-tracked` added automatically
- `priority` — `high` | `medium` | `low` | `none` (default `none`)
- `scheduled_at` — ISO datetime when GAIA should auto-execute (must be future). Omit for cron recurrence — first fire is computed from the cron.
- `recurrence` — repeat pattern. Cron-style works alone (no `scheduled_at` needed); shortcut values still need `scheduled_at` as anchor.
- `expires_at` — ISO datetime when todo becomes irrelevant (skipped if expired)

`due_date` is only settable via `update_tracked_todo`, not at creation time.

## Scheduling & Recurrence

### `scheduled_at`

ISO datetime, must be in the future. GAIA auto-executes via background worker at that time.

### `recurrence`

ALWAYS evaluated in the user's stored timezone — pass cron in user-local wall-clock terms, the backend converts to UTC. Do NOT bake offsets into the cron string. After successful execution, `scheduled_at` auto-advances and a new job is enqueued.

- `daily` — +1 day (shortcut, needs `scheduled_at` as anchor)
- `weekly` — +7 days (shortcut, needs `scheduled_at`)
- `every_4h` — +4 hours (shortcut, needs `scheduled_at`)
- `every_1h` — +1 hour (shortcut, needs `scheduled_at`)
- Cron — `0 9 * * 1-5` = weekdays 9am user-local; `0 9,20 * * *` = 9am and 8pm daily. ONE recurrence, not two todos. No `scheduled_at` needed — first fire is computed from the cron.

### `due_date` vs `expires_at`

- **`due_date`** = deadline. Overdue tasks still need doing. Set via `update_tracked_todo`.
- **`expires_at`** = relevance window. Expired tasks are skipped entirely.
- Both can be set together (e.g., "file taxes": due April 15, expires April 15).
- Don't set `expires_at` on open-ended tasks with no natural expiry.

### Validation

- `scheduled_at` must be future
- Shortcut `recurrence` (`daily`, `weekly`, `every_4h`, `every_1h`) requires `scheduled_at` as anchor. Cron does not.
- Cannot clear `scheduled_at` while a shortcut `recurrence` is set
- Cron expressions validated via croniter
- If both `scheduled_at` and a cron `recurrence` are passed, `scheduled_at` is ignored (first fire comes from the cron)

### Execution & Retry

- Background worker (ARQ) runs at `scheduled_at`
- Redis lock prevents concurrent execution of same todo
- Failure: retries up to 3× with backoff (1 hour, then 4 hours)
- After 3 failures: `failed` label added, user notified
- Success with recurrence: `scheduled_at` advances, new job enqueued

## Institutional Memory

### References

Manually link related past todos:

```
update_tracked_todo(todo_id="abc", references=["old_todo_id_1"])
```

References are appended (not replaced). Use `search_todo_context` to find past todos worth referencing, then read their canvases via `vfs_read` to understand past approaches.

### Writing Learnings Before Completion

Before calling `complete_tracked_todo`, update the canvas with a thorough `## Learnings` section. Future similar tasks will reference these.

**Good:** "Sarah responds in 2-3 days", "approval takes 1 week", "batch the Linear + Notion updates in one handoff"
**Bad:** "went well", restating the timeline, obvious observations

## Lifecycle

### Before Acting

1. Check the `ACTIVE TRACKED TODOS:` block in your context — does the request relate to an existing todo?
2. If yes: `vfs_read` its canvas.md, then act, then update canvas
3. If unclear: `search_todo_context(query="...")` to check for duplicates

### After Acting

- Update canvas with activity log from subagent reports
- Update properties if needed (`update_tracked_todo`)

### Completing

1. Write `## Learnings` in canvas
2. `complete_tracked_todo(todo_id="...", summary="...")` — archives VFS, marks completed in DB + ChromaDB

## Examples

### Immediate: send an email

```python
create_tracked_todo(
  title="Sent Q2 report to Sarah",
  initial_canvas="# Sent Q2 report to Sarah\n\n## Key Details\n- Recipient: sarah@example.com\n\n## Activity Log\n\n## Learnings\n"
)
# handoff to Gmail → collect report → update canvas → complete
```

### Long-running: follow-up with expiry

```python
create_tracked_todo(
  title="Follow up with Rahul re: contract",
  description="Sent initial email. Follow up if no reply.",
  scheduled_at="2026-04-01T09:00:00Z",
  expires_at="2026-04-08T00:00:00Z",
  initial_canvas="# Rahul Contract Follow-up\n\n## Key Details\n- Email: rahul@example.com\n- Thread ID: 18f3a2b\n- Contract: Q2 vendor agreement\n\n## Current State\nInitial email sent. Waiting for reply.\n\n## Activity Log\n### 2026-03-25\n- **Gmail agent**: Sent email re: Q2 contract. Tools: GMAIL_CREATE_DRAFT → GMAIL_SEND_DRAFT. Thread ID: 18f3a2b.\n\n## Learnings\n"
)
```

### Recurring: daily check

```python
create_tracked_todo(
  title="Daily HN top posts summary",
  scheduled_at="2026-03-26T08:00:00Z",
  recurrence="daily"
)
```

### Recurring: weekday cron

```python
create_tracked_todo(
  title="Weekday standup prep",
  scheduled_at="2026-03-26T09:00:00Z",
  recurrence="0 9 * * 1-5"
)
```

### Update after creation

```python
update_tracked_todo(todo_id="abc123", due_date="2026-04-15")
update_tracked_todo(todo_id="abc123", scheduled_at="2026-03-30T10:00:00Z")
update_tracked_todo(todo_id="abc123", scheduled_at="", recurrence="")  # Clear scheduling
update_tracked_todo(todo_id="abc123", labels=["gaia-tracked", "waiting-for-reply"])
```

## Anti-Patterns

- **Not creating** a tracked todo when GAIA touched external systems (even "just" sending an email)
- **Multiple todos** for one initiative (one email todo + one Linear todo + one Notion todo → should be one)
- **Vague canvas** ("made progress") instead of specific details with IDs and tool names
- **Not collecting** activity reports from subagents before writing the canvas
- **Not searching** before creating — duplicates make future lookups confusing
- **Not writing learnings** before completing — wastes institutional memory
