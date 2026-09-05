> **Revisions.** 2026-07-10: Mission Control (timeline + action rail + heatmap) was replaced by the Today view; Telegram inline Approve buttons were dropped for the natural-language reply loop (no buttons on any chat platform). 2026-08-06/07: the standalone `/dashboard` route is removed entirely — the Today view tops `/todos`; the product has exactly three user-facing surfaces (chat, todos, briefing documents); weekly digests became rotating template'd email editions (shuffled full-cycle, no repeats until exhaustion); goals are backstage data only (no lane UI, no goal-linked workflows); nudges are completion-triggered only; simultaneous blockers batch into one message. The capability specs and `tasks.md` Phase I are authoritative over any conflicting text below.

## Why

GAIA has production-grade proactive infrastructure — self-executing tracked todos (`call_agent_silent` + ARQ), a full workflows engine, a multi-channel notification orchestrator, and platform delivery to Telegram/Discord/Slack/WhatsApp — but no conductor on top of it. Nothing pulls these into one daily moment, so the product remains pull-model: the user must open it, know what to ask, and babysit the answer. Pull-model AI tools do not retain.

Three concrete failures this change fixes:

1. **Tracked ("context") todos are broken in practice.** The agent creates random, useless tracked todos: creation is gated only by prompt guidance in `todo_prompts.py`, there are no server-side caps, no expiry, no quality gate tracing a todo back to something the user actually cares about, and no feedback loop when the user ignores them. The user-todo/tracked-todo split is a label hack (`gaia-tracked` in `labels`) with the canvas buried in a sidebar viewer — users cannot see who is doing what, hand work over, or tell a note-to-self apart from work GAIA is running.
2. **The daily briefing is aspirational.** The dashboard renders a count line, not reasoning. Onboarding captures intent (`onboarding.focus`) and then never feeds it to the agent again. There is no per-day record of what moved, so "based on your progress" has nothing to stand on.
3. **No activation path.** After onboarding there is nothing that walks a user to the moments that make them stay (first integration beyond Gmail, Telegram link, first Approve tap).

The retention thesis: a todo list where half the todos do themselves and the user just taps Approve — proven every morning by a briefing that shows what GAIA did overnight, kept honest by hard anti-spam budgets and an honest streak.

## What Changes

- **Unify the todo model.** Every todo gets an `assignee` (`user` | `gaia`) replacing the `gaia-tracked` label hack, plus an execution lifecycle for GAIA todos: `proposed → (Approve) → queued → running → done | needs_you | failed | expired`. Approve/Dismiss become first-class todo actions; "Hand to GAIA" converts a user todo; the canvas is promoted from sidebar viewer to the todo's visible work log.
- **Fix tracked-todo junk at the root.** Server-side budgets (max GAIA todos in flight, max pending proposals), 72h proposal expiry, a creation quality gate (every GAIA todo must cite the goal/memory/user-request it serves), and dismiss/ignore signals written to memory so rejected proposal types stop recurring.
- **Approval rule.** Work only the user and GAIA can see (research, drafts, triage, prep) executes without permission. Anything the outside world sees (send email/DM, post, invite others, spend) requires an Approve tap. Missing integrations never block work — GAIA produces the deliverable as content and offers connect-or-take-content at handoff.
- **Daily briefing run.** A system workflow provisioned for every user (cron ~8am user-local) that curates the todo list first (expire, merge, flag), compares yesterday's plan to what actually happened, creates/proposes today's todos within budget, and emits a structured briefing payload. One briefing message per day is law.
- **Briefing artifact system.** The agent emits a small JSON payload (kicker, headline, lede, stat tuples, numbered sections, mood, caption) — never markup. Three renderers: hand-designed email templates (email is a new notification channel adapter), an OpenUI briefing component family on the dashboard (briefs archived and browsable), and Telegram prose with working inline Approve buttons. Visual identity: editorial masthead over the bands-gradient wallpaper with per-day hue rotation.
- **Mission Control dashboard.** Replaces the `/dashboard` widget grid: briefing header, day timeline (todos + calendar + workflow executions interleaved), action rail (Next up / Waiting on you with inline Approve / Done today: GAIA n · You n), and a GitHub-style contribution heatmap.
- **Retention loop.** Honest streak (green = ≥1 todo actually completed that day by either party; heartbeat work never counts; idle day = gray, streak breaks). Rare milestone badges. Weekly zoom-out email with a shareable Wrapped card. Full instrumentation from day one: approve rate (north star), briefing open/reply rate, time-to-first-approve, D1/D7/D30 morning-loop retention. No global leaderboard.
- **Onboarding goal seed.** One added question — "what are you working on right now?" — asked on every path (including Gmail), persisted to memory, and required to produce real proposed todos in the user's first morning briefing.
- **First-steps nudge.** A persistent bottom-right widget across app pages walking new users through activation: explore workflows, connect a first non-Gmail integration, link Telegram for notifications, meet Mission Control, approve their first GAIA todo. Dismissible, progress-tracked, disappears when complete.
- **Free tier built for conversion.** The hook (briefing, dashboard, proposals, streak) is free and unlimited; GAIA's *execution* is metered through the existing tiered rate-limit system. At quota, the Approve tap becomes the upgrade surface — pitching the specific staged work GAIA has ready, not a generic paywall.
- **Email briefings on by default.** Daily briefings and weekly digests deliver to email for every user until disabled in notification settings or via one-click unsubscribe.
- **Existing users are announced to and interviewed.** One-time all-channel announcement introducing briefings; goals derived from memory where possible (stated with a correct-me line), and a short bootstrap interview where not — no user cold-starts into a generic briefing.
- **Design as a first-class deliverable.** Briefing surfaces, email templates, the todos sidebar, and Mission Control are designed to the Dia-artifacts bar (Notion/Apple/ElevenLabs/Vercel cleanliness) within GAIA's design system — Aeonik + Playfair Display as briefing display type — via a multi-candidate design-exploration phase with user selection before build. No feature flags anywhere; the founder-persona end-to-end verification gates rollout instead.

## Capabilities

### New Capabilities
- `unified-todo-model`: Assignee + execution lifecycle on todos, Approve/Dismiss/Hand-to-GAIA actions, visible work log, server-side budgets + expiry + creation quality gate, silence-as-signal memory writes.
- `daily-briefing-run`: Per-user daily system workflow: curate-then-create, yesterday-vs-plan lookback, budget enforcement, one-message-a-day law with a short escalation ladder, briefing payload emission, gone-quiet winback behavior.
- `briefing-artifacts`: Briefing payload schema + storage, email notification channel adapter + editorial templates (daily/weekly/notification), OpenUI briefing component family with archive, Telegram rendering with inline Approve actions, bands-gradient visual system.
- `mission-control-dashboard`: The new `/dashboard`: briefing header, interleaved day timeline, action rail with inline approvals, done-today counts, contribution heatmap.
- `retention-loop`: Honest streak rules, milestone badge system, weekly digest + shareable Wrapped card, PostHog instrumentation events and the approve-rate north star.
- `onboarding-goal-seed`: The added onboarding question, memory persistence, revival of dormant `onboarding.focus`, first-briefing cold-start guarantee.
- `first-steps-nudge`: The cross-page activation checklist widget with per-user progress state.
- `tier-limits-conversion`: Free-tier metering of GAIA todo executions via the existing tiered rate-limit system; the at-quota Approve tap as the upgrade surface with the staged work as the pitch.

### Modified Capabilities
- `tracked-todos-vfs`: Activeness discriminator changes from `labels` containing `gaia-tracked` to `assignee == "gaia"`; projected file contents otherwise unchanged.

## Impact

- **Backend**: `apps/api/app/models/todo_models.py` (assignee + execution lifecycle fields), `apps/api/app/constants/todos.py` (budgets, expiry, retire `GAIA_TRACKED_LABEL`), `apps/api/app/services/tracked_todo_service.py` + `apps/api/app/agents/tools/tracked_todo_tools.py` (quality gate, budget enforcement, assignee migration), new briefing service + ARQ task + prompt, new `briefings` collection, email channel adapter in `apps/api/app/utils/notification/`, outbound envelope extension for Telegram inline actions (`apps/api/app/schemas/outbound.py` + `libs/shared/ts/src/bots/`), new endpoints (approve/dismiss/hand-off, briefing fetch, timeline, heatmap, first-steps progress), onboarding question plumbing, PostHog events.
- **Frontend**: todo feature UI (assignee, states, Approve/Dismiss, work log), new Mission Control `/dashboard` page + heatmap, OpenUI briefing components, first-steps widget in the main layout, onboarding step, settings for email channel.
- **Bots**: Telegram adapter renders inline keyboards for approve actions and posts callbacks to the API.
- **Data migration**: backfill `assignee: "gaia"` where `labels` contains `gaia-tracked`; one release of dual-read fallback, then the label is removed.
- **Monetization**: new `gaia_todo_executions` entry in `apps/api/app/config/rate_limits.py` (free/pro), upgrade flow reuse; email requires an ESP account + sending domain (SPF/DKIM) as an ops precondition.
- **Risk**: briefing quality is the retention bet — mitigated by budgets, the quality gate, the founder-persona end-to-end verification gate before all-users rollout, and instrumentation that surfaces approve-rate decay weeks before churn. Approval enforcement is prompt + tool-arg level in v1 (documented), not a hard tool sandbox. No feature flags — sequencing and E2E verification replace them.
- **Non-goals (v1)**: global leaderboard, HTML approval-table artifacts, trust-ramp auto-send escalation, persona expansion beyond founder-flavored prompts, mobile push, effort-gamification (points/guilt streaks).
