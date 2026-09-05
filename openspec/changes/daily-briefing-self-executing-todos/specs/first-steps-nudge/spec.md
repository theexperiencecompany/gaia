## ADDED Requirements

### Requirement: A first-steps checklist widget appears bottom-right across the app

A persistent, collapsible widget SHALL render at the bottom-right of all `(main)` app pages for users who have not completed activation, presenting an ordered checklist: (1) explore the workflows page, (2) connect a first non-Gmail integration, (3) link Telegram for notifications, (4) meet Mission Control, (5) approve your first GAIA todo. Each step SHALL deep-link to its surface. The widget SHALL be dismissible per-step and entirely, and SHALL unmount permanently once all steps are complete or dismissed.

#### Scenario: Fresh user sees the checklist everywhere
- **WHEN** a newly onboarded user navigates between chat, todos, and workflows pages
- **THEN** the widget renders bottom-right on each with current progress

#### Scenario: Completion removes it forever
- **WHEN** the final open step completes
- **THEN** the widget celebrates once and never renders again for that user

### Requirement: Progress derives from real signals, not self-report

Step completion SHALL be recorded on the user doc (`first_steps: {step_key: completed_at}`) by existing signals — route visit (workflows page, dashboard), integration connect events, platform-link creation, and the first `todo_approved` — with no polling and no manual "mark done". Steps satisfied before the widget first renders SHALL be pre-checked.

#### Scenario: Already-linked Telegram is pre-checked
- **WHEN** a user linked Telegram before the widget ships
- **THEN** step 3 renders complete on first appearance

#### Scenario: Approve completes the last mile
- **WHEN** the user taps Approve on any GAIA todo anywhere (dashboard, todo list, Telegram)
- **THEN** step 5 completes and `first_steps_step_done` is emitted
