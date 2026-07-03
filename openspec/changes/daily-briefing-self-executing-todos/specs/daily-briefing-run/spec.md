## ADDED Requirements

### Requirement: Daily briefing is a per-user system workflow

The system SHALL provision a system workflow (`system_workflow_key = "daily_briefing"`) for every user — at onboarding completion for new users and via a one-time backfill for existing users — scheduled cron `0 8 * * *` in the user's timezone, executing through the standard workflow ARQ path into `call_agent_silent` with a dedicated briefing prompt. Users SHALL be able to disable it or change its hour like any workflow.

#### Scenario: New user is provisioned
- **WHEN** a user completes onboarding
- **THEN** a `daily_briefing` system workflow exists for them, activated, with `next_run` the following 8am in their timezone

### Requirement: The run curates before it creates

The briefing run's first step SHALL sweep the existing todo list: expire proposals older than `PROPOSAL_TTL_HOURS`, merge duplicate GAIA todos, and flag stale user todos. Only after curation MAY it create or propose new todos, within the budgets of `unified-todo-model`. Cleanup performed SHALL be reported in the briefing ("I cleared 4 stale things off your list").

#### Scenario: Stale proposals expire before new ones appear
- **WHEN** the run starts with two proposals older than 72h and wants to propose two new todos
- **THEN** the old proposals are `expired` (memory signals written) before the new ones are created

### Requirement: The run looks back before planning

The run SHALL compare yesterday's briefing payload against what actually happened (todo completions, `WorkflowExecution` records, calendar) and reflect the delta: completed work acknowledged, slipped items rolled forward or offered for takeover. Slipped items SHALL NOT silently disappear.

#### Scenario: A slip rolls forward with an offer
- **WHEN** yesterday's plan included a user todo that was not completed
- **THEN** today's briefing mentions it once and offers GAIA takeover where the approval rule allows

### Requirement: One briefing message per day is law

The system SHALL deliver at most one briefing message per user per day. The only permitted additional proactive messages are: a time-critical `needs_you` blocker, or replies when the user messaged first. For ignored items the escalation ladder SHALL be: mention in brief → one re-mention with a different angle → drop to a memory signal. The run SHALL read its own prior briefings and recent conversation history before writing and SHALL NOT re-ask a question the same way twice.

#### Scenario: Ignored item exits to memory
- **WHEN** an item has appeared in two briefings with no user action
- **THEN** the third briefing omits it and a memory signal records the double-ignore

#### Scenario: No second message on a quiet day
- **WHEN** the briefing was sent and nothing time-critical arises
- **THEN** no further proactive message is sent that day on any channel

### Requirement: Idle days are honest

When GAIA has no real queued work, the briefing SHALL say so and ask whether priorities have shifted — it SHALL NOT pad with heartbeat activity (triage sweeps, syncs) presented as work.

#### Scenario: Empty queue prompts the priorities question
- **WHEN** the run finds no queued/running GAIA todos and no proposals worth making
- **THEN** the briefing is short, states that nothing is queued, and asks if the user's focus changed

### Requirement: Gone-quiet users get one adaptive winback, not repeats

When a user has ignored 3 or more consecutive briefings, the next run SHALL switch to a winback mode: safe (non-approval) work continues silently, and the briefing is a single short message centered on the one most valuable pending item, written differently from prior briefings. Winback SHALL NOT fire on consecutive days for a still-silent user; cadence backs off using the maintenance-sweep backoff pattern.

#### Scenario: Winback after three ignored briefings
- **WHEN** briefings on three consecutive days had no open/reply/approve
- **THEN** the next communication is a single winback message and daily cadence pauses pending user activity

### Requirement: The run emits exactly one structured payload

Each run SHALL end by persisting exactly one `BriefingPayload` (see `briefing-artifacts`) for the user and date, then delivering it via the notification orchestrator (in-app + linked platforms, email when enabled). Payload persistence SHALL precede delivery so the dashboard never misses a brief that was sent to chat.

#### Scenario: Payload persists even if a channel fails
- **WHEN** Telegram delivery fails after the payload is stored
- **THEN** the briefing still renders on the dashboard and the failure is logged per orchestrator behavior
