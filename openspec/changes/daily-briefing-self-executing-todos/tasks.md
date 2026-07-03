## 1. Phase A — Unified todo model (foundation; everything else depends on it)

- [ ] 1.1 Add `assignee: Literal["user","gaia"] = "user"` and `execution_status: ExecutionStatus | None` to `TodoBase` in `apps/api/app/models/todo_models.py`; define the `ExecutionStatus` enum (`proposed|queued|running|needs_you|done|failed|expired|dismissed`).
- [ ] 1.2 Add constants to `apps/api/app/constants/todos.py`: `MAX_GAIA_TODOS_IN_FLIGHT = 5`, `MAX_PENDING_PROPOSALS = 3`, `PROPOSAL_TTL_HOURS = 72`. Mark `GAIA_TRACKED_LABEL` deprecated (removed in 1.10).
- [ ] 1.3 Server-enforce transitions + budgets + `serves` traceability in `apps/api/app/services/tracked_todo_service.py`: creation rejects over-budget or `serves`-less GAIA todos; only Approve moves `proposed → queued` (enqueue via existing `schedule_execution`); only the worker sets `running/done/failed/needs_you`; `failed` requires a cause.
- [ ] 1.4 Update `apps/api/app/agents/tools/tracked_todo_tools.py`: required `serves: str` and `requires_approval: bool` args with the outward-visibility rubric in the tool description; entry state from `requires_approval`; tool errors surface budget rejections with the pending items listed.
- [ ] 1.5 Add endpoints in `apps/api/app/api/v1/endpoints/todos.py`: `POST /todos/{id}/approve`, `POST /todos/{id}/dismiss` (optional reason), `POST /todos/{id}/handoff`. Dismiss/expiry write the `proposal_rejected` memory signal.
- [ ] 1.6 Wire the memory-signal read into the briefing/creation prompts: kinds rejected/expired 3+ times are not re-proposed (prompt section + a service-side recent-rejections summary injected into the run context).
- [ ] 1.7 Silent classification of new user todos (offer / prep / stay-silent) as a post-create background step; offer renders as a dismissible affordance on the todo only — no notification.
- [ ] 1.8 Execution-side approval contract: background-run prompt forbids outward actions on todos not entered via Approve; mid-run new outward action flips todo to `needs_you` with a linked conversation. Missing-integration handoff: complete with content + connect-or-take-content choice.
- [ ] 1.9 Migration script: backfill `assignee`/`execution_status` from `gaia-tracked` labels, remove the label; dual-read in VFS projector (`tracked-todos-vfs` delta), context injection (`message_helpers.py`), and list filters for one release.
- [ ] 1.10 Frontend (`apps/web/src/features/todo/`): assignee + state glyphs in list, Approve/Dismiss on proposals with one-glance result preview, "Hand to GAIA" action, work log (canvas) in todo detail view replacing sidebar-only `CanvasViewer` placement. Remove label-based tracked-todo detection.
- [ ] 1.11 `nx lint api && nx type-check api && nx run-many -t type-check --projects=web,desktop && nx run-many -t lint --projects=web,desktop`; manually verify: create → propose → approve → run → done/failed round-trip in dev.

## 2. Phase B — Daily briefing run

- [ ] 2.1 `BriefingPayload` Pydantic model + `briefings` collection with indexes (`user_id + date`, `kind`).
- [ ] 2.2 Briefing prompt (new file under `apps/api/app/agents/prompts/`): curate-first contract, lookback vs yesterday's payload, budgets, traceability, one-message law, escalation ladder, idle honesty, winback mood, payload-only output.
- [ ] 2.3 `daily_briefing` system workflow definition in `apps/api/app/services/system_workflows/`: provision at onboarding completion + one-time backfill task; cron `0 8 * * *` user-tz; execution through the standard workflow path into `call_agent_silent`.
- [ ] 2.4 Run pipeline: curation service step (expire proposals, memory signals) runs deterministically before the agent turn; payload validated + persisted before delivery via the notification orchestrator.
- [ ] 2.5 Winback behavior keyed off consecutive unacknowledged briefings (derive from `briefing_opened`/approve events); cadence backoff per maintenance-sweep pattern.
- [ ] 2.6 Dogfood flag: provision only for internal users first; backfill to all users as the final task of this phase.
- [ ] 2.7 Lint/type-check; verify one full morning cycle in dev (seeded todos + goal memory → briefing payload + Telegram delivery).

## 3. Phase C — Briefing artifacts & channels

- [ ] 3.1 OpenUI briefing component family (`apps/web/src/config/openui/` + components): masthead, bands-gradient hero with `hue-rotate`, serif headline, lede, stat row, numbered sections, caption. Archive view of past briefs.
- [ ] 3.2 Extend outbound envelope with optional `actions: [{label, callback_data}]` in `apps/api/app/schemas/outbound.py` and the TS twin in `libs/shared/ts/src/bots/`; keep byte-compatible when absent.
- [ ] 3.3 Telegram adapter (`apps/bots/telegram/src/adapter.ts`): render actions as inline keyboard; callback handler posts to approve/dismiss endpoints with platform-link identity; edit message after action.
- [ ] 3.4 Email channel adapter in `apps/api/app/utils/notification/channels/`: HTTP ESP behind env config, dark when unset; register in orchestrator; add to channel preferences + `NotificationSettings.tsx`.
- [ ] 3.5 Email templates (daily brief, weekly digest, plain notification) — hand-designed, payload-slotted; template selection by `kind`.
- [ ] 3.6 Lint/type-check across api, web, bots; verify: same payload renders on dashboard, Telegram (with working Approve), and email preview.

## 4. Phase D — Mission Control dashboard

- [ ] 4.1 `GET /dashboard/today` aggregation endpoint (todos + calendar + `WorkflowExecution`, chronological) and heatmap aggregation endpoint over `completed_at`.
- [ ] 4.2 Rebuild `apps/web/src/app/[locale]/(main)/dashboard/page.tsx` behind a feature flag: briefing header (OpenUI component, collapsible), timeline left, action rail right (Next up / Waiting on you with inline Approve + preview / Done today GAIA n · You n), heatmap.
- [ ] 4.3 Live updates over the existing notification WebSocket (todo state changes, executions).
- [ ] 4.4 Lint/type-check; verify timeline interleaving, rail approve round-trip, heatmap gray-day honesty in dev.

## 5. Phase E — Onboarding seed & first-steps nudge

- [ ] 5.1 Add "What are you working on right now?" to onboarding on all paths (`apps/web/src/features/onboarding/`, `OnboardingRequest`, `onboarding_service.py`); write to memory; unify with `onboarding.focus`.
- [ ] 5.2 First-briefing guarantee: briefing prompt requires ≥1 item tracing to the stated goal; when skipped, derive from triage and close with the goal question.
- [ ] 5.3 First-steps widget in the `(main)` layout: 5-step checklist, deep links, collapse/dismiss, permanent unmount on completion; `first_steps` progress on the user doc updated by route-visit, integration-connect, platform-link, and first-approve signals; pre-check satisfied steps.
- [ ] 5.4 Lint/type-check; verify fresh-user flow end-to-end: onboarding answer → next-morning briefing traces to it → widget steps tick.

## 6. Phase F — Retention loop & instrumentation

- [ ] 6.1 Server-side analytics events at state transitions: `briefing_sent/opened`, `todo_proposed/approved/dismissed`, `proposal_expired`, `gaia_todo_completed`, `handoff_created`, `first_steps_step_done` (with channel). Dashboards for approve rate, time-to-first-approve, D1/D7/D30 morning loop.
- [ ] 6.2 Streak/heatmap derivation from `completed_at` only; briefing acknowledges broken streaks honestly.
- [ ] 6.3 `awards` collection + daily badge checks in the briefing run (`first_approve`, `first_overnight_shipment`, `gaia_100_todos`, `streak_7`, `streak_30`); notification delivery; once-only guarantee.
- [ ] 6.4 `weekly_digest` system workflow (Sunday 5pm user-tz): weekly payload, email template, dashboard archive, opt-in public Wrapped card via public-slug pattern.
- [ ] 6.5 Lint/type-check; verify events fire from dashboard AND Telegram approvals; verify badge once-only.

## 7. Documentation & cleanup

- [ ] 7.1 Update `apps/api/CLAUDE.md` (briefing run, budgets, approval rule) and `apps/web/src/features/todo/` docs for the unified model.
- [ ] 7.2 Retire `GAIA_TRACKED_LABEL` + dual-read paths after the migration window; delete dead label-based branches.
- [ ] 7.3 Final pass: `nx run-many -t lint type-check` across api, web, desktop, bots — all green; push.
