# Design — Daily Briefing & Self-Executing Todos

> **Revisions.** §5's Telegram inline-keyboard/`actions` envelope was superseded 2026-07-10 by the reply loop (no buttons; the chat agent acts via approve/dismiss/answer tools). §6 Mission Control was superseded twice: first by the Today view (2026-07-10), then 2026-08-06 by removing `/dashboard` entirely — the Today view renders at the top of `/todos`. §7's weekly digest is now a rotating template'd email edition (shuffled full cycle; see `retention-loop` spec). Goals gained an explicit backstage-only rule (`unified-todo-model` spec). The specs are authoritative over the superseded text kept below for context.

## Design stance: reuse-first, wire don't build

The building blocks already exist and are production-grade. This change builds **no new scheduler, no new execution engine, no new approval subsystem, no new notification pipeline, and no new rendering engine.** It adds thin connective tissue over existing rails and makes the existing pieces work perfectly together:

| Need | Existing rail (reused as-is) |
|---|---|
| Agent runs without a user message | `call_agent_silent` (`apps/api/app/agents/core/agent.py`) |
| Per-user daily scheduling | System workflow provisioning + `execute_workflow_by_id` ARQ path (`apps/api/app/services/system_workflows/`, `apps/api/app/workers/tasks/workflow_tasks.py`) |
| GAIA-todo execution | `schedule_execution` → `execute_tracked_todo` (`apps/api/app/services/tracked_todo_service.py`, `apps/api/app/workers/tasks/tracked_todo_tasks.py`) |
| Multi-channel delivery | Notification orchestrator + channel adapters (`apps/api/app/utils/notification/orchestrator.py`) |
| Telegram outbound | `publish_outbound_message` → RabbitMQ → bot consumer (`apps/api/app/services/outbound_delivery.py`, `libs/shared/ts/src/bots/`) |
| Working memory per todo | Canvas storage (`apps/api/app/services/todo_canvas_storage.py`) |
| LLM-emitted UI | OpenUI system (`apps/web/src/config/openui/`) |
| Timeline data | `WorkflowExecution` records, todo `completed_at`, calendar queries — all already persisted |
| Stale-work sweeps, backoff, quiet hours | Maintenance sweep patterns (`apps/api/app/workers/tasks/maintenance_sweep_tasks.py`) |

Genuinely new surface, kept deliberately small: two todo fields + three endpoints, one briefing prompt + payload schema + one Mongo collection, one email adapter + a handful of templates, one dashboard page, one widget, one onboarding question, one rate-limit feature entry, analytics events.

## 1. Unified todo model

**Fields** (on `TodoBase`, `apps/api/app/models/todo_models.py`):
- `assignee: Literal["user", "gaia"] = "user"` — replaces the `GAIA_TRACKED_LABEL` discriminator.
- `execution_status: ExecutionStatus | None` — only set when `assignee == "gaia"`: `proposed | queued | running | needs_you | done | failed | expired | dismissed`.

Existing tracked-todo fields (`vfs_path`, `scheduled_at`, `recurrence`, canvas/log content) are unchanged and now apply to any `assignee == "gaia"` todo. `completed`/`completed_at` remain the single completion source of truth for both assignees (`execution_status: done` is set alongside).

**State transitions** (server-enforced in `tracked_todo_service.py`):
- `proposed → queued`: only via the Approve action (API endpoint or Telegram callback). Enqueues execution on the existing rail.
- `proposed → dismissed`: Dismiss action; writes a memory signal (see §3).
- `proposed → expired`: curation pass when `created_at` older than `PROPOSAL_TTL_HOURS` (72). Writes the same memory signal as an implicit dismiss.
- `queued → running → done | failed | needs_you`: owned by the execution worker. `failed` carries a human-readable `error_message` and is rendered as loudly as `done` (list + briefing).
- `needs_you → running`: resolved by the user answering in the linked conversation.
- Internal-only work (nothing outward-facing) may be created directly as `queued` — the approval rule (§2) decides which entry state a new GAIA todo gets.

**Actions** (new endpoints on `apps/api/app/api/v1/endpoints/todos.py`):
- `POST /todos/{id}/approve`, `POST /todos/{id}/dismiss` (optional `reason`), `POST /todos/{id}/handoff` (user todo → `assignee: gaia`, entry state per approval rule; GAIA replies with a one-line plan in the todo's work log).

**Work log**: the canvas is rendered in the todo detail view (promoted from `TodoSidebar`-only `CanvasViewer`). No storage change.

**Migration**: backfill script sets `assignee: "gaia"` + `execution_status` (from current scheduling state) where `labels` contains `gaia-tracked`, then removes the label. One release of dual-read (`assignee == "gaia" or GAIA_TRACKED_LABEL in labels`) in the VFS projector and context injection, then the constant is retired.

## 2. The approval rule

**Rule**: work only the user and GAIA can see executes without permission; anything the outside world can observe requires an Approve tap first.

**Enforcement (v1, honest scope)**: two layers, prompt + tool-arg — not a hard tool sandbox.
1. Creation: `create_tracked_todo` (renamed contract, same tool) gains a required `requires_approval: bool` argument with an explicit classification rubric in the tool description (outward sends, posts, invites to others, purchases → `true`). `requires_approval=true` → entry state `proposed`; `false` → `queued`.
2. Execution: the silent-run prompt contract forbids outward-facing tool calls unless the todo entered via Approve; if an approved plan grows a new outward action mid-run, the todo flips to `needs_you` instead of acting.

Missing integrations never block work: the run produces the deliverable as content (message/artifact/doc) and the todo completes with a handoff choice ("connect X and I'll finish the last step, or take the content").

## 3. Fixing tracked-todo junk (creation quality gate)

The current failure — random, useless context todos — is attacked at four levels, all server-side except the last:

1. **Budgets as hard caps** (constants in `apps/api/app/constants/todos.py`): `MAX_GAIA_TODOS_IN_FLIGHT = 5` (queued/running/needs_you), `MAX_PENDING_PROPOSALS = 3`, `PROPOSAL_TTL_HOURS = 72`. Creation beyond a cap is rejected by the service; the tool returns the rejection with instructions to curate first. Scarcity forces ranking.
2. **Traceability**: `create_tracked_todo` gains a required `serves: str` argument — the goal, memory item, or explicit user request this todo advances. Stored on the todo, rendered in the proposal UI ("because you're raising a pre-seed"). Untraceable todos are the junk; making the trace mandatory kills the failure mode at creation.
3. **Curate-before-create**: the daily briefing run's first mandatory step sweeps the existing list (expire stale proposals, merge duplicates, flag stale user todos) before anything new is created. Net list growth ≈ 0 by design.
4. **Silence is signal**: every dismiss/expiry writes a structured memory note (`proposal_rejected: {kind, serves, reason?}`). The briefing prompt reads these and must not re-propose a kind rejected 3+ times. Ignoring something twice is the user's answer.

## 4. Daily briefing run

**Provisioning**: a system workflow (`system_workflow_key = "daily_briefing"`, `is_system_workflow = true`) provisioned for every user at onboarding completion + a one-time backfill; cron `0 8 * * *` in the user's timezone; execution via the standard workflow ARQ path into `call_agent_silent` with a dedicated briefing prompt.

**Run contract (in order)**:
1. **Curate** (§3.3).
2. **Look back**: compare yesterday's plan (yesterday's briefing payload) to what actually happened (todos completed, `WorkflowExecution` records, calendar). Roll slips forward or offer to take them over.
3. **Plan**: select today's you-items (top ~3), GAIA items, and proposals — within budgets; every item traceable (§3.2).
4. **Emit**: one briefing payload (§5), persisted, then delivered via the notification orchestrator to in-app + Telegram (+ email when enabled).

**One message a day is law.** The only exceptions: a time-critical `needs_you` blocker, or the user messaged first. Escalation ladder for ignored items: brief mention → one re-mention with a different angle → drop to memory. The run reads its own prior briefings + conversation history before writing; it never re-asks the same way twice. Quiet-hours and backoff behavior reuses the maintenance-sweep patterns.

**Idle honesty**: if GAIA has nothing real queued, the briefing must say so and ask whether priorities shifted — never pad.

**Gone-quiet winback**: reuses the existing inactivity cron signal. When a user has ignored 3+ briefings, the next run switches to a winback mood: safe work continues silently, and the briefing is one short, different message centered on the single most valuable pending item. No repeats.

## 5. Briefing artifact system

**Payload, never markup.** The run emits a Pydantic-validated JSON payload:

```
BriefingPayload {
  kicker: str            # "THE MORNING BRIEF"
  date: str              # user-local
  headline: str          # italic-serif display line
  lede: str
  stats: [ { value, label, delta? } ]          # the tuple row
  sections: [ { numeral, title, items: [ { text, todo_id?, kind } ] } ]
  mood: str              # keys hue + hero treatment (e.g. clear, packed, winback, weekly)
  caption: str           # one witty line
  hue: int               # 0-360, per-day rotation of the bands gradient
}
```

Stored in a new `briefings` Mongo collection `{ id, user_id, date, payload, delivered_channels, created_at }` — one per user per day (weekly digests share the collection with `kind: weekly`).

**Three renderers, one payload**:
- **Dashboard**: an OpenUI briefing component family (`apps/web/src/config/openui/`) with the editorial styling baked in — masthead (kicker + date), bands-gradient hero (`/images/wallpapers/bands_gradient_1.webp`) with CSS `hue-rotate(payload.hue)`, serif display headline, lede, stat row, Roman-numeraled sections, caption footer. Past briefs are archived and browsable.
- **Email**: a new channel adapter in the notification orchestrator (same `ExternalPlatformAdapter` shape) sending via an HTTP ESP (Resend-class, config via env; no-op with a log until keys exist — an ops precondition, not a flag). **Default-on for briefings and weekly digests** for every user with an email address, until disabled in notification settings or via the one-click unsubscribe every briefing email carries. Hand-designed templates: daily brief, weekly digest, plain notification. Templates own all design; the payload fills slots.
- **Telegram**: payload flattened to prose through the existing outbound envelope, with approve actions as inline keyboard buttons. The envelope schema (`apps/api/app/schemas/outbound.py` + TS twin) gains an optional `actions: [{label, callback}]`; the Telegram adapter renders an inline keyboard and posts callbacks to the approve/dismiss endpoints. Approving from bed must work.

Token cost is bounded by design: the model writes ~40 lines of structured text; all styling is human-authored once.

## 6. Mission Control dashboard

Replaces the widget grid at `apps/web/src/app/[locale]/(main)/dashboard/page.tsx`:
- **Header**: latest briefing rendered via the OpenUI briefing component (collapsible to its headline).
- **Timeline (left)**: today's items interleaved chronologically — todos (both assignees, with state glyphs), calendar events, completed `WorkflowExecution` entries. Served by one new aggregation endpoint (`GET /dashboard/today`); live updates ride the existing notification WebSocket.
- **Action rail (right)**: *Next up* (top unfinished user todo), *Waiting on you* (proposed + needs_you todos with inline Approve/Dismiss and one-glance result preview), *Done today* (GAIA n · You n).
- **Heatmap**: GitHub-style contribution grid; one aggregation endpoint over todo `completed_at` (both assignees). Green requires real completed work (§7); gray otherwise.

## 7. Retention loop

- **Honest streak**: a day is green iff ≥1 todo was actually completed that day by either party. Heartbeat/cron activity (triage sweeps, syncs) never counts. Nothing done → gray, streak broken — honestly. Because GAIA's completed work counts, healthy weeks stay green without guilt mechanics; dishonest padding is structurally impossible because the source is `completed_at` records only.
- **Badges**: rare, real-event-only (`first_approve`, `first_overnight_shipment`, `gaia_100_todos`, `streak_7`, `streak_30`). New `awards` collection; checks run inside the daily briefing run (cheap, once a day); delivery via the existing notification orchestrator. No badge cabinet page in v1 — the notification and the weekly digest mention are the surface.
- **Weekly zoom-out**: a `weekly_digest` system workflow (Sunday 5pm user-local) emitting a `kind: weekly` payload — week's completed work, hours-saved estimate, streak, heatmap snippet — rendered by the weekly email template + dashboard archive, with a shareable public Wrapped card (public-slug pattern already used by community workflows).
- **Instrumentation (PostHog, day one)**: `briefing_sent`, `briefing_opened`, `todo_proposed`, `todo_approved`, `todo_dismissed`, `proposal_expired`, `gaia_todo_completed`, `handoff_created`, `first_steps_step_done`. North star: **approve rate** = approved / (approved + dismissed + expired). Activation event: first `todo_approved`. Funnels: time-to-first-approve, D1/D7/D30 presence in the morning loop (briefing_opened or any approve within 24h of briefing_sent).
- **No global leaderboard** (rewards volume, corrupts approve rate, privacy). Shareable-not-comparable instead (Wrapped).

## 8. Onboarding goal seed

- One added question on **all** paths (including Gmail): "What are you working on right now?" — free text, stored to the memory system (not just the user doc) so every future agent run sees it; `onboarding.focus` handling is unified into the same write (reviving the dormant field).
- Cold-start guarantee: the first daily briefing (provisioned at onboarding completion, first fire next morning) must contain at least one real proposed todo traceable to the stated goal. The intelligence pipeline already seeds first todos; the briefing run picks them up naturally.

## 9. First-steps nudge

A small persistent widget, bottom-right of all main app pages (mounted in the `(main)` layout): an ordered activation checklist —
1. Explore the workflows page
2. Connect your first non-Gmail integration
3. Link Telegram so briefings reach you
4. Meet Mission Control (visit `/dashboard`)
5. Approve your first GAIA todo

Progress state lives on the user doc (`first_steps: {step_key: completed_at}`), updated by existing signals (integration connect, platform link, route visit, first approve) — no polling. Widget is collapsible, dismissible per-step and entirely, and unmounts permanently once all steps complete. Each step deep-links to its surface. Steps completed before the widget ever rendered are pre-checked (e.g. Telegram already linked).

## 10. Free tier & conversion

The hook is free; the labor is metered. Briefing, weekly digest, Mission Control, heatmap/streak, proposals, and the todo list are unlimited on free. GAIA todo **executions** meter through the existing tiered rate-limit system (`apps/api/app/config/rate_limits.py`) via a new `gaia_todo_executions` feature (**free: 5/month launch default** — monthly, not daily, so every approve is felt; pro: generous; tuned by approve-rate + conversion data). GAIA proposes at full quality regardless of tier, with previews visible — so the at-quota Approve tap becomes the conversion surface: it opens the upgrade flow pitching the *specific staged work* ("12 investor DMs drafted and ready — upgrade to send"), reusing the existing rate-limit upgrade-CTA pattern. The pitched proposal is exempt from TTL expiry for up to 7 days. Conversion events (`upgrade_prompt_shown`, `upgrade_from_approve`) join the analytics set.

## 11. Design mandate

Every surface in this change follows GAIA's design system (`DESIGN.md`) at the Dia-artifacts quality bar — Notion/Apple/ElevenLabs/Vercel-class cleanliness. Briefing display typography: **Aeonik** (already in the codebase at `apps/web/src/app/fonts/aeonik.ts`) + **Playfair Display** (added via `next/font`) as the serif display companion, alongside existing families (Inter, PP Editorial New, Anonymous Pro) in their established roles. The todos sidebar + detail view are redesigned, not patched (see `unified-todo-model`). Build is preceded by a **design-exploration phase**: multiple full candidates each for the briefing card, the email templates, the todos sidebar, and Mission Control layout polish — user selects before implementation. The Dia reference (editorial masthead, stat tuples, numbered sections, witty captions, curated art direction) is the north star; the bands-gradient wallpaper with per-day hue rotation is the hero identity.

## 12. Existing-user rollout

No cold starts. When briefings are provisioned for the existing base: (1) every user receives a one-time announcement on all connected channels (in-app + linked platforms + email) introducing daily briefings; (2) before a user's first briefing, the run derives goals from memory, integrations, and todo history — if sufficient, the first briefing proceeds and states its inference with a correct-me line; (3) if insufficient, the announcement asks a 2–3 question bootstrap interview (what are you working on, what should GAIA take over, preferred hour) — replies write to memory and briefings begin the morning after, with a 3-day triage-derived fallback that repeats the questions as its closing line.

## 13. Rollout

**No feature flags anywhere in this change.** Sequencing and verification replace flags:

1. Todo model + migration ship first (dual-read window is a data-migration mechanism, not a flag).
2. Founder-persona end-to-end verification (tasks Phase G) gates the all-users provisioning backfill: real account, real memories, goals "raise a pre-seed / ship / post on socials" — the generated briefing, proposals, approve round-trip, and channel delivery are inspected end to end and iterated until they meet the bar.
3. Existing-user announcement + backfill run once verification passes (§12).
4. Email requires ESP keys + sending domain (SPF/DKIM) in prod — an ops precondition satisfied before the backfill so default-on email works from day one. Sender: `brief@heygaia.io`. All credentials (ESP, test Telegram bot token, PostHog) are read from Infisical / existing `.env` files — read-only, no secret writes.
5. Founder E2E (Phase G) is pre-authorized: snapshot the founder account's memories + todos (`aryanranderiya1478@gmail.com`, via `ssh gaia-prod`) into a dev seed — Mongo docs and Chroma embeddings both.
5. Post-login redirect stays `/c`; moving it to `/dashboard` is a deferred decision on approve-rate data.
