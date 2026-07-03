## ADDED Requirements

### Requirement: Briefings are payloads, never markup

The briefing run SHALL emit a Pydantic-validated `BriefingPayload` — `kicker`, `date`, `headline`, `lede`, `stats[] {value, label, delta?}`, `sections[] {numeral, title, items[] {text, todo_id?, kind}}`, `mood`, `caption`, `hue` (0–360) — and SHALL NOT emit HTML, Markdown styling, or any markup. Payloads SHALL be stored in a `briefings` collection `{id, user_id, date, kind: daily|weekly, payload, delivered_channels, created_at}`, one daily payload per user per day.

#### Scenario: Invalid payload fails loudly
- **WHEN** the run produces output missing `headline`
- **THEN** validation fails, the run is marked failed, and no partial briefing is stored or delivered

### Requirement: Dashboard renders briefings via an OpenUI component family

A briefing component family SHALL be added to the OpenUI system with editorial styling baked in: masthead (kicker + date), bands-gradient hero (`/images/wallpapers/bands_gradient_1.webp`) with CSS `hue-rotate` driven by `payload.hue`, serif display headline, lede, stat row, Roman-numeraled sections, caption footer. Styling SHALL be entirely client-owned; the payload only fills slots. Past briefings SHALL be archived and browsable from the dashboard.

#### Scenario: Hue varies per day, template does not
- **WHEN** two consecutive daily payloads carry different `hue` values
- **THEN** both render the identical layout with only the gradient hue (and mood-keyed treatment) differing

### Requirement: Email briefings are on by default until the user disables them

An email channel adapter SHALL be added to the notification orchestrator, sending via an HTTP ESP configured by environment variables (no-op with a structured log until keys are set — an ops precondition, not a feature flag). The email channel SHALL be **enabled by default** for daily briefings and weekly digests for every user with a known email address, until the user disables it in notification settings or via the one-click unsubscribe link that every briefing email SHALL carry (unsubscribe maps to the same channel preference). Three hand-designed templates SHALL exist — daily brief, weekly digest, plain notification — filled from the payload; template selection keys off `kind`.

#### Scenario: Default-on for briefings
- **WHEN** a user has never touched notification settings
- **THEN** the morning briefing is delivered to their email as well as in-app and linked platforms

#### Scenario: Unsubscribe honors immediately
- **WHEN** the user clicks unsubscribe in a briefing email
- **THEN** the email channel preference flips off and no further briefing emails are sent, with other channels unaffected

### Requirement: Briefing and todo surfaces meet the editorial design bar

Briefing surfaces (dashboard card, email templates, archive) SHALL follow GAIA's design system (`DESIGN.md`) at the quality bar of the Dia-artifacts reference: Notion/Apple/ElevenLabs/Vercel-class cleanliness. Display typography for briefings SHALL use **Aeonik** (already at `apps/web/src/app/fonts/aeonik.ts`) with **Playfair Display** as the serif display companion (added via `next/font`), alongside the codebase's existing families (Inter, PP Editorial New, Anonymous Pro) per their established roles. Implementation SHALL be preceded by a design-exploration pass producing multiple full candidates for (a) the briefing card and (b) the todos sidebar, with one selected by the user before build (see tasks).

#### Scenario: Typography is from the system
- **WHEN** any briefing surface renders
- **THEN** all type resolves to Aeonik, Playfair Display, or existing codebase families — no ad-hoc fonts

#### Scenario: Email matches the dashboard identity
- **WHEN** the same payload renders as email and dashboard card
- **THEN** both share the masthead structure, bands-gradient identity, and typographic hierarchy within each medium's constraints

### Requirement: Telegram briefings carry working inline approvals

The outbound envelope (`apps/api/app/schemas/outbound.py` and its TS twin) SHALL gain optional `actions: [{label, callback_data}]`. The Telegram adapter SHALL render actions as an inline keyboard; callbacks SHALL resolve to the approve/dismiss endpoints with the user's identity verified via the existing platform link. An approval tapped in Telegram SHALL have the same effect as one tapped on the dashboard, and the message SHALL update to reflect the taken action.

#### Scenario: Approve from Telegram
- **WHEN** a briefing in Telegram includes "Send 12 investor DMs [Approve]" and the user taps Approve
- **THEN** the corresponding todo transitions `proposed → queued`, execution enqueues, and the Telegram message updates to show the approval

#### Scenario: Envelope without actions is unchanged
- **WHEN** an outbound message has no `actions`
- **THEN** bots render it exactly as today (backward compatible)

### Requirement: One payload feeds every channel

A single stored payload SHALL be the source for all renderings of that briefing — OpenUI dashboard card, email template, and Telegram prose. Channel renderers SHALL NOT re-invoke the LLM to reformat.

#### Scenario: Consistent content across channels
- **WHEN** a briefing is delivered to dashboard, Telegram, and email
- **THEN** all three contain the same headline, stats, and items, differing only in presentation
