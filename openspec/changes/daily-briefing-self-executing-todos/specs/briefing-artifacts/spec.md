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

### Requirement: Email is a new notification channel with hand-designed templates

An email channel adapter SHALL be added to the notification orchestrator, sending via an HTTP ESP configured by environment variables and shipping dark (no-op with a log) until keys are set. Three hand-designed templates SHALL exist — daily brief, weekly digest, plain notification — filled from the payload; template selection keys off `kind`. Email SHALL respect the existing per-channel notification preferences and appear in the notification settings UI.

#### Scenario: Dark until configured
- **WHEN** no ESP credentials are configured
- **THEN** email delivery is skipped with a structured log and other channels deliver normally

#### Scenario: User disables email
- **WHEN** the user turns the email channel off in notification settings
- **THEN** briefings deliver to remaining channels only

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
