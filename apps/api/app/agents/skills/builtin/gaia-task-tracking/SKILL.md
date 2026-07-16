---
name: tracked-todo-working-memory
description: Workflow guide for GAIA tracked todos: the search-first create flow, two modes (immediate/long-running), the canvas facets, goal lanes, and institutional memory. The create_tracked_todo tool description is the authoritative rulebook.
target: executor
---

# Tracked Todo Working Memory

## Philosophy

Tracked todos are **GAIA-managed todos**: they show on the user's todos page like a normal todo, but GAIA owns them and keeps a canvas of working notes (and an optional schedule) so it can act on them over time. They record what GAIA did, when, how, and why, so future conversations can find and build on past work. When the user says "email Rahul about the contract" and months later asks "what happened with Rahul's contract?", the tracked todo and its canvas surface the answer.

**One todo per initiative.** "Email Rahul, create a Linear issue, follow up Friday" is ONE tracked todo ("Contract negotiation with Rahul") whose canvas holds the email thread ID, Linear issue URL, and follow-up schedule.

The `create_tracked_todo` tool description is the authority on when to create, what never qualifies, the required `serves`, budgets, and every create field. This skill covers the workflow around it.

## Tools

Always available to the executor, no `retrieve_tools` needed:

- `create_tracked_todo`: create the todo and its facet workspace
- `update_tracked_todo`: update labels, due_date, priority, scheduling, references
- `update_tracked_todo_canvas`: write a facet (notes / deliverable / log)
- `complete_tracked_todo`: mark done and archive (requires a completion summary)
- `search_todo_context`: semantic search across all canvases (includes completed)
- `list_tracked_todos`: list active tracked todos with full metadata
- `approve_todo` / `dismiss_todo` / `block_todo` / `answer_todo`: lifecycle transitions

## Search First, Create Last

Creating is the **last step**, not the first. Always `search_todo_context(query="...")` before creating.

- Active match: update its canvas, do NOT create. "Related" means the same initiative, person, system, or goal. Update even for follow-on steps.
- Completed match, same initiative resuming: create new ONLY if the user explicitly asked GAIA to DO something for it again. Never create just because search returned a historical match during an unrelated request.
- No match: create.

Overusing tracked todos degrades search quality and clutters GAIA's memory.

## Two Modes

### Immediate

Completes in this conversation. Create, delegate, document, complete.

```
search_todo_context (nothing found) -> create_tracked_todo
-> handoff to subagent -> collect activity report
-> update_tracked_todo_canvas (append to log facet)
-> complete_tracked_todo
```

### Long-Running

Spans conversations or needs follow-up. Create, act, update, leave open.

```
search_todo_context (nothing found) -> create_tracked_todo(scheduled_at=..., ...)
-> act -> update canvas -> leave open
-> (future conversation) find via active todos or search -> read canvas -> act -> update
-> eventually: complete_tracked_todo with learnings
```

- "Send Rahul the report": search first; if nothing found, immediate.
- "Email Rahul about the meeting": search first; if nothing found, long-running.
- "He replied, send thanks": search finds the existing todo, so update its canvas, no new todo.

## Canvas

A tracked todo's workspace has three facets (pass `facet` to `update_tracked_todo_canvas`):

- **notes**: GAIA's private working memory (plan, key details, current state, learnings). Seeded from `initial_notes`, or the default template below.
- **deliverable**: the polished, send-ready output the user sees. For a proposal it is the EXACT content Approve releases.
- **log**: the chronological activity and timeline audit trail. Activity entries live HERE, not in notes.

Write modes: `append` (default, for log entries and new notes), `section` (replace one named `## Section`, e.g. Current State), `replace` (full rewrite, only when restructuring). `append` and `section` do not require reading the facet first.

### Notes template

```markdown
# {title}

## Key Details
<!-- email addresses, thread IDs, calendar IDs, issue IDs: everything needed to act -->

## Current State
<!-- what's true RIGHT NOW, updated after every action -->

## Context
<!-- accumulated context, related information, decisions made -->

## Learnings
<!-- written on completion: what worked, what didn't, key decisions. Not activity log entries -->
```

### Activity log

After subagents return, append their structured reports to the **log** facet:

```python
update_tracked_todo_canvas(todo_id="...", facet="log", mode="append",
  content="### 2026-03-26\n- **Gmail agent**: Sent email to rahul@example.com re: Q2 contract.\n  Tools: GMAIL_SEND_DRAFT. Thread ID: 18f3a2b.")
```

The log also receives system-written entries (creation, canvas updates, completion) automatically. Append yours; never rewrite or delete the system ones.

## Goal Lanes

A goal is a long-lived lane (`kind="goal"`) whose canvas is the living strategy the nightly pass advances. When the user reveals a durable multi-week objective (raising a round, launching a product, a job search), propose making it a goal in that same reply with ONE specific question ("Want me to track the raise as a goal? I'd start tonight with a target-investor list."). On their yes, create it with `initial_notes` carrying the strategy you heard: the objective, deadline, constraints, and the next 3 concrete steps. Set `goal_id` on every task that advances the goal.

When later chat reveals goal-relevant direction (a channel to drop, a deadline shift, "warm intros not cold emails"), write it into that goal's notes facet in the same turn:

```python
update_tracked_todo_canvas(todo_id="<goal>", facet="notes", mode="section",
  section="Current State", content="Warm intros only, no cold email.")
```

The night shift and the morning brief plan from that text, not from chat history.

## Institutional Memory

- **References**: `update_tracked_todo(todo_id="abc", references=["old_id"])` links related past todos (appended, not replaced). Use `search_todo_context` to find them.
- **Learnings before completion**: before `complete_tracked_todo`, write a thorough `## Learnings` section in notes. Good: "Sarah responds in 2-3 days", "batch the Linear and Notion updates in one handoff". Bad: "went well", restating the timeline.

## Anti-Patterns

- Not creating a tracked todo when GAIA touched external systems (even "just" sending an email).
- Multiple todos for one initiative (one email, one Linear, one Notion, when it should be one).
- Vague canvas ("made progress") instead of specific details with IDs and tool names.
- Not collecting subagent activity reports before writing the canvas.
- Not searching before creating.
- Not writing learnings before completing.
