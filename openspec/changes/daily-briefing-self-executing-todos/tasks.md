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
- [ ] 1.10 Tier metering: add `gaia_todo_executions` to `apps/api/app/config/rate_limits.py` (free: `month=5`, no daily cap; pro: generous); enforce at the Approve/queue transition; at-quota Approve returns the upgrade state instead of a silent failure; pitched proposal exempt from TTL for 7 days; emit `upgrade_prompt_shown` / `upgrade_from_approve`.
- [ ] 1.11 `nx lint api && nx type-check api`; verify create → propose → approve → run → done/failed round-trip and the at-quota upgrade path in dev.

## 2. Phase B — Design exploration (gates all frontend build)

- [ ] 2.1 Study references: the Dia artifacts thread visuals, `DESIGN.md`, existing bands-gradient usage on landing; add Playfair Display via `next/font` alongside Aeonik (`apps/web/src/app/fonts/`).
- [ ] 2.2 Produce multiple full design candidates (real comps, not wireframes) for: (a) the briefing card (masthead, gradient hero + hue rotation, stat row, sections, caption), (b) the daily + weekly email templates, (c) the todos sidebar + todo detail with assignee/state glyphs, proposal treatment, work-log document view, (d) Mission Control layout (timeline + action rail + heatmap).
- [ ] 2.3 User selects one candidate per surface (iterate until selected); lock a briefing-surface style guide (type scale, hue table per mood, spacing, glyph set) that Phases C–E implement verbatim.

## 3. Phase C — Daily briefing run

- [ ] 3.1 `BriefingPayload` Pydantic model + `briefings` collection with indexes (`user_id + date`, `kind`).
- [ ] 3.2 Briefing prompt (new file under `apps/api/app/agents/prompts/`): curate-first contract, lookback vs yesterday's payload, budgets, traceability, one-message law, escalation ladder, idle honesty, winback mood, payload-only output.
- [ ] 3.3 `daily_briefing` system workflow definition in `apps/api/app/services/system_workflows/`: provision at onboarding completion; cron `0 8 * * *` user-tz; execution through the standard workflow path into `call_agent_silent`. (All-users backfill happens in Phase G after E2E verification passes.)
- [ ] 3.4 Run pipeline: curation service step (expire proposals, memory signals) runs deterministically before the agent turn; payload validated + persisted before delivery via the notification orchestrator.
- [ ] 3.5 Winback behavior keyed off consecutive unacknowledged briefings (derive from `briefing_opened`/approve events); cadence backoff per maintenance-sweep pattern.
- [ ] 3.6 Lint/type-check; verify one full morning cycle in dev (seeded todos + goal memory → briefing payload + Telegram delivery).

## 4. Phase D — Briefing artifacts & channels

- [ ] 4.1 OpenUI briefing component family (`apps/web/src/config/openui/` + components) implementing the selected Phase B design: masthead, bands-gradient hero with `hue-rotate`, Aeonik/Playfair display type, stat row, numbered sections, caption. Archive view of past briefs.
- [ ] 4.2 Extend outbound envelope with optional `actions: [{label, callback_data}]` in `apps/api/app/schemas/outbound.py` and the TS twin in `libs/shared/ts/src/bots/`; keep byte-compatible when absent.
- [ ] 4.3 Telegram adapter (`apps/bots/telegram/src/adapter.ts`): render actions as inline keyboard; callback handler posts to approve/dismiss endpoints with platform-link identity; edit message after action.
- [ ] 4.4 Email channel adapter in `apps/api/app/utils/notification/channels/`: HTTP ESP behind env config (no-op with log until keys — ops precondition, not a flag); **default-enabled for briefing/digest kinds**; one-click unsubscribe link mapping to the channel preference; register in orchestrator; add to channel preferences + `NotificationSettings.tsx`.
- [ ] 4.5 Email templates (daily brief, weekly digest, plain notification) implementing the selected Phase B design; template selection by `kind`.
- [ ] 4.6 Lint/type-check across api, web, bots; verify: same payload renders on dashboard, Telegram (with working Approve), and email preview; unsubscribe round-trip works.

## 5. Phase E — Mission Control dashboard + todos surface redesign

- [ ] 5.1 `GET /dashboard/today` aggregation endpoint (todos + calendar + `WorkflowExecution`, chronological) and heatmap aggregation endpoint over `completed_at`.
- [ ] 5.2 Rebuild `apps/web/src/app/[locale]/(main)/dashboard/page.tsx` as Mission Control per the selected Phase B design — direct replacement, no flag; delete the old widget-grid code from this page: briefing header (OpenUI component, collapsible), timeline left, action rail right (Next up / Waiting on you with inline Approve + preview / Done today GAIA n · You n), heatmap.
- [ ] 5.3 Todos sidebar + detail redesign per the selected Phase B design: assignee/state glyphs (no label chips), proposal treatment with inline Approve/Dismiss + one-glance previews, work log as a first-class document view (replaces sidebar-only `CanvasViewer` placement), quiet GAIA-offer affordances.
- [ ] 5.4 Live updates over the existing notification WebSocket (todo state changes, executions).
- [ ] 5.5 Lint/type-check; verify timeline interleaving, rail approve round-trip, heatmap gray-day honesty, and the redesigned sidebar states in dev.

## 6. Phase F — Onboarding seed, first-steps nudge & retention loop

- [ ] 6.1 Add "What are you working on right now?" to onboarding on all paths (`apps/web/src/features/onboarding/`, `OnboardingRequest`, `onboarding_service.py`); write to memory; unify with `onboarding.focus`.
- [ ] 6.2 First-briefing guarantee: briefing prompt requires ≥1 item tracing to the stated goal; when skipped, derive from triage and close with the goal question.
- [ ] 6.3 First-steps widget in the `(main)` layout: 5-step checklist, deep links, collapse/dismiss, permanent unmount on completion; `first_steps` progress on the user doc updated by route-visit, integration-connect, platform-link, and first-approve signals; pre-check satisfied steps.
- [ ] 6.4 Server-side analytics events at state transitions: `briefing_sent/opened`, `todo_proposed/approved/dismissed`, `proposal_expired`, `gaia_todo_completed`, `handoff_created`, `first_steps_step_done`, `upgrade_prompt_shown`, `upgrade_from_approve` (with channel). Dashboards for approve rate, time-to-first-approve, D1/D7/D30 morning loop, at-quota conversion.
- [ ] 6.5 Streak/heatmap derivation from `completed_at` only; briefing acknowledges broken streaks honestly.
- [ ] 6.6 `awards` collection + daily badge checks in the briefing run (`first_approve`, `first_overnight_shipment`, `gaia_100_todos`, `streak_7`, `streak_30`); notification delivery; once-only guarantee.
- [ ] 6.7 `weekly_digest` system workflow (Sunday 5pm user-tz): weekly payload, email template, dashboard archive, opt-in public Wrapped card via public-slug pattern.
- [ ] 6.8 Lint/type-check; verify events fire from dashboard AND Telegram approvals; verify badge once-only; verify fresh-user flow end-to-end (onboarding answer → next-morning briefing traces to it → widget steps tick).

## 7. Phase G — Founder-persona end-to-end verification (gates all-users rollout)

- [ ] 7.0 Test setup (pre-authorized): snapshot the founder account's memories + todos (`aryanranderiya1478@gmail.com` via `ssh gaia-prod` over Tailscale — Mongo docs AND Chroma embeddings) into a dev seed; locate the test Telegram bot token in the existing `.env` files; pull ESP/PostHog/other credentials from Infisical (read-only, no writes); configure `brief@heygaia.io` as sender.
- [ ] 7.1 Run the full loop against the seeded founder account with goals "raise a pre-seed round / ship / post on socials": provision the briefing workflow, fire it via execute-now, and capture the actual generated briefing. Simulate multi-day behaviors (72h expiry, 3-ignore winback, streak break, lookback) with backdated fixture records.
- [ ] 7.2 Inspect and iterate until the bar is met: proposals trace to the real goals (investor research/DMs, shipping, socials — not generic inbox items), budgets hold, curation cleans, lookback reflects the prior day, idle/winback behaviors trigger correctly when simulated.
- [ ] 7.3 Verify every channel end to end with the real account: dashboard card, Telegram inline Approve (tap → execution → message edit), email render + unsubscribe, heatmap/streak updates, at-quota upgrade path (simulated free tier).
- [ ] 7.4 Only after sign-off: existing-user rollout — one-time all-channel announcement, memory-derivation vs bootstrap-interview branch per user, then the all-users provisioning backfill (design §12).

## 8. Documentation & cleanup

- [ ] 8.1 Update `apps/api/CLAUDE.md` (briefing run, budgets, approval rule, tier metering) and `apps/web/src/features/todo/` docs for the unified model.
- [ ] 8.2 Retire `GAIA_TRACKED_LABEL` + dual-read paths after the migration window; delete dead label-based branches and the removed widget-grid code.
- [ ] 8.3 Final pass: `nx run-many -t lint type-check` across api, web, desktop, bots — all green; push.
