## ADDED Requirements

> Revised 2026-07-10: the Mission Control layout (briefing hero + timeline + action rail + heatmap) was replaced by the **Today view** before rollout — a single-column, status-grouped list optimized for scanning and acting.
>
> Revised 2026-08-06: the standalone `/dashboard` route is removed. The product has exactly three user-facing surfaces — chat, todos, briefing documents — and a separate dashboard route showed only task-shaped data, duplicating `/todos`. The Today view now lives at the top of `/todos`. A dashboard route may return later only if there is daily-glance content that is not task-shaped.

### Requirement: The Today view is the top of the todos page

The `/todos` page SHALL open with the Today view: the briefing headline as the page heading with a one-line subline (date, needs-you count, next calendar event, runs remaining), followed by flat status-grouped sections in priority order — **Needs you**, **Suggested**, **In flight**, **Your tasks**, **Done today** — above the regular todo list. Empty sections render nothing. The standalone `/dashboard` route SHALL be removed (redirecting to `/todos`), and the dashboard feature's separate row components SHALL be deleted or absorbed into the todos feature — no parallel implementations. The replacement ships directly — **no feature flags**. The page SHALL follow GAIA's design system (`DESIGN.md`). The post-login redirect (`/c`) is explicitly NOT changed by this spec.

#### Scenario: Direct replacement
- **WHEN** the change is deployed
- **THEN** `/dashboard` redirects to `/todos`, the Today view renders at the top of `/todos` for all users, and no code path renders a standalone dashboard page

### Requirement: One sectioned payload

`GET /dashboard/today` SHALL return the page pre-grouped server-side, as one payload: `headline`, `subline` (date, needs_you count, next_event), `runs` (used/limit/period/reset for `gaia_todo_executions`), and five sections queried from the todos collection — `needs_you` (`proposed` | `needs_you`, with `blocker_question`), `suggested` (user todos carrying `gaia_offer`, excluding those due today), `in_flight` (`queued` | `running`), `your_tasks` (user todos due/scheduled today, with any `gaia_offer` inline), `done_today` (`completed_at` today, both assignees). No new event store; the client renders and does not compute.

#### Scenario: Overnight work appears in Done today
- **WHEN** a GAIA todo completed at 3:02am and the user opens the dashboard at 8:30am
- **THEN** `done_today` contains it with `assignee: "gaia"` and the row renders dimmed with its completion time

### Requirement: The headline is the briefing's headline

Before user-local noon, the page headline SHALL be the day's `BriefingPayload.headline` (the morning push and the page share one sentence by construction). After noon, or when no briefing exists for today, a deterministic headline SHALL be built in code from the section counts. No LLM call is made by the dashboard.

#### Scenario: Afternoon flip
- **WHEN** the user opens the dashboard at 3pm with 2 items in needs_you
- **THEN** the headline reads from counts (e.g. "2 things need you."), not the stale 8am sentence

### Requirement: Acting from the rows

Rows SHALL act inline via the same endpoints as everywhere else: Approve (`POST /todos/{id}/approve`, 402 renders the upgrade pitch), Skip (`/dismiss`, revealed on hover), Run on a suggestion (`/handoff`), Answer on a blocked run (`/answer`, inline input under the row showing `blocker_question`), and a checkbox completing the user's own todos.

#### Scenario: Answering resumes the run without navigation
- **WHEN** a `needs_you` row shows its blocker question and the user submits an answer inline
- **THEN** the todo re-queues, the row moves to In flight on the next refetch, and no page navigation occurs

### Requirement: Freshness is push-first

Lifecycle transitions (`approve`, `answer`, `dismiss`, `handoff`, worker status flips) SHALL broadcast `todo.execution_status` over the existing user WebSocket; the dashboard invalidates on receipt. Window-focus refetch is the safety net, and a slow poll runs only while any item is `queued`/`running`.

#### Scenario: Row approve updates without reload
- **WHEN** the user approves a proposal row
- **THEN** the item leaves Needs you and appears In flight without a page reload
