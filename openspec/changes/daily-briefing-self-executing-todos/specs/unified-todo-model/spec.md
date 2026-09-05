## ADDED Requirements

### Requirement: Every todo has an assignee

The system SHALL add `assignee: "user" | "gaia"` (default `"user"`) to the todo model, replacing the `gaia-tracked` label as the discriminator for GAIA-owned todos. A migration SHALL backfill `assignee: "gaia"` on every todo whose `labels` contains `gaia-tracked` and remove that label. For one release, readers (VFS projection, context injection, list filters) SHALL dual-read (`assignee == "gaia"` OR legacy label), after which `GAIA_TRACKED_LABEL` is retired.

#### Scenario: Legacy tracked todo is migrated
- **WHEN** the backfill runs against a todo with `labels: ["gaia-tracked"]` and an armed `scheduled_at`
- **THEN** the todo has `assignee: "gaia"`, an `execution_status` reflecting its scheduling state, and no `gaia-tracked` label

#### Scenario: User todos are untouched
- **WHEN** the backfill runs against a todo without the label
- **THEN** the todo has `assignee: "user"` and no `execution_status`

### Requirement: GAIA todos carry an execution lifecycle

GAIA-assigned todos SHALL carry `execution_status`: `proposed | queued | running | needs_you | done | failed | expired | dismissed`. Transitions SHALL be server-enforced: `proposed → queued` only via the Approve action; `proposed → dismissed` via Dismiss; `proposed → expired` only by the curation pass after `PROPOSAL_TTL_HOURS` (72h); `queued → running → done | failed | needs_you` only by the execution worker. Approve SHALL enqueue execution on the existing tracked-todo rail (`schedule_execution` → `execute_tracked_todo`). A `failed` todo SHALL carry a human-readable cause and SHALL be rendered as prominently as `done` in the list and the next briefing.

#### Scenario: Approve queues execution
- **WHEN** `POST /todos/{id}/approve` is called on a `proposed` GAIA todo
- **THEN** the todo becomes `queued` and an ARQ execution job is enqueued for it

#### Scenario: Failure is loud
- **WHEN** an execution run raises after retries (e.g. expired integration token)
- **THEN** the todo shows `failed` with the cause in the list and appears in the next briefing's sections

#### Scenario: Invalid transition rejected
- **WHEN** any caller attempts to set a `proposed` todo directly to `running`
- **THEN** the service rejects the transition

### Requirement: A blocked run carries its question and resumes on the answer

When a run pauses on a decision only the user can make, the todo SHALL flip to `needs_you` via a guarded lifecycle entry point (`block`: only from `queued`/`running`, agent-callable as `block_todo`) carrying a `blocker_question`. The honesty gate's unconfirmed-send flip SHALL also set `blocker_question`. Every surface renders the same question: the dashboard row shows it with an inline answer input; the chat agent relays it and matches the user's reply. `answer` SHALL be the only `needs_you → queued` path (`POST /todos/{id}/answer` or the `answer_todo` agent tool): it records the Q&A into the notes facet — which the next execution reads — clears the blocker, and re-enqueues the run with its existing `execution_intent`. Answering never re-meters the execution quota.

#### Scenario: Blocked run asks one question everywhere
- **WHEN** a run calls `block_todo` with "Which MRR figure should lead?"
- **THEN** the todo is `needs_you`, the dashboard row shows the question with an answer box, and the chat context lists the todo as waiting on that question

#### Scenario: A texted answer resumes the run
- **WHEN** the user replies "41.2k" on any chat platform and the agent calls `answer_todo`
- **THEN** the Q&A lands in the notes facet, the todo re-queues, and the resumed run reads the answer and continues

#### Scenario: Blocking a terminal todo is rejected
- **WHEN** `block_todo` is called on a `done` or `proposed` todo
- **THEN** the lifecycle rejects the transition

### Requirement: Approval rule decides the entry state

Todo creation by the agent SHALL require a `requires_approval: bool` argument classified by the outward-visibility rule: actions observable outside the user–GAIA pair (sending email/DMs, posting, inviting others, spending) SHALL be `true` → entry state `proposed`; work only the pair can see (research, drafts, triage, prep) SHALL be `false` → entry state `queued`, executing without permission. **Explicit-instruction exception** (added 2026-08-07): when the user's own words directly instructed the exact outward action and its target ("send Bob the invoice reminder tomorrow at 9am"), the instruction IS the approval — the todo enters `queued` and executes on schedule without a redundant Approve tap; the send-time HIL approval gate remains the independent backstop verifying the user's words authorized the action. A goal or vague ask ("help me collect invoices") does NOT qualify and is proposed. During execution, the silent-run prompt contract SHALL forbid outward-facing actions on todos that entered neither via Approve nor via an explicit instruction covering that action; when a plan grows a NEW outward action mid-run, the todo SHALL flip to `needs_you` instead of acting. Missing integrations SHALL never block work: the run produces the deliverable as content and completes with a connect-or-take-content handoff.

#### Scenario: Explicit instruction executes without a redundant tap
- **WHEN** the user tells GAIA "send Bob the invoice reminder tomorrow at 9am"
- **THEN** the todo enters `queued`, sends at 9am with no Approve prompt, and the HIL send-time gate verifies the user's words authorized that exact send

#### Scenario: Research runs without a tap
- **WHEN** the agent creates a GAIA todo "research pre-seed investors and draft intro DMs" with `requires_approval: false`
- **THEN** it enters `queued` and executes without user interaction, and the drafted DMs are staged — not sent

#### Scenario: Sending requires the tap
- **WHEN** the agent creates "send the 12 drafted investor DMs"
- **THEN** it enters `proposed` and no send occurs until Approve

#### Scenario: Missing integration degrades to handoff
- **WHEN** a deck-building todo runs and Google Slides is not connected
- **THEN** the run completes with full deck content produced and the todo offers connect-or-take-content

### Requirement: Server-side budgets cap GAIA todos

The system SHALL enforce, at the service layer: `MAX_GAIA_TODOS_IN_FLIGHT = 5` (statuses `queued | running | needs_you`) and `MAX_PENDING_PROPOSALS = 3`. Creation beyond a cap SHALL be rejected with an error instructing the agent to complete, expire, or dismiss existing items first. The caps SHALL be constants in `apps/api/app/constants/todos.py`.

#### Scenario: Fourth proposal rejected
- **WHEN** the agent attempts to create a fourth `proposed` todo while three are pending
- **THEN** the creation is rejected and the tool result names the three pending proposals

### Requirement: Every GAIA todo is traceable

Agent creation of a GAIA todo SHALL require a `serves` argument naming the goal, memory item, or explicit user request the todo advances. `serves` SHALL be stored on the todo and rendered wherever the proposal is shown ("because you're raising a pre-seed"). Creation without a non-empty `serves` SHALL be rejected.

#### Scenario: Untraceable creation rejected
- **WHEN** the agent calls the creation tool with an empty `serves`
- **THEN** the service rejects the creation

### Requirement: Goals are a data-model concept, not a user-facing surface

`kind: "goal"` todos SHALL exist only as backstage structure: the nightly pass advances them, child tasks link via `goal_id`, and `serves` traceability references them. The product SHALL NOT ship a goal-lane UI, and goals SHALL NOT link to workflows (`source_todo_id` on a goal is not a supported relationship — recurring goal work is expressed as GAIA todos with `recurrence`). The user-facing primitive count stays at three surfaces: chat, todos, briefing documents.

#### Scenario: A goal renders as a pinned todo, nothing more
- **WHEN** a user has an active goal lane with three child tasks
- **THEN** the todos page shows them as todos (the goal pinned, children linked), with no separate lane view, board, or goal-workflow surface

### Requirement: Dismissal and expiry teach memory

Every Dismiss and every expiry SHALL write a structured memory signal (`proposal_rejected: {kind, serves, reason?}`). Agent runs that propose todos SHALL read these signals and SHALL NOT re-propose a kind rejected or expired 3+ times, unless the user explicitly asks again.

#### Scenario: Third strike ends a proposal kind
- **WHEN** investor-DM proposals have been dismissed or expired three times
- **THEN** subsequent briefing runs create no further investor-DM proposals and may raise the topic at most once via the weekly digest

### Requirement: Users can hand todos to GAIA, and GAIA quietly offers

`POST /todos/{id}/handoff` SHALL convert a user todo to `assignee: "gaia"` with entry state per the approval rule, and GAIA SHALL append a one-line plan to the todo's work log. Independently, when a user creates a todo, GAIA SHALL classify it silently: fully doable → a non-blocking "GAIA can do this" offer appears on the todo; partially doable → GAIA preps supporting material into the work log without changing the assignee; not doable → no UI change and no message. Capture SHALL remain instant — classification never blocks creation.

#### Scenario: Silent classification never nags
- **WHEN** a user creates "hit the gym"
- **THEN** the todo renders as a plain user todo with no offer and no notification

#### Scenario: Offer on a doable todo
- **WHEN** a user creates "follow up with the lawyer about the SAFE"
- **THEN** a dismissible offer to hand it to GAIA appears on that todo only

### Requirement: The work log is visible on the todo

The canvas of any GAIA-assigned todo SHALL be rendered in the todo's detail view as its work log (what GAIA did, is doing, learned). The sidebar-only `CanvasViewer` placement is replaced; canvas storage is unchanged.

#### Scenario: Work log in detail view
- **WHEN** a user opens a GAIA todo that has canvas content
- **THEN** the work log renders in the detail view without navigating to a separate sidebar

### Requirement: The todos surface is redesigned to the editorial bar

The todos sidebar and todo detail view SHALL be redesigned as part of this change — not patched — to GAIA's design system (`DESIGN.md`) at the Notion/Apple/ElevenLabs/Vercel cleanliness bar: assignee and execution state legible at a glance (glyphs, not label chips), proposals visually distinct with inline Approve/Dismiss and one-glance previews, the work log presented as a first-class document (editorial typography per `briefing-artifacts`), and GAIA offers rendered as quiet affordances rather than banners. Implementation SHALL be preceded by the same multi-candidate design-exploration pass as the briefing card, with user selection before build.

#### Scenario: State legible without reading
- **WHEN** a user scans a mixed list of user todos, running GAIA todos, and proposals
- **THEN** who owns what and what needs a tap is distinguishable from glyph/treatment alone

#### Scenario: No label chips as state
- **WHEN** a GAIA todo renders anywhere
- **THEN** its GAIA-ness comes from the design treatment, never from a visible `gaia-tracked`-style label chip
