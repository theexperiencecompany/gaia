## ADDED Requirements

### Requirement: The streak is honest

Streak and heatmap state SHALL derive exclusively from completed-todo records: a day is green iff ≥1 todo (either assignee) has `completed_at` that day in the user's timezone. Days with no completed todo SHALL be gray and SHALL break the streak — including days where only background sweeps, syncs, or triage ran. No mechanism SHALL pad, freeze, or repair a streak.

#### Scenario: GAIA's real work sustains the streak
- **WHEN** the user does nothing on a Saturday but a GAIA todo completes
- **THEN** Saturday is green

#### Scenario: Mutual idleness breaks the streak
- **WHEN** neither party completes a todo on a day (though crons ran)
- **THEN** the day is gray and the streak resets; the next briefing acknowledges it honestly

### Requirement: Badges are rare and real

An `awards` collection SHALL store earned badges `{user_id, key, earned_at}`. v1 badge set, checked once per day inside the briefing run: `first_approve`, `first_overnight_shipment` (first GAIA todo completed between 10pm–7am user-local), `gaia_100_todos`, `streak_7`, `streak_30`. Each badge SHALL be earnable once, delivered as a notification via the orchestrator and mentioned in the next briefing/weekly digest. No points, no effort-based rewards, no badge cabinet page in v1.

#### Scenario: Badge fires once
- **WHEN** a user's 100th GAIA-completed todo lands and later a 101st completes
- **THEN** `gaia_100_todos` is awarded and notified exactly once

### Requirement: The edition template library is the founder's explorer set

The template source of truth is the vendored Edition Explorer library (recovered session 547b140a: ~20 parametric families, 500+ skin combos), rendered byte-identical through the same headless-Chromium pipeline as every edition email — new families are one vendored module + registry pickup. **Both daily and weekly editions rotate over the eligible family set** under the shuffled-cycle law below, with independent per-kind rotation state ("daily fun docs"). Permitted deviations from byte-identical vendoring: null-safety guards only (real payload items carry no time field; the demo fixture always did). A family whose content is not fully derived from the real payload (currently the explorer's own "weekly" family — hardcoded demo aggregates) SHALL be excluded from rotation until a real data adapter exists: fabricated content in a briefing is never acceptable.

#### Scenario: Every family's content is real
- **WHEN** any edition renders for a user
- **THEN** every fact shown derives from that user's stored payload, and a family that cannot satisfy this is not in the rotation pool

### Requirement: Weekly editions are beautiful rotating documents

A `weekly_digest` system workflow (Sunday 5pm user-local) SHALL emit a `kind: weekly` BriefingPayload summarizing the week: completed work split by assignee, an hours-saved estimate, streak length, and what's ahead (open todos, scheduled follow-ups). It SHALL render as a designed editorial email document from a **template family** chosen by a shuffled-cycle rotation engine: each cycle is a random permutation of every available family, consumed in order, so no family repeats until the whole set has been used; the next cycle reshuffles (never producing the same family twice in a row across the cycle boundary). The rotation state is per-user and persisted, so the sequence survives restarts and template additions join the next cycle. v1 ships 2–3 template families from the edition-template system, expanding later.

#### Scenario: No repeat until exhaustion
- **WHEN** 3 template families exist and a user receives 6 weekly editions
- **THEN** the first three editions use all three families in some order, the next three use all three again in a new order, and editions 3 and 4 never use the same family The weekly edition is an emailed keepsake document — it is NOT a dashboard surface. It SHALL also appear in the briefing archive.

> Removed 2026-08-07: the public shareable Wrapped card is cut entirely (product decision — no public stats surface). The share-is-opt-in scenario below is retained only as the guarantee that no public URL for a user's stats ever exists.

#### Scenario: Weekly email delivered
- **WHEN** the weekly run completes for a user with email enabled
- **THEN** the weekly digest email is sent and the payload appears in the dashboard archive

#### Scenario: Share is opt-in
- **WHEN** the user has not tapped share
- **THEN** no public URL for their Wrapped card exists

### Requirement: Completion reports carry the next step

When a GAIA todo the user approved completes during the user's waking hours, the completion message on their priority chat channel MAY include one contextual next-step suggestion drawn from open todos, goal state, or the completed work itself ("Done — sent the Rahul follow-up. Want me to prep the invoice chase next?"). Nudges SHALL be completion-triggered only — the system SHALL NOT send standalone time-based engagement pings ("it's 2pm, want anything?"). At most one suggestion per completion message; a suggestion dismissed or ignored SHALL NOT be repeated in later completion messages.

#### Scenario: Completion nudge is contextual and single
- **WHEN** an approved GAIA todo completes at 2pm and two other candidate tasks exist
- **THEN** the completion message contains the report plus at most one suggestion, and no separate engagement ping is sent

#### Scenario: No clock-based pings
- **WHEN** no approved todo completes during an afternoon
- **THEN** no proactive engagement message is sent that afternoon

### Requirement: Retention instrumentation from day one

The system SHALL emit analytics events: `briefing_sent`, `briefing_opened`, `todo_proposed`, `todo_approved`, `todo_dismissed`, `proposal_expired`, `gaia_todo_completed`, `handoff_created`, `first_steps_step_done` — each carrying user id, todo/briefing kind, and channel where applicable. Approve rate (approved / (approved + dismissed + expired)) SHALL be derivable from these events; `todo_approved` is the activation event. Events SHALL be emitted server-side at the state transition, not from the client.

#### Scenario: Telegram approve is counted
- **WHEN** a user approves a proposal via the Telegram inline button
- **THEN** `todo_approved` is emitted with `channel: telegram`

### Requirement: No global leaderboard

The system SHALL NOT rank users against each other on productivity metrics. Comparison surfaces are limited to the user's own history (streak, heatmap, weekly digest) and explicitly shared Wrapped cards.

#### Scenario: No cross-user ranking endpoint
- **WHEN** the v1 feature ships
- **THEN** no API endpoint exposes one user's productivity metrics ranked against others'
