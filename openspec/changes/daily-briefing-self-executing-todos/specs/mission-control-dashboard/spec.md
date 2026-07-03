## ADDED Requirements

### Requirement: Mission Control replaces the dashboard widget grid

The `/dashboard` page SHALL be rebuilt as Mission Control: the latest briefing rendered via the OpenUI briefing component as the header (collapsible to its headline), a day timeline, an action rail, and the contribution heatmap. The prior five-widget `GridSection` layout is removed from this page and its dead code deleted. The replacement ships directly — **no feature flags** — gated instead by the founder-persona end-to-end verification in tasks. The page SHALL follow GAIA's design system (`DESIGN.md`) throughout, with the briefing header using the editorial typography defined in `briefing-artifacts`. The post-login redirect (`/c`) is explicitly NOT changed by this spec.

#### Scenario: Direct replacement
- **WHEN** the change is deployed
- **THEN** `/dashboard` renders Mission Control for all users and no code path can render the old widget grid

### Requirement: The day timeline interleaves existing records

A `GET /dashboard/today` aggregation endpoint SHALL return today's items chronologically interleaved: todos (both assignees, with execution-state glyphs), calendar events, and completed `WorkflowExecution` entries — sourced from existing collections with no new event store. The timeline SHALL update live via the existing notification WebSocket.

#### Scenario: Overnight work appears completed on the timeline
- **WHEN** a GAIA todo completed at 3:02am and the user opens the dashboard at 8:30am
- **THEN** the timeline shows the 3:02am completion with a done glyph ahead of upcoming calendar events

### Requirement: The action rail answers "what now"

The action rail SHALL render three stacks: **Next up** — the top unfinished user-assigned todo; **Waiting on you** — todos in `proposed` or `needs_you`, each with inline Approve/Dismiss and a one-glance result preview (the staged draft or plan, not a bare title); **Done today** — completed-todo counts split `GAIA n · You n`. Approve/Dismiss in the rail SHALL call the same endpoints as everywhere else.

#### Scenario: Result visible before the tap
- **WHEN** a proposed todo carries 12 drafted DMs
- **THEN** the rail entry previews the drafts (expandable) before the user approves

#### Scenario: Rail approve updates the timeline
- **WHEN** the user approves a proposal in the rail
- **THEN** the item leaves "Waiting on you", the todo enqueues, and the timeline reflects the state change without reload

### Requirement: Contribution heatmap of real work

The dashboard SHALL render a GitHub-style heatmap fed by one aggregation endpoint over todo `completed_at` (both assignees). Only completed todos count; heartbeat/cron activity SHALL NOT color a day. Hovering a day shows its counts split by assignee.

#### Scenario: Idle day is gray
- **WHEN** a day has zero completed todos
- **THEN** that day renders gray regardless of any background sweeps that ran
