# GAIA Video Design Language

Every GAIA video must be unmistakably GAIA. All values below are lifted from the live codebase (`DESIGN.md`, `apps/web/src/app/styles/globals.css`, font configs, hero components, brand assets). Trust these over memory.

The look in one sentence: **dark-first, flat, single-accent** — a deep near-black canvas, one electric cyan, huge tight-tracked Helvetica display type, soft blur-in motion, depth from tonal layering (never borders or shadows).

## Typography

Two families do all the work in video. (`DESIGN.md` names Anonymous Pro for mono but the shipped code uses **Geist Mono** — trust the code.)

| Role | Family | Weights | Where |
|---|---|---|---|
| Everything | **Helvetica** (via TeX Gyre Heros, the faithful free clone) | 400, 700 | All display, statements, body, UI mockups |
| Mono / code | **Geist Mono** | 400–500 | Timestamps, numbers, URLs, terminal/CLI motifs |

**Video type is Helvetica-only (founder-mandated), varied by weight.** Real Helvetica isn't redistributable — embed **TeX Gyre Heros** (GUST e-foundry, free, metrically faithful) as base64 OTFs behind the stack `'TeX Gyre Heros', 'Helvetica Neue', Helvetica, Arial, sans-serif`. Heros ships only 400 + 700: design with those two real cuts and NEVER use 500/600 (the browser would synthesize fake weights). Hierarchy comes from size + the 400/700 contrast.

**SERIF IS BANNED IN VIDEO (founder-mandated).** PP Editorial New is a web-landing display face only — it never appears in motion work. No exceptions, no "one serif hero moment."

Font files: PP Editorial New woff2s live at `apps/web/src/app/fonts/editor-new/`; Inter + Geist Mono woff2s via `@fontsource/inter` / `@fontsource/geist-mono`. In Remotion, embed all of them as base64 data-URI `@font-face` CSS (see `remotion-technique.md` — network font loaders flake in renders).

### The video display signature

- Helvetica weight **700**, 90–210px at 1080p, `letter-spacing: -0.035..-0.04em`, line-height ~1.05
- **Sentence case** — never lowercase, never uppercase
- Hero lines may use the vertical **gradient text clip**: `linear-gradient(to bottom, #ffffff, #dbdbdb)` on dark
- Real brand headline for reference of voice: "Get a workday back every week."
- (The web landing uses PP Editorial New serif for its hero — that face is banned in video; see above.)

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

- Radius in video: outer cards **34px**, inner items **22–24px**, chat surfaces 36–38px, buttons/pills 9999. Rounder than the web app — the camera magnifies corners. Nothing sharp.
- Cards: flat, borderless, shadowless.
- Glassmorphism for floating elements: `rgba(39,39,42,0.4)` + `backdrop-blur-xl`.
- Signature CTA ("RaisedButton"): cyan `#00bbff` pill, `border-top: 1px solid rgba(255,255,255,0.4)`, overlay `linear-gradient(to bottom, rgba(255,255,255,0.2), transparent)`, shadow `0 4px 5px rgba(0,187,255,0.2)`, black text.
- **No grain/noise texture.** The aesthetic is clean and flat — let cyan + huge confident type carry identity.

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

- **Typography is the hero of every scene.** The dominant element is a giant statement (Helvetica 700, 90–150px at 1080p, tracking −0.03..−0.04em, hero-to-support ratio ≥2.6:1). UI components support the claim; they never carry the scene alone.
- **Components are big.** Cards span ~1000–1300px of a 1920 frame, body type inside them ≥28px. If a card looks like a small floating widget in empty space, the camera is too far out — zoom until it feels tight.
- **Prefer typography and real product components** (composer with live typing + caret, chat bubbles, approval rows, counters) **over photographs/wallpapers/stock imagery.** Atmosphere comes from light (glows, gradient washes) and motion, not from background images.
- Headings must belong to the composition (overlapping, anchored to the evidence below them) — never a detached "section title" floating above a card like a webpage.

## Platform surface fidelity (founder-mandated)

When a scene shows a third-party chat surface, **replicate the product's real landing-page components for that platform — never invent a lookalike**:

- **iMessage**: the landing page's iMessage bubble component, including the **tail/wick** on bubbles, real iMessage blue/gray (`linear-gradient(180deg,#309BFE,#027BFF)` + tail `#0E89FF`; gray `#E9E9EB`), correct radii and delivered/timestamp styling. **GAIA's own chat scenes also use these iMessage-style bubbles** (blue = user, gray = GAIA) — never invented bubble styles.
  - Tail geometry gotcha: the landing tails are `clip-path: path(...)` with **fixed 20×18px coordinates** — the path does NOT scale with the element. To enlarge for video, keep the span at exactly 20×18 and `transform: scale(N)` from the corner that touches the bubble (`transformOrigin` bubble-side bottom). Sizing the box larger instead puts the wick in the wrong corner.
- **Telegram**: the landing page's Telegram section — its wallpaper asset and exact bubble components.
- **WhatsApp**: same principle — real dark-mode palette + the doodle wallpaper asset (`whatsapp-doodle.webp`).
Pull colors/radii/tails from the actual code under `apps/web/src/features/landing/` before building the scene. A generic rounded rectangle "chat" reads as fake instantly; the tail and wallpaper are what sell the platform.

## The close (manifesto-aligned)

The final line comes from the brand manifesto ("Every Human Deserves a Jarvis" — apps/web `features/about/components/About.tsx`), and the film must have EARNED it: the preceding scenes are the proof of the line. Never close on generic boilerplate, and no glows on the CTA surface — the lit enter-button is the only accent.

## CTAs in video

A static URL string is a weak close. Make the CTA an **interaction**: a URL/search bar rises and *types* `heygaia.io` with a live caret (mirroring the product's composer — a bookend if the film opened with typing), then a subline ("Free forever plan. No credit card."). The viewer should watch the action they're about to take.

## Copy logic check

Before animating any line, ask **"who is doing this, and does the sentence survive that?"** — e.g. "5 AM. Your workday just started." fails because the viewer is asleep; it's *GAIA's* workday ("You're asleep. GAIA just clocked in."). Every statement must be literally true within the film's own fiction.

## Surface discipline (defect classes that recur — check every card)

- **One accent means one accent.** Semantic greens/ambers count: a success-green chip recurring across three scenes IS a second accent. Reserve semantic color for at most ONE moment in the film; status chips elsewhere are zinc surfaces with a cyan drawn check.
- **No blank placeholder shapes.** An empty gray avatar circle is the loudest "AI mockup" tell. Use an initial, a logo, or nothing.
- **Reading time is math, not vibes.** For every text surface: chars ÷ 17 ≤ seconds actually held (compute from the beat sheet). The emotional-proof card gets the LONGEST hold, not the shortest.
- **Copy logic must be consistent across scenes.** Props are testimony: a chip that says "Queued" contradicts a later "needs your approval." Before rendering, list every status/claim string and check they tell one story.
- **No dead card regions.** If a card has an empty right half, right-align metadata there (durations, counts, in mono) or narrow the card. Standardize on at most two card widths per film.
- **Mono is for time, numbers, URLs, code — nothing else.** A handle or label in mono dilutes the signal the timestamps own.
- **Show one real sentence of any AI-produced artifact** (email opening line, message text). All-skeleton bodies at the moment of proof read as hiding the goods.
- **Components must be the real structure, not an abstraction of it.** A "calendar" of growing horizontal bars is slop; a calendar is a time ruler with duration-positioned blocks. Build the actual anatomy of the surface (grid lines, event geometry, platform chrome) at reduced fidelity — never a metaphor of it.
- **Brand lockups: never stack the glyph and the wordmark when the wordmark already contains the mark.** One asset per reveal.
- **Chips/pills: auto-width, asymmetric padding (tighter on the icon side), icon ≤0.8× text cap height.** Fixed-width chips leave dead right-padding — a small tell that compounds.
- **VO cue = on-screen line cue.** Each VO line starts within ~0.3s of its paired text entering. Sync is authored per line, not per scene.

## What makes GAIA look like GAIA (checklist)

1. `#111111` canvas + one electric cyan `#00bbff`, monochrome zinc everywhere else
2. Huge Helvetica 700 display with gradient-clipped fill, tight tracking
3. Soft blur-in entrances with the house ease
4. Flat borderless two-tone zinc cards, 16px+ radius
5. Glass for floating elements
6. Glossy raised cyan CTA pill
7. Fade-to-black gradient section transitions
8. Drawn icons only — never Unicode glyphs (→ • ✓ ×) as UI (emoji inside chat message content is fine — it's diegetic)
