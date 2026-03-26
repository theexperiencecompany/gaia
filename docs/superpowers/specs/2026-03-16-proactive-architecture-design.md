# Proactive Architecture — Design Spec

> Status: Design Approved
> Date: 2026-03-16
> Branch: proactive-crons

---

## Problem

GAIA today is passive. It activates when triggered — user message, webhook, cron — then goes dark. Between triggers it has no initiative. More critically, when GAIA takes actions (sends an email, creates a PR, submits a contract), it immediately forgets what it expected to happen next. There is no tracking of open loops. The result: GAIA cannot follow up on its own work, cannot connect a reply to the action that caused it, and cannot escalate when expected outcomes don't arrive.

Two things fix this:

1. **GaiaTask** — a persistent, VFS-backed execution entity that tracks multi-step work across sessions, owns the workflows that serve it, and monitors the outcomes it expects
2. **Proactive Loop** — a two-mode strategy layer that surveys everything GAIA knows about a user's life, detects what needs attention, and acts — without being asked

---

## Core Mental Model Shift

The current design is **observational**: GAIA surveys the world and notices things.

The new design is **intentional**: GAIA tracks what it put in motion and monitors whether those intentions resolved.

> "Rahul hasn't replied in 3 days" is only knowable if GAIA registered — at the moment it sent the email — that it expected a reply. Without intent tracking, the proactive loop can only read inbox noise.

**Every significant action GAIA takes creates an open loop. The system's job is to track, monitor, and resolve those open loops.**

---

## Three-Layer Architecture

```
┌─────────────────────────────────────────────────────┐
│              STRATEGY LAYER                         │
│              Proactive Loop                         │
│  Surveys everything. Spots patterns. Creates tasks. │
│  Escalates stalled work. Self-schedules next run.   │
└──────────────────┬──────────────────────────────────┘
                   │ creates / escalates / reads
                   ▼
┌─────────────────────────────────────────────────────┐
│              EXECUTION LAYER                        │
│              GaiaTasks                              │
│  Does the work. Owns workflows. Writes to VFS.      │
│  Tracks open loops. Acts on triggers.               │
│  Self-schedules for specific events.                │
└──────────────────┬──────────────────────────────────┘
                   │ owns / creates / runs
                   ▼
┌─────────────────────────────────────────────────────┐
│              AUTOMATION LAYER                       │
│              Workflows                              │
│  Single-purpose, scheduled/event-driven routines.  │
│  Inbox triage, meeting prep, reply drafting, etc.   │
└─────────────────────────────────────────────────────┘
```

Each layer only knows about the one below it. The user sees none of this — they receive notifications only when something requires their attention or has been resolved.

---

## Part 1: GaiaTask — The Execution Layer

### What It Is

A persistent, stateful agent entity. Not user-facing. GAIA auto-creates a GaiaTask when it judges that a user request requires multi-step work that will unfold across time or channels.

**Scope is flexible:**
- Small: "Schedule meeting with Rahul" — a few back-and-forth emails, no sub-workflows needed
- Large: "Manage my inbox" — long-running, owns multiple workflows, accumulates weeks of logs

The same structure handles both.

### When GAIA Creates a GaiaTask

GAIA (not the user) judges whether a task is needed. Rule of thumb:

- **Creates a task**: any action that expects a response, involves multiple steps, or needs to be monitored over time
- **Does not create a task**: one-shot actions with no expected follow-up (add calendar event, web search, answer a question)

The executor agent has a `create_gaia_task()` tool. It calls it when it judges the action warrants tracking.

### The VFS — Living Memory

Each task owns a directory in the VFS:

```
/users/{user_id}/tasks/{task_id}/
├── progress.md       ← what's been done, what's next (read first on every wakeup)
├── log.md            ← append-only chronological history of every action and event
├── context.json      ← structured state: status, workflow IDs, conversation ID
├── inbox/            ← incoming signals: email replies, slack messages, webhook data
└── workflows/        ← outputs from sub-workflows that ran for this task
    └── archive/      ← compacted older workflow outputs (see VFS Growth below)
```

This is not a DB record — it's the task's working memory. When the task wakes up (triggered by an email reply, a cron, or the proactive loop), the agent reads `progress.md` first (summary), then drills into `context.json` and `log.md` as needed. Progressive disclosure: the agent doesn't load the full history every time, only what it needs.

The VFS directory persists after task completion — it becomes permanent memory of what was done. Not deleted, just archived.

**VFS Growth and Compaction:**

For long-running tasks (e.g., "Manage inbox" with triage running every 15 min), unbounded file accumulation is a real operational concern. Two mitigations:

1. **Workflow output rotation**: `workflows/` keeps the last 7 days of files inline. Older outputs are moved to `workflows/archive/` and replaced with a single `archive_summary_{week}.md`. The agent reads the inline files by default; the archive is available on demand via `read_task_vfs()`.

2. **log.md compaction**: When `log.md` exceeds 500 lines, the oldest 80% is summarized into a `log_summary_{date}.md` and the main `log.md` is reset to the summary header + the most recent 20%. The full history is not lost — the summaries remain in the VFS — but the agent's default read stays bounded.

### Open Loop Tracking — The Core Innovation

Every significant action creates an expectation. Open loops are stored as a **separate MongoDB collection** (`open_loops`), not embedded in `context.json`. This enables efficient indexed queries across all users without full collection scans — the maintenance scan does `{ resolved: false, deadline: { $lt: now } }` on a single indexed collection rather than unwinding nested arrays across `gaia_tasks`.

`context.json` holds only a reference list of active loop IDs for context injection:

```json
{
  "task_id": "task_abc",
  "title": "Schedule meeting with Rahul",
  "status": "waiting",
  "created_at": "2026-03-13T10:00:00Z",
  "active_loop_ids": ["loop_1"],
  "owned_workflow_ids": [],
  "primary_conversation_id": "conv_123"
}
```

**Open Loop schema by channel:**

```json
// Email
{
  "id": "loop_1",
  "task_id": "task_abc",
  "user_id": "user_xyz",
  "description": "Reply from rahul@company.com re: meeting availability",
  "channel": "email",
  "watch": {
    "sender": "rahul@company.com",
    "thread_id": "gmail_thread_xyz"
  },
  "deadline": "2026-03-16T10:00:00Z",
  "if_unresolved": "draft_followup_email",
  "resolved": false,
  "resolved_at": null,
  "resolved_by": null
}

// Slack
{
  "channel": "slack",
  "watch": {
    "slack_user_id": "U012AB3CD",
    "channel_id": "D987ZY654",   // DM channel ID
    "after_ts": "1710000000.000" // only messages after this timestamp
  }
}

// GitHub
{
  "channel": "github",
  "watch": {
    "event_type": "pull_request_review",   // or "pull_request_merged", "issue_closed"
    "repo": "org/repo",
    "resource_id": "pr_412"               // PR number or issue number
  }
}

// Calendar
{
  "channel": "calendar",
  "watch": {
    "event_type": "invite_accepted",      // or "event_started", "event_updated"
    "event_id": "cal_event_abc",
    "attendee_email": "priya@company.com" // optional: specific attendee
  }
}

// Linear
{
  "channel": "linear",
  "watch": {
    "event_type": "issue_status_changed",
    "issue_id": "LIN-412",
    "target_status": "Done"              // optional: only resolve on specific status
  }
}

// Generic webhook
{
  "channel": "webhook",
  "watch": {
    "source": "composio",               // which integration
    "trigger_name": "contract_signed",  // Composio trigger name
    "match_fields": {                   // key-value pairs that must match in payload
      "document_id": "doc_abc123"
    }
  }
}
```

Each channel's trigger handler implements `find_matching_open_loops(channel, event_data) -> List[OpenLoop]`. The matching logic per channel:
- **email**: match `sender` AND (`thread_id` if present OR any email in thread)
- **slack**: match `slack_user_id` AND `channel_id` AND `ts > after_ts`
- **github**: match `event_type` AND `resource_id`
- **calendar**: match `event_id` AND `event_type` AND optionally `attendee_email`
- **linear**: match `issue_id` AND `event_type` AND optionally `target_status`
- **webhook**: match `source` AND `trigger_name` AND all `match_fields`

**Multi-task conflict resolution:** When multiple active open loops match the same incoming signal (e.g., two tasks both watching for email from `rahul@company.com`):

1. All matching loops are resolved simultaneously — the signal is not consumed by one task only
2. The incoming signal is stored in each matching task's `inbox/` folder
3. Each matched task wakes up independently with the signal in its context
4. Tasks do not know about each other — each acts on the signal from its own perspective
5. If this causes duplicate actions (e.g., both tasks try to reply), the dedup layer in the notification orchestrator prevents double-sending

**Automatic open loop detection:** When GAIA's executor takes an action, it classifies the action type:

| Action | Auto-registered expectation | Default deadline |
|---|---|---|
| Send email | Reply from recipient | 3 days |
| Create calendar invite | Acceptance from invitees | 24 hours |
| Send contract / document | Signed return or acknowledgment | 7 days |
| Open GitHub PR | Review from team | 2 days |
| Send Slack DM | Response from recipient | 4 hours |
| Create todo for user | Completion or acknowledgment | 2 days |

GAIA registers these automatically — not because you asked it to track something, but because it knows what kind of action it just took.

### Workflow Ownership

GaiaTask sits above Workflows. A task can:

- **Adopt** an existing system workflow ("Manage inbox" adopts the inbox triage workflow)
- **Create** new workflows for its specific needs
- **Enable / disable** workflows based on task state
- **Trigger** a workflow immediately outside its normal schedule

Workflow outputs flow into the task's `workflows/` VFS folder. The task agent reads these when it wakes up — it knows what its sub-workflows have done.

### Lifecycle

```
1. CREATION
   Agent calls create_gaia_task(title, description, expires_in_days=N)
   → gaia_tasks record created
   → VFS directory created at /users/{uid}/tasks/{task_id}/
   → progress.md, log.md, context.json initialized
   → Workflows adopted or created if needed
   → open loops registered in open_loops collection

2. ACTIVE (waiting / acting)
   Incoming signal (email reply, cron, proactive loop escalation)
   → Task conversation thread resumes (LangGraph checkpointer)
   → Agent reads progress.md → context.json → acts
   → Appends to log.md, updates progress.md and context.json
   → Notifies user only if significant
   → Calls schedule_next_wakeup() or registers conditional wakeup

3. COMPLETION
   Agent calls complete_task()
   → All owned workflows disabled
   → All active open loops closed (resolved=true, resolved_by="task_completed")
   → VFS directory renamed to /users/{uid}/tasks/archive/{task_id}/
   → gaia_tasks record status → "completed"
   → User notified of resolution
   → Primary conversation thread resumed with outcome if still valid
     (fallback: if conversation not found in checkpointer, send notification instead)

4. CANCELLATION
   User says "stop tracking X" or "forget about the meeting with Rahul"
   → Executor calls cancel_task(task_id)
   → All owned workflows disabled
   → All active open loops closed (resolved_by="cancelled")
   → VFS archived (not deleted)
   → gaia_tasks status → "cancelled"
   → No notification sent (user initiated this)

5. EXPIRATION
   expires_at TTL reached (checked by maintenance scan)
   → If task still has unresolved open loops:
     → Set gaia_tasks.status → "escalating" (prevents re-escalation on next scan cycle)
     → Enqueue synthesis run: "Task expired with unresolved loops — decide: extend, notify, cancel"
     → Loop decides: extend deadline, notify user, or auto-cancel
     → On loop completion: status transitions out of "escalating"
   → If no unresolved open loops (task is just stale):
     → Auto-cancel with log entry
     → User notified: "Task 'X' expired after N days with no activity"
   → VFS archived

6. ESCALATION (from proactive loop)
   Loop detects stalled task or expired open loop deadline
   → Injects escalation context into task's next wakeup
   → Task agent decides: draft follow-up, notify user, extend deadline, or cancel
```

**Agent tools (Phase 0):**
- `create_gaia_task(title, description, expires_in_days)` — creates task + VFS
- `update_gaia_task(task_id, status, notes)` — updates state, appends to log
- `complete_task(task_id, summary)` — marks done, archives VFS
- `cancel_task(task_id, reason)` — cancels task, archives VFS
- `list_active_tasks()` — returns lightweight list for context injection
- `read_task_vfs(task_id, path)` — progressive disclosure drill-in

### Self-Scheduling

A task can schedule its own wakeup in two ways:

- **Time-based**: "wake me in 3 days" → ARQ job scheduled
- **Conditional**: "wake me when I receive email from rahul@company.com" → registered in open_loops, resolved when the watch condition fires

Both co-exist. A task can say: "wake me in 3 days if Rahul hasn't replied, but also wake me immediately if he does reply."

---

## Part 2: Open Loop System — The Infrastructure of Intent

### What It Does

The open loop system is the bridge between GaiaTask and incoming signals. It answers one question continuously: **did the things we expected to happen, happen?**

Maintenance mode of the proactive loop handles deadline scanning — no LLM required. Channel trigger handlers handle real-time resolution.

### Resolution Flow

```
Incoming Gmail event
  → GmailTriggerHandler fires
  → find_workflows() runs (existing behavior)
  → find_matching_open_loops("email", event_data) runs in parallel   ← new
       → queries open_loops: {channel:"email", resolved:false, user_id:uid}
       → matches sender + thread_id (or sender alone if no thread_id)
       → if matches found:
           → mark each loop resolved
           → store email in each matched task's inbox/
           → wake each matched task's conversation thread with context

Maintenance scan (every 30 min)
  → queries: { resolved: false, deadline: { $lt: now } }
  → for each expired loop:
       → check if_unresolved action
       → deterministic (no LLM): draft_followup_email, send_reminder, cancel_task, notify_user
       → requires synthesis run: escalate_to_loop
  → no LLM needed for deterministic actions
```

---

## Part 3: The Proactive Loop — The Strategy Layer

### Two Modes

The proactive loop runs in two distinct modes. This is critical for cost and latency at scale.

**Maintenance Mode** (frequent, no LLM, cheap):
- Runs every 30-60 min per active user
- Scans open loops: which are past deadline?
- Scans tasks: which are stalled (no activity in N days)?
- Executes deterministic actions: draft follow-ups, send reminders, escalate
- No LLM call unless an action requires generating text
- Cost: near zero per run

**Synthesis Mode** (less frequent, full LLM, expensive):
- Runs 2-3x/day for active users, 1x/day for dormant
- Full context snapshot assembled (pure code, no LLM cost)
- LLM call with strategy prompt
- Cross-domain pattern detection
- New task creation
- Strategic nudges, morning briefs, weekly reviews
- Cost: 1 LLM call per run

**Temporal chaining** (e.g., "run 5 min after meeting ends") is handled by the task's own self-scheduling, not the synthesis loop. The synthesis loop is not precision-scheduled to the minute — it runs at day-level cadence. Tasks handle minute-level event chaining by self-scheduling ARQ jobs with precise timestamps.

### Context Snapshot (Synthesis Mode)

Assembled in parallel, pure code. LLM sees:

```
=== PROACTIVE CONTEXT ===
Time: Thursday 2pm IST | User active: 2h ago | Tier: active

ACTIVE TASKS (3):
  "Schedule meeting with Rahul" — waiting 3 days, open loop EXPIRED
  "Manage inbox" — active, triage ran 12 times today, 3 todos created
  "Follow up with a16z" — waiting 5 days, open loop EXPIRING SOON

CALENDAR (next 48h):
  4pm today: Design review — Priya, Rahul (30 min)
  9am tomorrow: Investor call — a16z (1hr)

EMAIL DELTA (since last run 3h ago):
  NEW: Email from Rahul re: design review
  AGING: Your reply to contracts@acme.com — 3 days pending

TODOS:
  DUE SOON: "Q1 report" — due in 2 days
  OVERDUE: "Review PR #412" — 1 day overdue

GOALS:
  "Ship v2.0 by March" — next node: Deploy staging, stalled 5 days

INTEGRATIONS:
  GitHub: 2 PRs awaiting your review
  Slack: 3 unread DMs (1 from @priya)
  Linear: Sprint ends in 2 days, 3 issues open

MEMORY HIGHLIGHTS:
  "Prefers morning focus time, no interruptions before 10am"
  "Priya is the design lead, reports to user"
```

Critical innovations:
- **Delta awareness**: only shows what changed since last run — not everything from scratch
- **Cross-domain synthesis**: calendar + email + tasks + goals + GitHub + Slack in one view
- **Task-aware**: sees all active GaiaTasks and their open loop status
- **Memory-informed**: Mem0 memories injected, so it knows Priya's role, preferences, etc.

### What the Loop Can Do (max 3 actions per run)

**Create a new GaiaTask:**
"Investor call is tomorrow — no prep task exists. Create one."

**Escalate an existing task:**
"Schedule meeting with Rahul has an expired open loop. Inject escalation into task's next wakeup."

**Send a cross-domain notification:**
"You have a 4pm with Priya, she sent a Slack DM an hour ago, and her PR is waiting for your review." — one notification, not three.

**Trigger a workflow immediately:**
"Sprint ends in 2 days and 3 issues are open. Run the Linear triage workflow now instead of waiting."

**Send a synthesis brief:**
Morning: "Today: 3 meetings, Q1 report due tomorrow, Rahul still hasn't replied."

**Action budget enforcement:** The budget (max 3 actions per synthesis run) is enforced at the tool level, not just in the prompt. A per-run action counter is stored in the `proactive_runs` record (`actions_taken_this_run: int`). The tool checks this counter on every call and returns an error if the budget is exhausted, forcing the agent to call `schedule_next_run()` instead. The counter is reset at the start of each run.

### Self-Scheduling — The Heartbeat

The synthesis agent picks its own next wakeup cadence:

| What it sees | Next synthesis run | Why |
|---|---|---|
| Investor call tomorrow 9am | Tonight 10pm | Prepare brief overnight |
| Expired open loop, Rahul 3 days | In 4h | Check if follow-up was sent, escalate if not |
| Nothing actionable, quiet week | Day after tomorrow | Routine check-in |
| User hasn't been active in 3 days | In 3 days | Dormant — lower cadence |

Note: minute-precision event chaining (e.g., "check in 5 min after the meeting ends") is handled by the task's self-scheduling, not the synthesis loop.

**Three-layer guarantee the loop never dies:**
1. Agent is required to call `schedule_next_run()` — enforced in prompt
2. If it forgets — post-run wrapper auto-schedules 24h fallback + logs warning
3. Supervisor cron (hourly) — rescues any user whose `next_run_at` is >48h stale

**Bounds:** min 30 min (no tight loops), max 7 days (no silent death). Clamped silently.

### User Activity Tiers

| Tier | Condition | Synthesis cadence | Maintenance cadence |
|---|---|---|---|
| Active | Seen < 24h | 2-3x/day | Every 30 min |
| Dormant | Seen 1-7 days | 1x/day | Every 2h |
| Inactive | Seen 7-30 days | 1x/week | 1x/day |
| Churned | Seen > 30 days | Paused | Paused |

**Return detection:** "Return" is defined as any authenticated API call (chat message, app open, any endpoint hit). A `last_seen_at` timestamp on the user record is updated on each request. The proactive loop compares `last_seen_at` to activity tier thresholds.

**Return digest:** When a dormant/inactive user returns → immediate synthesis run triggered (not the next scheduled one) with prompt: "User returned after N days. Surface the 3-5 most important things. Do not flood." Queued notifications (see below) are collapsed into this digest rather than sent individually.

### Anti-Spam

- **Action budget**: max 3 actions per synthesis run. Enforced by tool-level counter in `proactive_runs.actions_taken_this_run` (see above).
- **No-op backoff**: 5 consecutive no-action runs → synthesis interval doubles. Resets on any action.
- **Quiet hours**: user-configurable (default 10pm-7am). Injected into context.
- **Dedup**: notification hash checked before sending. Same notification not sent twice within 24h.
- **Notification hold**: when dormant, notifications are written to a `queued_notifications` array in the `proactive_runs` record instead of being dispatched. On user return, the queued notifications are passed to the return digest synthesis run as context. The synthesis LLM decides which ones to surface (max 5) and which to discard as stale. The queue is capped at 50 entries — oldest are dropped when cap is exceeded.

---

## Part 4: Context Injection — How the Agent Sees Tasks

Every agent call (chat and workflow) already gets user memories injected via `get_memory_message()`. GaiaTask adds a third concurrent fetch:

```python
memories_result, knowledge_result, active_tasks = await asyncio.gather(
    _get_memories(user_id),
    _get_knowledge(user_id),
    _get_active_tasks_summary(user_id),  # Redis 60s cache
)
```

**Progressive disclosure in practice:**

- Every call: lightweight list — task titles + status + any expired open loops
- When a task is being executed: `progress.md` loaded into context
- On demand: agent can call `read_task_vfs(task_id, path)` to drill into specific files

The agent in a chat session can see "oh, there's an active task for scheduling with Rahul, and its open loop expired yesterday" — and proactively mention it to the user without being asked.

---

## Part 5: Key Flows End-to-End

### Flow 1: Meeting Scheduling

```
User: "Schedule a meeting with Rahul"
  → Executor judges: multi-step, expects response → create GaiaTask
  → Creates /users/uid/tasks/task_abc/ with progress.md, context.json
  → Sends email to Rahul
  → Registers open loop: channel=email, sender=rahul@, thread_id=xyz, deadline=+3d
  → Appends to log.md: "Sent scheduling email to Rahul at 10am"

━━━ 3 days pass, no reply ━━━

Maintenance scan
  → open loop deadline passed, if_unresolved = "draft_followup_email"
  → Generates follow-up draft, sends it
  → Updates log.md, context.json (new open loop registered for follow-up)
  → Notifies user: "Rahul hasn't replied. I sent a follow-up."

━━━ Rahul replies ━━━

Gmail trigger fires
  → find_matching_open_loops("email", {sender: rahul@, thread_id: xyz})
  → Marks open loop resolved
  → Stores email in task inbox/rahul_reply_1.json
  → Resumes primary conversation thread (conv_123)
    (fallback: if conv_123 not found in checkpointer → send notification instead)
  → "Rahul is available Thursday 3pm or Friday 2pm. Want me to send an invite?"
```

### Flow 2: Cross-Domain Synthesis

```
Synthesis run at 7am
  → Gathers full context
  → Sees: investor call at 9am, no prep task, Priya sent Slack DM, her PR waiting
  → Creates GaiaTask: "Prep for investor call"
    → GaiaTask self-schedules: wake 5 min after call ends (10am ARQ job)
  → Sends one notification: "Morning: investor call in 2h (brief ready),
    Priya messaged you on Slack and has a PR waiting for your review"
  → Schedules next synthesis run: tomorrow morning (not 5-min precision — task handles that)

━━━ Call ends at 10am ━━━

Task self-wakeup fires (ARQ job at 10:05am)
  → Agent reads progress.md, sees call just ended
  → Captures action items from any notes, drafts follow-up
  → Notifies user: "Call wrapped. I've drafted follow-up notes — want me to send them?"
```

### Flow 3: Inbox Management Task

```
User: "Manage my inbox going forward"
  → GAIA creates GaiaTask: "Inbox Management" (no expiry — long-running)
  → Adopts system workflow "Inbox Triage" (runs every 15 min)
  → Creates workflow "Follow-up Tracker" (runs 1x/day)
  → Creates workflow "Weekly Inbox Review" (runs Sunday 6pm)
  → Task VFS accumulates: triage logs, follow-up drafts, weekly summaries

Each triage run
  → Appends to task's workflows/triage_{date}.json
  → After 7 days: older files moved to workflows/archive/, summary written
  → Emails needing reply registered as open loops automatically

Proactive loop (synthesis, weekly)
  → Reads task's progress.md (bounded — compacted)
  → Sees inbox health trends
  → "Your inbox has 15 emails waiting >3 days. Want a batch-reply session?"
```

---

## MongoDB Collections

### New Collections

**`gaia_tasks`**
```
task_id, user_id, title, description
status: active | waiting | stalled | completed | cancelled | expired | escalating
primary_conversation_id
owned_workflow_ids: List[str]
active_loop_ids: List[str]        # references to open_loops collection
vfs_path: str                     # /users/{uid}/tasks/{task_id}/
created_at, updated_at, completed_at
expires_at                        # TTL — checked by maintenance scan, not MongoDB TTL index
                                  # (we need custom expiration logic, not auto-delete)
```

**`open_loops`** (separate collection, not embedded — enables efficient indexed queries)
```
loop_id, task_id, user_id
description
channel: email | slack | github | calendar | linear | webhook
watch: {channel-specific fields — see watch schema above}
deadline: datetime
if_unresolved: draft_followup_email | send_reminder | escalate_to_loop | notify_user | cancel_task
resolved: bool
resolved_at: datetime | null
resolved_by: str | null  ("signal_match" | "task_completed" | "cancelled" | "expired" | "manual")

Indexes: { user_id, resolved, deadline }  ← maintenance scan query
         { channel, resolved, user_id }   ← trigger handler query
```

**`proactive_runs`** (one document per user, upserted on each run — not a run history log)
```
user_id
mode: maintenance | synthesis
next_run_at, next_run_reason
last_run_at, last_run_summary
last_context_snapshot             # for delta diffing
consecutive_no_op_count
activity_tier: active | dormant | inactive | churned
actions_taken_this_run: int       # reset at run start, checked by action tools
queued_notifications: List[dict]  # held when dormant (max 50, FIFO drop)
```

---

## Build Order

### Phase 0 — GaiaTask Foundation
`gaia_tasks` collection. VFS directory creation at `/users/{uid}/tasks/{task_id}/`. `progress.md`/`log.md`/`context.json` structure. Six agent tools: `create_gaia_task`, `update_gaia_task`, `complete_task`, `cancel_task`, `list_active_tasks`, `read_task_vfs`. Context injection in `get_memory_message()`. Agent can track multi-step work from chat and cancel tasks on user request. No open loop watching yet.

### Phase 1 — Open Loop Tracking
`open_loops` collection with indexes. Watch schema per channel. Auto-registration in executor tool calls (email send → register expectation). `find_matching_open_loops()` in Gmail trigger handler. Maintenance scan ARQ task (every 30 min) with expired loop scanning. Deterministic `if_unresolved` actions. Follow-up drafting. Full meeting scheduling end-to-end.

### Phase 2 — Workflow Ownership
GaiaTask can create, adopt, enable, disable, trigger workflows. Workflow outputs flow to task `workflows/` VFS folder with 7-day rotation. "Manage inbox" as first large-scale task owning multiple workflows.

### Phase 3 — Proactive Loop (Maintenance Mode)
`proactive_runs` collection. ARQ sweep (every 1 min). `execute_maintenance_run()` — pure code, no LLM. Stalled task detection (uses task activity timestamps; workflow-staleness detection deferred to after Phase 2 delivers workflow-to-VFS output flow). Expired open loop escalation. Activity tiers. No-op backoff. Return detection via `last_seen_at`.

### Phase 4 — Proactive Loop (Synthesis Mode)
Full context snapshot assembly. `execute_synthesis_run()` via `call_agent_silent()`. Self-scheduling with `schedule_next_run()`. Strategy prompt. Action budget enforced by tool-level counter. Cross-domain notifications. New task creation from loop. Post-run safety net (24h fallback). Supervisor health cron (hourly). Queued notification hold + return digest.

### Phase 5 — Rich Context + Intelligence
Delta diffing (`last_context_snapshot`). `find_matching_open_loops()` extended to Slack, GitHub, Calendar, Linear, webhook channels. VFS log compaction (500-line threshold). Memory-informed decisions. Goal awareness. Quiet hours.

### Phase 6 — Learning + Preferences
User proactive preferences (enabled, quiet hours, max actions, preferred channels). Dismiss/act ratio tracking. Per-user escalation tuning. Weekly review and goal check-ins.

---

## What This Unlocks

Things that genuinely cannot exist without this system:

- **Follow-up that never drops**: Every email sent, every PR opened, every contract sent is tracked. GAIA follows up without being asked.
- **Cross-domain synthesis**: "You have a meeting with Priya in 2h, she messaged on Slack, and her PR needs your review" — no single integration sees all three.
- **Temporal chaining**: Tasks self-schedule for 5 min after a meeting ends to capture action items. Synthesis loop handles day-level strategy; tasks handle minute-level event chaining.
- **Goal awareness**: "Ship v2.0: next node is Deploy staging, no progress in 5 days" — goals become live-tracked, not just aspirational.
- **Inbox as a managed task**: Not just triage-and-forget but a living task that tracks reply rates, escalates aging threads, runs weekly reviews.
- **Return digest**: Came back after 4 days? One synthesis notification with the 5 things that actually matter, not 50 queued pings.
