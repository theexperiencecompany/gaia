# GAIA Video Design Language

Every GAIA video must be unmistakably GAIA. All values below are lifted from the live codebase (`DESIGN.md`, `apps/web/src/app/styles/globals.css`, font configs, hero components, brand assets). Trust these over memory.

The look in one sentence: **dark-first, flat, single-accent** — a deep near-black canvas, one electric cyan, an ultralight editorial serif for display moments, soft blur-in motion, depth from tonal layering (never borders or shadows).

## Typography

Three families do all the work. (`DESIGN.md` names Anonymous Pro for mono but the shipped code uses **Geist Mono** — trust the code.)

| Role | Family | Weights | Where |
|---|---|---|---|
| Display / hero | **PP Editorial New** | 200 Ultralight, 400 Regular (+italics) | Big editorial marketing moments ONLY |
| Body / UI | **Inter** (variable) | 300–700 | Everything else: subheads, body, labels, UI mockups |
| Mono / code | **Geist Mono** | 400–500 | Code, timestamps, terminal/CLI motifs |

Font files: PP Editorial New woff2s live at `apps/web/src/app/fonts/editor-new/`; Inter + Geist Mono woff2s via `@fontsource/inter` / `@fontsource/geist-mono`. In Remotion, embed all of them as base64 data-URI `@font-face` CSS (see `remotion-technique.md` — network font loaders flake in renders).

### The hero signature (memorize exactly)

- PP Editorial New, weight **400**, up to **104px** (6.5rem) desktop scale
- `line-height: 1.0`, `letter-spacing: -0.05em`
- **Sentence case** — never lowercase, never uppercase
- Fill is a vertical **gradient text clip**, not flat white: `linear-gradient(to bottom, #ffffff, #dbdbdb)` on dark
- Real brand headline: "Get a workday back every week."

Secondary display treatment: PP Editorial New 48px weight **200**, line-height 1.1, letter-spacing -0.02em.

### Case rules

Display = sentence case. Body = sentence case. Never lowercase-stylized headlines.

**BANNED IN VIDEO: the uppercase + wide-letter-spacing eyebrow/kicker pattern.** The web landing page uses it; the founder has explicitly banned it in motion work — it reads as generic UI chrome, not motion design. If a scene needs a secondary label, use a quiet sentence-case line (Inter 400, zinc-400) or a mono timestamp. No `text-transform: uppercase`, no positive letter-spacing labels, ever.

## Color (hex, video-ready)

| Token | Hex | Use |
|---|---|---|
| **Accent (brand cyan)** | `#00bbff` | THE one accent. CTAs, highlights, key strokes. Never introduce a second saturated hue outside data-viz. |
| App background | `#111111` | Default video canvas |
| Deepest | `#09090b` | Night/deep scenes |
| Sidebar/secondary | `#1a1a1a` | Panels |
| Card outer | `#27272a` | zinc-800 |
| Card inner | `#18181b` | zinc-900 |
| Text primary | `#f4f4f5` | zinc-100 |
| Text titles | `#e4e4e7` | zinc-200 |
| Text body/secondary | `#a1a1aa` | zinc-400 |
| Text meta/labels | `#71717a` | zinc-500 |
| Success | `#34d399` | 10%-opacity fill + full-color text |
| Warning | `#fbbf24` | same pattern |
| Error | `#f87171` | same pattern |
| Info | `#60a5fa` | same pattern |

Logo glyph internals: `#02bdff` (bright), `#059cda` (mid), `#0f537c` (deep). Chart palette: `#a78bfa #34d399 #60a5fa #f472b6 #fb923c`.

**Card depth rule:** outer `#27272a` over inner `#18181b`. That two-tone layering IS the separation mechanism. **No borders, no card shadows** — ever.

## Shape & surface

- Radius: cards **16px minimum** (up to 24px for large surfaces), buttons 16px, pills 9999. Nothing sharp.
- Cards: flat, borderless, shadowless.
- Glassmorphism for floating elements: `rgba(39,39,42,0.4)` + `backdrop-blur-xl`.
- Signature CTA ("RaisedButton"): cyan `#00bbff` pill, `border-top: 1px solid rgba(255,255,255,0.4)`, overlay `linear-gradient(to bottom, rgba(255,255,255,0.2), transparent)`, shadow `0 4px 5px rgba(0,187,255,0.2)`, black text.
- **No grain/noise texture.** The aesthetic is clean and flat — let cyan + the editorial serif carry identity.

## Motion fingerprint

GAIA's house entrance is the **soft blur-in**: fade + un-blur + rise.

```
from { opacity: 0; filter: blur(12px); transform: translateY(16px); }
to   { opacity: 1; filter: blur(0);    transform: translateY(0); }
```

- Ease: `cubic-bezier(0.22, 1, 0.36, 1)` (the house ease, easeOutExpo-like)
- Duration: 0.5s text / 0.55s blocks; per-character stagger 0.04s on hero, 0.015s default
- Bounce entrances: `cubic-bezier(0.34, 1.56, 0.64, 1)` — scale 0.9→1 (0.4s) or scale 0.8→1.05→1 with blur 20px→0 (0.5s)
- Hero word reveal ease: `cubic-bezier(0.2, 0.8, 0.2, 1)`
- Background parallax drifts at **0.3×** foreground speed

## Brand assets (paths under `apps/web/public/`)

- `brand/gaia_logo.svg` — vector glyph, layered cyans, best for video
- `brand/gaia_wordmark_white.png` / `gaia_wordmark_black.png` — wordmark lockups
- `gaia-glow.webp` — cyan bloom, use as light source behind the mark
- `images/wallpapers/swiss_morning|_evening|_night.webp`, `swiss kid day.webp` — the time-of-day Swiss mountain system (a "GAIA adapts to your day" motif)
- `images/wallpapers/bands_gradient_1.webp` — gradient band section background
- `whatsapp-doodle.webp`, `aryan-avatar.webp` — chat-scene props

## Brand voice

Direct, benefit-led, slightly provocative toward incumbents. Short declaratives, em-dashes not pipes. Core word: **proactive**. Real lines usable as video beats:

- "Get a workday back every week."
- "Acts before you ask"
- "Stop doing everything yourself."
- "Every tool. One assistant."
- "GAIA watches your inbox, calendar, and tools and acts before you ask."
- CTA microcopy: "No credit card required. Free forever plan included."

## Motion design, not UI design (founder-mandated)

A GAIA video is a **type-led motion piece with product surfaces as evidence** — not an animated screenshot tour.

- **Typography is the hero of every scene.** The dominant element is a giant statement (Inter 700, 90–150px at 1080p, tracking −0.03..−0.04em, hero-to-support ratio ≥2.6:1). UI components support the claim; they never carry the scene alone.
- **Components are big.** Cards span ~1000–1300px of a 1920 frame, body type inside them ≥28px. If a card looks like a small floating widget in empty space, the camera is too far out — zoom until it feels tight.
- **Prefer typography and real product components** (composer with live typing + caret, chat bubbles, approval rows, counters) **over photographs/wallpapers/stock imagery.** Atmosphere comes from light (glows, gradient washes) and motion, not from background images.
- Headings must belong to the composition (overlapping, anchored to the evidence below them) — never a detached "section title" floating above a card like a webpage.

## Surface discipline (defect classes that recur — check every card)

- **One accent means one accent.** Semantic greens/ambers count: a success-green chip recurring across three scenes IS a second accent. Reserve semantic color for at most ONE moment in the film; status chips elsewhere are zinc surfaces with a cyan drawn check.
- **No blank placeholder shapes.** An empty gray avatar circle is the loudest "AI mockup" tell. Use an initial, a logo, or nothing.
- **Reading time is math, not vibes.** For every text surface: chars ÷ 17 ≤ seconds actually held (compute from the beat sheet). The emotional-proof card gets the LONGEST hold, not the shortest.
- **Copy logic must be consistent across scenes.** Props are testimony: a chip that says "Queued" contradicts a later "needs your approval." Before rendering, list every status/claim string and check they tell one story.
- **No dead card regions.** If a card has an empty right half, right-align metadata there (durations, counts, in mono) or narrow the card. Standardize on at most two card widths per film.
- **Mono is for time, numbers, URLs, code — nothing else.** A handle or label in mono dilutes the signal the timestamps own.
- **Show one real sentence of any AI-produced artifact** (email opening line, message text). All-skeleton bodies at the moment of proof read as hiding the goods.

## What makes GAIA look like GAIA (checklist)

1. `#111111` canvas + one electric cyan `#00bbff`, monochrome zinc everywhere else
2. Ultralight/regular editorial serif display with gradient-clipped fill, huge, tight tracking
3. Soft blur-in entrances with the house ease
4. Flat borderless two-tone zinc cards, 16px+ radius
5. Glass for floating elements
6. Glossy raised cyan CTA pill
7. Fade-to-black gradient section transitions
8. Drawn icons only — never Unicode glyphs (→ • ✓ ×) as UI (emoji inside chat message content is fine — it's diegetic)
