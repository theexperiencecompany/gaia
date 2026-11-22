---
name: gaia-task-tracking
description: "Complete guide for GAIA's own tasks: when to take work on, the notes it keeps, next checks and repeats, app-event subscriptions, subtasks, email threads, and learning from past tasks."
target: executor
---

# GAIA Tasks

## Philosophy

A task is one item on the user's tasks page. `assignee="user"` is a to-do the user does; GAIA only nudges them. `assignee="gaia"` is work GAIA owns past this turn: it keeps notes on it and runs it on its next check, its repeat and the app events it listens for, so later conversations can find and build on the work.

When the user says "email Rahul about the contract" and months later asks "what happened with Rahul's contract?", the task and its notes surface the answer.

**One task per initiative.** "Email Rahul, create a Linear issue, follow up Friday" = ONE GAIA task ("Contract negotiation with Rahul") whose notes hold the email thread id, the Linear issue URL, and the follow-up date.

**One task per email thread.** A task about one email thread is created with `gmail_thread_id` (and `gmail_account` when the user has several); it then runs on new mail and on the user's own replies there. A thread has at most one open task: creating another names the open one back instead of creating anything, so update that one. When the thread's task was completed, creating one reopens it with its notes and log; bring its Current State up to date.

## Notes, observations, log

Every GAIA task carries three texts; `get_task` shows all of them:

- **notes**: the recall doc. Standing rules, Done when, Evidence, Key Details, Current State, Context, Learnings, one section each (add your own sections if needed). Write them with `update_task(task_id=..., notes=...)`, passing the whole new notes: read them with `get_task`, change the section that changed, send the result. Never append a log to them; notes that repeat a section or carry dated log entries are refused.
- **observations**: the evidence behind patterns a task learns over time, when it keeps one (the Inbox desk does). Written the same way with `update_task(observations=...)`.
- **log**: written by GAIA itself, oldest first: runs and their outcome, schedule and delivery changes, subscriptions, app events, failures, completion. You never write it. What matters now goes in Current State.

## Tools

Always available to the executor. No `retrieve_tools` needed:

- `create_task`, `update_task`, `complete_task` (with a summary; `stop_repeat` ends a repeating task), `reopen_task`
- `search_tasks`: by meaning, over titles, details and GAIA's notes, finished tasks included
- `list_tasks`: a view (`open`, `today`, `upcoming`, `overdue`, `done`), narrowed by exact words (`query`), `assignee` or `parent_id`
- `get_task`: one task in full
- `edit_checklist`: add, rename, tick, untick or remove one checklist item
- `list_event_fields`, `subscribe_task`, `unsubscribe_task`: app events
- `complete_tasks`, `delete_tasks`: several of the user's to-dos at once; delete only when the user asks

## Search First, Create Last

Creating a task is the **last step**, not the first. Always search before creating.

```
search_tasks(query="relevant keywords")
```

- Open match → update it; do NOT create. "Related action" = same initiative, person, system, or goal. Always update, even for follow-on steps.
- Finished match, same initiative resuming → act on it again ONLY if the user explicitly asked GAIA to DO something for this initiative again. Never because a search returned a historical match during an unrelated request.
- No match → create, only if real follow-up work remains.

**Do NOT create a GAIA task for:**

- Work that only reads ("what's the weather?", "summarize my emails"): no matter how complex or how often it runs, and saving the summary as a task is not tracking. Judge by what the work does, not what it reports: recurring work that also writes on the user's behalf (an inbox desk that opens a task per email thread and saves reply drafts, then briefs the user) DOES get a task, even though its final message is a summary
- A one-off write that finishes this turn (a sent notification, one changed setting)
- Steps in your current orchestration (use `plan_tasks`)
- Casual conversation or one-off questions
- Anything clearly continuing an existing task: update that one instead

Overusing tasks degrades search quality and clutters the user's list.

## Every open GAIA task has a next step

Code refuses to leave an open GAIA task without one, so nothing is ever forgotten. A task with a `repeat` has it already. Every other open GAIA task carries two answers:

1. **What is it waiting for?** `waiting_on`
2. **When does GAIA look again?** `next_check`, an ISO datetime with the user's offset or a duration from now (`"30m"`, `"4h"`, `"3d"`, `"1w"`)

| `waiting_on` | Use when | `next_check` means |
|---|---|---|
| `time` | nothing outside to wait for; look again then | the next check |
| `event` | a subscription or its email thread will wake it (a reply, a merge, a delivery) | the backup check if the event never comes |
| `user` | you asked the user one specific question | when the question expires |
| `sub_todos` | its subtasks do the work | the backup check; each finished subtask wakes it |
| `unplanned` | captured with no plan yet ("track it", a brain dump) | the date to plan it by |

Size the next check to urgency: hours when urgent, days for normal work, up to two weeks for a loose idea. A wait of months is fine; the task just looks again within that and sets the next check from there.

**Asking the user** (`waiting_on="user"`) needs `question` (what you asked) and `if_no_reply`, decided at the moment you ask, while you know why it matters:

- `ask_again`: it matters, ask once more. One re-ask per task, ever.
- `proceed` with `default_action`: carry out the default ("archive the thread without replying") and tell the user.
- `hold`: nothing can move without the answer. GAIA reminds the user on slow checks; after the last unanswered one it closes the task and tells them.

**A scheduled run spends the check that woke it.** Its brief opens with WHY YOU WOKE. End the run by completing the task or giving it a new `waiting_on` + `next_check`. A run that ends without one is sent back once; after that GAIA parks the task as `unplanned` for tomorrow and records that it had to.

## Done when and Evidence

`done_when` (a list of checkable conditions, as the user means them: "the feature is live for users", not "a PR exists") and `evidence` (where each proof shows up and how a run checks it) start the notes' Done when and Evidence sections. Every run checks one against the other, then ends one of three ways: closed with the proof in Learnings, open with its next step, or one specific question to the user. Pick evidence from what the user actually uses, and name the apps later runs need in `needs_integrations`: nothing is created while one is not connected.

## App events

When the proof will arrive as an app event, subscribe the task to it so it wakes early, and keep the next check as the backup:

```python
list_event_fields(trigger_name="gmail_new_message")  # what the event delivers
subscribe_task(
    task_id="abc",
    trigger_name="gmail_new_message",
    conditions=[{"field": "sender", "operator": "contains", "value": "@acme.com"}],
)
update_task(task_id="abc", waiting_on="event", next_check="3d")
```

Key conditions on what identifies the real thing (a sender domain, an order number, a subject token), not broad words. Per-resource events (github, slack, sheets, notion, linear, asana) need `scope` naming the resource. `action="complete"` closes the task on an event that itself means done; `action="unblock"` clears its `flags` when someone outside answers. Completing a task stops it listening.

## Standing rules: the user's feedback

Where the user's feedback on a task goes is "THE USER'S FEEDBACK ON A TASK" in your system prompt; follow it as written there. A Standing rule is one dated line in the notes:

```markdown
## Standing rules
- 2026-09-28: skip newsletters and marketing mail entirely
```

## Scheduling & Repeats

- `next_check`: when GAIA next looks at a task that does not repeat.
- `repeat`: `daily`, `weekly`, `every_4h`, `every_1h`, or a 5-field cron in the user's own wall-clock time (`0 9 * * 1-5` = weekdays 9am; `0 9,20 * * *` = 9am and 8pm daily: ONE repeat, not two tasks). The backend converts it; never bake offsets in. A repeating task needs no next_check, and one finished run never ends it.
- `due`: deadline, an ISO datetime with the user's offset. Overdue still needs doing.
- `expires_at`: relevance window. An expired task is skipped entirely. Don't set it on open-ended work.
- A failed run is retried on a backoff ladder; a one-off task that keeps failing is marked failed.

### Where a run's result goes

- GAIA reads the run's **final report** and messages the user's chat app (WhatsApp/Telegram/Discord/Slack) only when the run found something they need to know or decide. A routine or no-op run sends nothing.
- So end with a factual report (what you did, what changed, what needs them), and do NOT call `send_notification` to announce it: that sends it twice.
- `notify` (default on; a subtask reports to its parent instead) is the user's setting: change it only when they ask. A silent task reaches the user only via a deliberate `send_notification`.

## Subtasks

A GAIA job made of many pieces of the same kind (the inbox desk and one task per email thread it handles) is one parent with a subtask per piece:

```python
create_task(title="Reply to Sam about the lease", assignee="gaia", gmail_thread_id="18f3a2b", parent_id="desk_id", waiting_on="event", next_check="2d")
update_task(task_id="abc", parent_id="desk_id")   # move an existing task under it
update_task(task_id="desk_id", waiting_on="sub_todos", next_check="3d")
list_tasks(parent_id="desk_id")                   # its open subtasks
```

- A subtask obeys its parent's Standing rules on top of its own, so a rule the user gives the parent reaches every piece.
- It reports to its parent, not to the user, and each parent run sees every open subtask's Current State. Keep that section true after each subtask run; it is the subtask's report.
- Each finished subtask wakes the parent; completing the parent closes its open subtasks.
- One level deep: a subtask cannot have subtasks, and the parent must be an open top-level task.

These are not checklist items: those are lines to tick off inside one task (`edit_checklist`), never work GAIA runs.

## Institutional Memory

### References

Link past tasks this one builds on, at creation or later; every run reads their Learnings:

```python
create_task(title="Plan the Q4 launch", assignee="gaia", references=["q3_launch_id"], waiting_on="time", next_check="1w")
update_task(task_id="abc", references=["old_id_1"])   # replaces the list
```

Use `search_tasks` to find past tasks worth referencing, and `get_task` to read how they went.

### Writing Learnings Before Completion

Before calling `complete_task`, write the notes' `## Learnings`. Future similar tasks will reference them.

**Good:** "Sarah responds in 2-3 days", "approval takes 1 week", "batch the Linear + Notion updates in one pass"
**Bad:** "went well", restating the timeline, obvious observations

## Lifecycle

### Before Acting

1. Check the active tasks in your context: does the request relate to an existing task?
2. If yes: `get_task`, then act, then update its notes.
3. If unclear: `search_tasks(query="...")` to check for duplicates.

### After Acting

- Record ids and outcomes under Key Details, and rewrite Current State (`update_task notes=...`).
- Update properties if needed (`update_task`).

### Completing

1. Write `## Learnings` in the notes.
2. `complete_task(task_id="...", summary="...")`.

Complete on your own as soon as the work is clearly resolved (the fix is live and verified, the PR is merged, the external system shows done, the watched event arrived and is handled, the user confirmed it). Do not wait for the user to report it or ask for closure. A repeating task keeps firing unless the standing work itself is over (`stop_repeat=True`).

Never repeat task, subscription, notification or approval IDs in user-visible text; refer to tasks by title. IDs are wiring for tool calls only.

## Examples

### Long-running: follow-up with expiry

```python
create_task(
    title="Follow up with Rahul re: contract",
    assignee="gaia",
    body="Sent the first email. Follow up if no reply.",
    gmail_thread_id="18f3a2b",
    waiting_on="event",
    next_check="3d",
    expires_at="2026-04-08T00:00:00Z",
    done_when=["Rahul has answered on the Q2 contract"],
    evidence="a reply from rahul@example.com on the thread",
    notes="## Key Details\n- Email: rahul@example.com\n- Contract: Q2 vendor agreement\n\n## Current State\nFirst email sent 2026-03-25. Waiting for a reply.",
)
```

### Captured, no plan yet

```python
create_task(title="Rework the inbox desk instructions", assignee="gaia", waiting_on="unplanned", next_check="3d")
```

### Recurring: work that writes, then reports

```python
create_task(
    title="Inbox desk",
    assignee="gaia",
    body="Each morning: open a thread task per email that needs a reply, save reply drafts, then brief the user.",
    repeat="0 8 * * *",
)
```

A daily summary that only reads (top news, "what's in my inbox") gets no task.

### Update after creation

```python
update_task(task_id="abc123", due="2026-04-15T17:00:00+05:30")
update_task(task_id="abc123", waiting_on="event", next_check="3d")  # a subscription wakes it; backup in 3 days
update_task(
    task_id="abc123",
    waiting_on="user",
    question="Should I just ignore Raj's email?",
    if_no_reply="proceed",
    default_action="archive the thread without replying",
    next_check="2d",
)
update_task(task_id="abc123", flags=["waiting_for_reply"])
complete_task(task_id="abc123", summary="...", stop_repeat=True)  # the user stopped a repeating task
```

## Anti-Patterns

- **Not creating** a GAIA task when GAIA touched an external system and something is still open
- **Multiple tasks** for one initiative (one email task + one Linear task + one Notion task → should be one)
- **Vague notes** ("made progress") instead of specific details with ids and tool names
- **A stale Current State** after an action
- **Not searching** before creating: duplicates make future lookups confusing
- **Not writing learnings** before completing: wastes institutional memory
- **Pushing the next check back with nothing changed**: when a check finds no progress, ask the user one question or close the task instead of setting another week
