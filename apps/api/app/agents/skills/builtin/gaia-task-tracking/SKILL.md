---
name: tracked-todo-working-memory
description: Complete guide for GAIA tracked todos — philosophy, two modes (immediate/long-running), canvas activity logging, scheduling/recurrence, and institutional memory.
target: executor
---

# Tracked Todo Working Memory

## Philosophy

Tracked todos are **GAIA-managed todos**: they show on the user's todos page like a normal todo, but GAIA owns them and keeps a canvas of working notes (and an optional schedule) so it can act on them over time. They are distinct from the user's own hand-created action items. They record what GAIA did, when, how, and why, so future conversations can find and build on past work.

When the user says "email Rahul about the contract" and months later asks "what happened with Rahul's contract?", the tracked todo and its canvas surface the answer.

**One todo per initiative.** "Email Rahul, create a Linear issue, follow up Friday" = ONE tracked todo ("Contract negotiation with Rahul") with a canvas holding the email thread ID, Linear issue URL, and follow-up schedule.

## Tools

Always available to the executor — no `retrieve_tools` needed:

- `create_tracked_todo` — create todo with its facet workspace (notes / deliverable / log)
- `update_tracked_todo` — update labels, due_date, priority, scheduled_at, recurrence, expires_at, references
- `update_tracked_todo_canvas` — write a facet (notes / deliverable / log); modes: append (default), section, replace
- `complete_tracked_todo` — mark done, archive, requires completion summary
- `search_todo_context` — semantic search across all canvas embeddings (ChromaDB); includes completed
- `list_tracked_todos` — list all active tracked todos (up to 50) with full metadata
- `approve_todo` — release a proposed todo for execution, ONLY on the user's explicit go-ahead; when their go-ahead carries a qualification ("only the Sequoia one"), pass their verbatim words as `instruction`
- `dismiss_todo` — decline a proposed todo on the user's explicit say-so; records the rejection signal
- `block_todo` — pause a run on a decision only the user can make; asks one clear question
- `answer_todo` — resume a blocked (needs_you) todo with the user's answer

## Search First, Create Last

Creating a new todo is the **last step**, not the first. Always search before creating.

```
search_todo_context(query="relevant keywords")
```

- Active match → update its canvas; do NOT create. "Related action" = same initiative, person, system, or goal. Always update, even for follow-on steps.
- Completed match, same initiative resuming → create new ONLY if the user explicitly asked GAIA to DO something for this initiative again. Never create just because search returned a historical match during an unrelated request.
- No match → create — only if GAIA performed or scheduled a real write/action this turn.

**Create when** GAIA performs or schedules an action on an external system (email, calendar, Slack, Linear, Notion, etc.) that it needs to remember, follow up on, or repeat — and nothing relevant already exists in memory.

**Do NOT create for:**

- Pure reads with no side effects ("what's the weather?", "summarize my emails") — no matter how complex or how often they run; a recurring daily summary is still a read, and saving the summary as a todo is not tracking
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

A tracked todo's workspace has three facets (pass `facet` to `update_tracked_todo_canvas`):

- **notes** — GAIA's private working memory: plan, key details, current state. Seeded from `initial_notes`, or this default template:

```markdown
# {title}

## Key Details

<!-- email addresses, thread IDs, calendar IDs, issue IDs — everything needed to take action -->

## Current State

<!-- what's true RIGHT NOW — updated after every action -->

## Context

<!-- accumulated context from signals, related information, decisions made -->

## Learnings

<!-- written on completion: what worked, what didn't, key decisions, timing insights. DO NOT write activity log entries here -->
```

- **deliverable** — the polished, send-ready output the user sees. For a proposal (`requires_approval=True`) this is the EXACT content Approve releases, seeded from the required `initial_deliverable`. Internal todos start from a light template.
- **log** — the activity/timeline audit trail. Chronological activity (Activity Log, Timeline) lives HERE, not in notes.

### Activity Log

After subagents return, record their structured reports in the **log** facet:

```python
update_tracked_todo_canvas(todo_id="...", facet="log", mode="append", content="### 2026-03-26\n- **Gmail agent**: Sent email...")
```

```markdown
### 2026-03-26

- **Gmail agent**: Sent email to rahul@example.com re: Q2 contract renewal.
  Tools: GMAIL_CREATE_DRAFT → GMAIL_SEND_DRAFT. Thread ID: 18f3a2b.
  Subject: "Q2 Contract Renewal — Next Steps". Draft approved and sent.
- **Linear agent**: Created issue LIN-423 "Track Q2 contract renewal".
  Tools: LINEAR_CREATE_ISSUE. URL: https://linear.app/team/LIN-423.
```

### System Log

The log facet also receives system-written entries automatically (creation, canvas updates, completion). Append your activity entries; never rewrite or delete the system ones.

## Create Fields

- `title` (required) — short descriptive title
- `serves` (required) — the goal, memory item, or explicit user request this todo advances; creation is rejected when empty
- `requires_approval` (required) — the approval rule. `True` for outward-visible work (sending email/DMs, posting, inviting others, spending money): enters `proposed` and waits for the user's Approve tap, and MUST carry its finished `initial_deliverable`. `False` for work only the user and GAIA can see (research, drafts, triage, prep): enters `queued` and runs immediately
- `description` — what needs to happen and expected outcome
- `initial_deliverable` — deliverable facet: the polished, send-ready output. REQUIRED for proposals (it is what Approve releases); optional otherwise
- `initial_notes` — notes facet: initial working memory; default template if omitted
- `labels` — list of strings
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

References are appended (not replaced). Use `search_todo_context` to find past todos worth referencing — its snippets surface the past approaches.

### Writing Learnings Before Completion

Before calling `complete_tracked_todo`, update the canvas with a thorough `## Learnings` section. Future similar tasks will reference these.

**Good:** "Sarah responds in 2-3 days", "approval takes 1 week", "batch the Linear + Notion updates in one handoff"
**Bad:** "went well", restating the timeline, obvious observations

## Lifecycle

### Before Acting

1. Check the `ACTIVE TRACKED TODOS:` block in your context — does the request relate to an existing todo?
2. If yes: pull its context (key details from the context block or `search_todo_context`), then act, then update its facets
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
  serves="User asked to send Sarah the Q2 report",
  requires_approval=False,
  initial_notes="# Sent Q2 report to Sarah\n\n## Key Details\n- Recipient: sarah@example.com\n\n## Current State\nReport sent in this conversation.\n\n## Learnings\n"
)
# handoff to Gmail → collect report → update canvas → complete
```

### Long-running: follow-up with expiry

```python
create_tracked_todo(
  title="Follow up with Rahul re: contract",
  serves="User asked GAIA to chase the Q2 vendor contract with Rahul",
  requires_approval=True,
  description="Sent initial email. Follow up if no reply.",
  scheduled_at="2026-04-01T09:00:00Z",
  expires_at="2026-04-08T00:00:00Z",
  initial_deliverable="# Follow-up email to Rahul\n\nHi Rahul, just checking in on the Q2 vendor agreement I sent last week. Any questions I can answer?",
  initial_notes="# Rahul Contract Follow-up\n\n## Key Details\n- Email: rahul@example.com\n- Thread ID: 18f3a2b\n- Contract: Q2 vendor agreement\n\n## Current State\nInitial email sent. Waiting for reply.\n\n## Learnings\n"
)
```

### Recurring: daily check

```python
create_tracked_todo(
  title="Daily HN top posts summary",
  serves="User asked for a daily HN top posts summary",
  requires_approval=False,
  scheduled_at="2026-03-26T08:00:00Z",
  recurrence="daily"
)
```

### Recurring: weekday cron

```python
create_tracked_todo(
  title="Weekday standup prep",
  serves="User asked GAIA to prep their standup every weekday",
  requires_approval=False,
  scheduled_at="2026-03-26T09:00:00Z",
  recurrence="0 9 * * 1-5"
)
```

### Update after creation

```python
update_tracked_todo(todo_id="abc123", due_date="2026-04-15")
update_tracked_todo(todo_id="abc123", scheduled_at="2026-03-30T10:00:00Z")
update_tracked_todo(todo_id="abc123", scheduled_at="", recurrence="")  # Clear scheduling
update_tracked_todo(todo_id="abc123", labels=["waiting-for-reply"])
```

## Anti-Patterns

- **Not creating** a tracked todo when GAIA touched external systems (even "just" sending an email)
- **Multiple todos** for one initiative (one email todo + one Linear todo + one Notion todo → should be one)
- **Vague canvas** ("made progress") instead of specific details with IDs and tool names
- **Not collecting** activity reports from subagents before writing the canvas
- **Not searching** before creating — duplicates make future lookups confusing
- **Not writing learnings** before completing — wastes institutional memory
