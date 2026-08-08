## 1. Phase A — Unified todo model (foundation; everything else depends on it)

- [x] 1.1 Add `assignee: Literal["user","gaia"] = "user"` and `execution_status: ExecutionStatus | None` to `TodoBase` in `apps/api/app/models/todo_models.py`; define the `ExecutionStatus` enum (`proposed|queued|running|needs_you|done|failed|expired|dismissed`).
- [x] 1.2 Add constants to `apps/api/app/constants/todos.py`: `MAX_GAIA_TODOS_IN_FLIGHT = 5`, `MAX_PENDING_PROPOSALS = 3`, `PROPOSAL_TTL_HOURS = 72`. Mark `GAIA_TRACKED_LABEL` deprecated (removed in 1.10).
- [x] 1.3 Server-enforce transitions + budgets + `serves` traceability in `apps/api/app/services/tracked_todo_service.py`: creation rejects over-budget or `serves`-less GAIA todos; only Approve moves `proposed → queued` (enqueue via existing `schedule_execution`); only the worker sets `running/done/failed/needs_you`; `failed` requires a cause.
- [x] 1.4 Update `apps/api/app/agents/tools/tracked_todo_tools.py`: required `serves: str` and `requires_approval: bool` args with the outward-visibility rubric in the tool description; entry state from `requires_approval`; tool errors surface budget rejections with the pending items listed.
- [x] 1.5 Add endpoints in `apps/api/app/api/v1/endpoints/todos.py`: `POST /todos/{id}/approve`, `POST /todos/{id}/dismiss` (optional reason), `POST /todos/{id}/handoff`. Dismiss/expiry write the `proposal_rejected` memory signal.
- [x] 1.6 Wire the memory-signal read into the briefing/creation prompts: kinds rejected/expired 3+ times are not re-proposed (prompt section + a service-side recent-rejections summary injected into the run context).
- [x] 1.7 Silent classification of new user todos (offer / prep / stay-silent) as a post-create background step; offer renders as a dismissible affordance on the todo only — no notification.
- [x] 1.8 Execution-side approval contract: background-run prompt forbids outward actions on todos not entered via Approve; mid-run new outward action flips todo to `needs_you` with a linked conversation. Missing-integration handoff: complete with content + connect-or-take-content choice.
- [x] 1.9 Migration script: backfill `assignee`/`execution_status` from `gaia-tracked` labels, remove the label; dual-read in VFS projector (`tracked-todos-vfs` delta), context injection (`message_helpers.py`), and list filters for one release.
- [x] 1.10 Tier metering: add `gaia_todo_executions` to `apps/api/app/config/rate_limits.py` (free: `month=5`, no daily cap; pro: generous); enforce at the Approve/queue transition; at-quota Approve returns the upgrade state instead of a silent failure; pitched proposal exempt from TTL for 7 days; emit `upgrade_prompt_shown` / `upgrade_from_approve`.
- [x] 1.11 `nx lint api && nx type-check api`; verify create → propose → approve → run → done/failed round-trip and the at-quota upgrade path in dev.

## 2. Phase B — Design exploration (gates all frontend build)

- [x] 2.1 Study references: the Dia artifacts thread visuals, `DESIGN.md`, existing bands-gradient usage on landing; add Playfair Display via `next/font` alongside Aeonik (`apps/web/src/app/fonts/`).
- [x] 2.2 Produce multiple full design candidates (real comps, not wireframes) for: (a) the briefing card (masthead, gradient hero + hue rotation, stat row, sections, caption), (b) the daily + weekly email templates, (c) the todos sidebar + todo detail with assignee/state glyphs, proposal treatment, work-log document view, (d) Mission Control layout (timeline + action rail + heatmap).
- [x] 2.3 User selects one candidate per surface (iterate until selected); lock a briefing-surface style guide (type scale, hue table per mood, spacing, glyph set) that Phases C–E implement verbatim.

## 3. Phase C — Daily briefing run

- [x] 3.1 `BriefingPayload` Pydantic model + `briefings` collection with indexes (`user_id + date`, `kind`).
- [x] 3.2 Briefing prompt (new file under `apps/api/app/agents/prompts/`): curate-first contract, lookback vs yesterday's payload, budgets, traceability, one-message law, escalation ladder, idle honesty, winback mood, payload-only output.
- [x] 3.3 `daily_briefing` system workflow definition in `apps/api/app/services/system_workflows/`: provision at onboarding completion; cron `0 8 * * *` user-tz; execution through the standard workflow path into `call_agent_silent`. (All-users backfill happens in Phase G after E2E verification passes.)
- [x] 3.4 Run pipeline: curation service step (expire proposals, memory signals) runs deterministically before the agent turn; payload validated + persisted before delivery via the notification orchestrator.
- [x] 3.5 Winback behavior keyed off consecutive unacknowledged briefings (derive from `briefing_opened`/approve events); cadence backoff per maintenance-sweep pattern.
- [x] 3.6 Lint/type-check; verify one full morning cycle in dev (seeded todos + goal memory → briefing payload + Telegram delivery).

## 4. Phase D — Briefing artifacts & channels

- [x] 4.1 OpenUI briefing component family (`apps/web/src/config/openui/` + components) implementing the selected Phase B design: masthead, bands-gradient hero with `hue-rotate`, Aeonik/Playfair display type, stat row, numbered sections, caption. Archive view of past briefs.
- [ ] 4.2 ~~Extend outbound envelope with optional `actions`~~ — **SUPERSEDED 2026-07-10** (was checked but never implemented — no `actions` field exists in either envelope twin). Decision: no buttons on chat platforms; natural-language replies are the cross-platform interface.
- [ ] 4.3 ~~Telegram inline keyboard + callback handler~~ — **SUPERSEDED 2026-07-10** (was checked but never implemented — no inline-keyboard/callback code exists in any bot). Replaced by the reply loop: proposal/briefing texts invite a reply; the chat agent acts via `approve_todo` / `dismiss_todo` / `answer_todo` (todo-context now carries `execution_status` + `blocker_question`).
- [x] 4.4 Email channel adapter in `apps/api/app/utils/notification/channels/`: HTTP ESP behind env config (no-op with log until keys — ops precondition, not a flag); **default-enabled for briefing/digest kinds**; one-click unsubscribe link mapping to the channel preference; register in orchestrator; add to channel preferences + `NotificationSettings.tsx`.
- [x] 4.5 Email templates (daily brief, weekly digest, plain notification) implementing the selected Phase B design; template selection by `kind`.
- [x] 4.6 Lint/type-check across api, web, bots; verify: same payload renders on dashboard, Telegram (with working Approve), and email preview; unsubscribe round-trip works.

## 5. Phase E — Mission Control dashboard + todos surface redesign

- [x] 5.1 `GET /dashboard/today` aggregation endpoint (todos + calendar + `WorkflowExecution`, chronological) and heatmap aggregation endpoint over `completed_at`.
- [x] 5.2 Rebuild `apps/web/src/app/[locale]/(main)/dashboard/page.tsx` as Mission Control per the selected Phase B design — **REVISED 2026-07-10: Mission Control replaced by the Today view before rollout** (see Phase H and the updated `mission-control-dashboard` spec).
- [x] 5.3 Todos sidebar + detail redesign per the selected Phase B design: assignee/state glyphs (no label chips), proposal treatment with inline Approve/Dismiss + one-glance previews, work log as a first-class document view (replaces sidebar-only `CanvasViewer` placement), quiet GAIA-offer affordances.
- [x] 5.4 Live updates over the existing notification WebSocket — **corrected 2026-07-10: was checked but not implemented; now real** via `todo.execution_status` broadcasts from every lifecycle transition + client invalidation.
- [x] 5.5 Lint/type-check; verify timeline interleaving, rail approve round-trip, heatmap gray-day honesty, and the redesigned sidebar states in dev. **Timeline/rail/heatmap superseded by Phase H.**

## 6. Phase F — Onboarding seed, first-steps nudge & retention loop

- [x] 6.1 Add "What are you working on right now?" to onboarding on all paths (`apps/web/src/features/onboarding/`, `OnboardingRequest`, `onboarding_service.py`); write to memory; unify with `onboarding.focus`.
- [x] 6.2 First-briefing guarantee: briefing prompt requires ≥1 item tracing to the stated goal; when skipped, derive from triage and close with the goal question.
- [x] 6.3 First-steps widget in the `(main)` layout: 5-step checklist, deep links, collapse/dismiss, permanent unmount on completion; `first_steps` progress on the user doc updated by route-visit, integration-connect, platform-link, and first-approve signals; pre-check satisfied steps.
- [x] 6.4 Server-side analytics events at state transitions: `briefing_sent/opened`, `todo_proposed/approved/dismissed`, `proposal_expired`, `gaia_todo_completed`, `handoff_created`, `first_steps_step_done`, `upgrade_prompt_shown`, `upgrade_from_approve` (with channel). Dashboards for approve rate, time-to-first-approve, D1/D7/D30 morning loop, at-quota conversion.
- [x] 6.5 Streak/heatmap derivation from `completed_at` only; briefing acknowledges broken streaks honestly.
- [x] 6.6 `awards` collection + daily badge checks in the briefing run (`first_approve`, `first_overnight_shipment`, `gaia_100_todos`, `streak_7`, `streak_30`); notification delivery; once-only guarantee.
- [x] 6.7 `weekly_digest` system workflow (Sunday 5pm user-tz): weekly payload, email template, dashboard archive, opt-in public Wrapped card via public-slug pattern.
- [x] 6.8 Lint/type-check; verify events fire from dashboard AND Telegram approvals; verify badge once-only; verify fresh-user flow end-to-end (onboarding answer → next-morning briefing traces to it → widget steps tick).

## 7. Phase G — Founder-persona end-to-end verification (gates all-users rollout)

- [x] 7.0 Test setup (pre-authorized): snapshot the founder account's memories + todos (`aryanranderiya1478@gmail.com` via `ssh gaia-prod` over Tailscale — Mongo docs AND Chroma embeddings) into a dev seed; locate the test Telegram bot token in the existing `.env` files; pull ESP/PostHog/other credentials from Infisical (read-only, no writes); configure `brief@heygaia.io` as sender.
- [x] 7.1 Run the full loop against the seeded founder account with goals "raise a pre-seed round / ship / post on socials": provision the briefing workflow, fire it via execute-now, and capture the actual generated briefing. Simulate multi-day behaviors (72h expiry, 3-ignore winback, streak break, lookback) with backdated fixture records.
- [x] 7.2 Inspect and iterate until the bar is met: proposals trace to the real goals (investor research/DMs, shipping, socials — not generic inbox items), budgets hold, curation cleans, lookback reflects the prior day, idle/winback behaviors trigger correctly when simulated.
- [ ] 7.3 Verify every channel end to end with the real account: dashboard Today view, Telegram **reply-based** approve/answer (text → agent tool → execution), email render + unsubscribe, streak updates in the briefing, at-quota upgrade path (simulated free tier). **Re-opened 2026-07-10: the prior check claimed Telegram inline-Approve verification, which cannot have run (that UI never existed); must be re-run against the Today view + reply loop.**
- [x] 7.4 Only after sign-off: existing-user rollout — one-time all-channel announcement, memory-derivation vs bootstrap-interview branch per user, then the all-users provisioning backfill (design §12).

## 7b. Phase H — Today view redesign (2026-07-10, branch `feat/today-dashboard`)

- [x] H.1 `blocker_question` on `TodoBase`; guarded lifecycle entry points `block()` (queued/running → needs_you) and `answer()` (the only needs_you → queued path; Q&A appended to the notes facet, run re-enqueued). Honesty-gate message now lands in `blocker_question` instead of being wiped.
- [x] H.2 `POST /todos/{id}/answer` endpoint + `block_todo` / `answer_todo` agent tools; background-run prompt and todo prompts updated (block instead of guessing; lifecycle tools explained).
- [x] H.3 `todo.execution_status` WebSocket broadcasts from every lifecycle transition (approve/dismiss/handoff/answer/mark_execution_status; complete path routed through the lifecycle).
- [x] H.4 `GET /dashboard/today` rewritten to the sectioned Today payload (headline w/ noon flip, subline, runs quota via new `tiered_limiter.get_usage`, five sections); heatmap endpoint deleted (activity.py streak math retained for the briefing).
- [x] H.5 Frontend Today view: header + five row sections, inline approve/skip/run/answer/checkbox, ws invalidation + focus refetch + in-flight-only poll; Mission Control components (TodayTimeline, ActionRail, ContributionHeatmap) deleted.
- [x] H.6 Tracked-todo tool audit (16 findings fixed): dead `gaia-tracked` queries, references-only update no-op, unguarded block path, false docstrings, SKILL.md drift (`initial_canvas`, missing required args, facet model).
- [x] H.7 Badges/awards decision — RESOLVED 2026-08-07 by the calm-surface direction: keep the v1 badge set exactly as built (5 real-event badges, once-only, notification + digest mention, no cabinet); no further gamification expansion. Aligns with the no-overwhelm principle.

## 7c. Phase I — Calm-surface consolidation (2026-08-06, in-PR)

Decisions: the product has exactly three user-facing surfaces (chat, todos, briefing documents); briefings are documents delivered by email/chat, not a dashboard; nudges are completion-triggered only.

- [x] I.1 Remove the standalone `/dashboard` route (redirect to `/todos`); render the Today view as the top of `/todos`; absorb/delete the dashboard feature's row components into the todos feature — no parallel implementations. Row click targets use the stretched-button overlay pattern (real semantics, keyboard-native).
- [x] I.2 Batch simultaneous `needs_you` blockers into one combined proactive message ("3 things need your call") — never separate pushes.
- [x] I.3 Completion-report nudge: an approved todo's completion message on the priority chat channel may carry at most one contextual next-step suggestion; no clock-based engagement pings; dismissed/ignored suggestions are not repeated (`nudge_shown` stamp).
- [x] I.4 Edition library: all 20 founder-explorer families vendored (569 combos) and rendered through the production Chromium pipeline; shuffled-cycle rotation generalized per kind so DAILY and WEEKLY both rotate the pool with independent persisted state. Real-data audit (anti-collision payload) verified every content slot is payload-derived; `{weekly, dayline, flightplan, metromap}` excluded with documented reasons.
- [x] I.5 Cut the goal↔workflow linkage (`find_goal_linked_workflows`, goal-sourced workflow reads in briefing context); goals stay backstage per the revised `unified-todo-model` spec — no lane UI.
- [x] I.6 Briefing rhythm crons (`daily_briefing`/`weekly_digest`/`overnight_work`) excluded from user workflow lists at the repository query; other system workflows (inbox triage, meeting prep) stay listed and toggleable — supersedes daily-briefing-run's "manage like any workflow" for the briefing crons specifically.
- [x] I.7 Persona thrash harness (`apps/api/scripts/persona_harness/`, dev-only): 11-persona matrix + founder-week capstone, driven through real HTTP surfaces with Mongo used only for fixtures/backdating/assertions; verbatim timeline reports per run. Verified live on the Nous lane: 10/11 personas + the capstone pass. `blocked-everything` is left RED on purpose — it is the clean repro for the executor's `block_todo` reliability gap (see I.11).
- [x] I.9 Urgent-signal alert: strict time-criticality gate in the triage/calendar trigger prompts + `urgent_alert_sent` analytics event + rejection-strike memory write for ignored kinds. NO numeric cap — urgency is the gate (see daily-briefing-run spec).
- [ ] I.11 Executor `block_todo` reliability: under the real-LLM lane the executor sometimes narrates a successful block ("awaiting your decision") without the tool call landing — the todo stays `queued`, no notification. Mechanism itself verified correct when the tool fires. Investigate tool retrieval for terse imperative tasks vs. the model substituting a canvas write. Repro: `uv run python -m scripts.persona_harness --persona blocked-everything`.
- [ ] I.12 Briefing runs skip silently for bootstrap-pending/dormant users (200, no new edition). Correct by design, but the skip reason is invisible to callers — surface it in the dev-trigger response so harnesses and operators can tell "skipped" from "generated" without diffing Mongo.
- [x] I.10 Wrapped card — REMOVED 2026-08-07 (product decision: no public stats surface, ever). 6.7's Wrapped clause is void; the no-public-URL guarantee stays.
- [ ] I.8 `nx run-many -t lint type-check` across api, web, bots — green.

Deferred to follow-up issues (not this PR): Gmail bulk-action tool (single scoped call for inbox cleanup), signal→todo wiring for reply-driven loops (scheduling negotiation), per-integration proactive workflow templates (Linear/Slack/Notion).

## 8. Documentation & cleanup

- [x] 8.1 Update `apps/api/CLAUDE.md` (briefing run, budgets, approval rule, tier metering) and `apps/web/src/features/todo/` docs for the unified model.
- [x] 8.2 Retire `GAIA_TRACKED_LABEL` + dual-read paths after the migration window; delete dead label-based branches and the removed widget-grid code.
- [x] 8.3 Final pass: `nx run-many -t lint type-check` across api, web, desktop, bots — all green; push.
