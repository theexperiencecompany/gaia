# Aesthetic Rules

Rules derived from 72 creative direction sessions. These are non-negotiable.

## Colors

| Token | Value | Usage |
|-------|-------|-------|
| Primary | `#00bbff` (cyan) | Highlights, buttons, accent text, CTA |
| Background | `#111111` | All scene backgrounds (globally configurable) |
| Surface | `#27272a` | Card backgrounds, panels |
| Card dark | `#18181b` | Darker card variants |
| Text primary | `#ffffff` | All heading text on dark bg |
| Text secondary | `#a1a1aa` (zinc400) | Subtext, timestamps, labels |
| Text muted | `#71717a` (zinc500) | Problem statement overlays |
| Separator | `#3f3f46` (zinc700) | Divider lines inside cards |
| No pure black (`#000000`) | Ever | Use `#111111` or `#18181b` instead |

## Typography

### Display text (headlines, hero words)
- Font: `FONTS.display` (Aeonik / Helvetica Neue)
- Weight: 700-800
- Case: UPPERCASE for all impact statements
- Size scale:
  - Hero word (1 word at a time): **200px**
  - Section headline: **96-190px**
  - Subtitle/tagline: **60-80px**
  - CTA headline: **72px**
- Letter spacing: `-0.02em` to `-0.04em` (tighter at larger sizes)
- Line height: `0.9` - `1.0`

### Body text (bubbles, cards, UI)
- Font: `FONTS.body` (Inter)
- Weight: 400-600
- Size: 22-36px
- Line height: `1.3` - `1.65`

### Rules
- **No italic anywhere**. Not even for emphasis.
- **No serif fonts anywhere**.
- **No weird letter-spacing** (no positive tracking on display text)
- **Underscored names → human readable**: `send_email` → `Send Email`

## Design Language

### Flat design
- No `border` on inner cards or components
- No `boxShadow` on modals or cards
- No outlines, no glows (except subtle radial `background` bloom on CTA)
- No grid/dot/pattern backgrounds

### Roundedness
- Cards: `borderRadius: 24-30`
- Chat bubbles: `borderRadius: 40` (user) / `40px 40px 40px 8px` (bot with tail)
- Buttons/pills: `borderRadius: 999` (full pill)
- Icons containers: `borderRadius: 16-26`
- Search bar: `borderRadius: 50`

### Screen real estate
- Fill the screen. It's a video, not a web app.
- Padding: `52-120px` from edges (never more)
- Cards should be large — `width: 100%` of available space
- Text should be BIG. If someone squints, it's too small.
- No unnecessary wrapper containers. Content sits directly on scene background.

### Icons
- Always use `@theexperiencecompany/gaia-icons/solid-rounded` or `stroke-rounded`
- Style prop: `style={{ color: "#00bbff" }}` — NOT `color="#00bbff"` (prop doesn't work)
- Size: 28-68px depending on context
- For app icons: use `staticFile("images/icons/macos/...")` with `.webp` format
- For integration icons: `staticFile("images/icons/...")` with `.svg` or `.webp`
- For GitHub SVG on dark bg: apply `filter: "invert(1)"`
- Circular clipping: `clipPath: "circle(50% at 50% 50%)"` (not `overflow: hidden` + `borderRadius`)
- Never use raw SVG elements. Never use emoji as icon substitutes.

### Image handling
- All images via `staticFile()` — never import or require
- Logo: `staticFile("images/logos/logo.webp")` (square), `staticFile("images/logos/text_w_logo_white.webp")` (text+logo)
- Use `<Img>` from Remotion (not `<img>`)
- `objectFit: "contain"` for logos, `"cover"` for app icons

## Copywriting

### Voice
- Direct, punchy, no corporate fluff
- Short phrases. One idea per beat.
- Not a developer tool — it's a personal productivity assistant
- Avoid generic SaaS copy ("Build it. Ship it." = bad)

### Proven lines
- Hook: "STOP WASTING YOUR TIME."
- Subtitle: "The AI that acts before you ask."
- Close: "So you can focus on WHAT MATTERS. EVERYTHING ELSE, HANDLED."
- CTA: "Start for free." + "heygaia.io" typing animation

### Bad patterns (rejected)
- "Build it. Ship it. Own it." — sounds like dev tool
- "Automate the repetitive. Reclaim your day." — generic
- "Community driven platform." — bland
- Any line that could be about any SaaS product
