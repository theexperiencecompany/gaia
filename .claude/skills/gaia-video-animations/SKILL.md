---
name: gaia-video-animations
description: Create high-quality Remotion video animations for GAIA product commercials. Use when building, modifying, or creating new scenes for the GAIA promotional video (apps/video), creating Apple-style motion design commercials in Remotion, or when working on any video animation in the GAIA monorepo. Covers scene architecture, animation patterns, typography, transitions, sound design, and aesthetic rules derived from 72 production conversations. Also use when the user asks to create a new video, add scenes, fix animation timing, or improve visual quality of Remotion compositions.
---

# GAIA Video Animations

Production-grade Remotion animation skill for GAIA product videos. Every rule below was learned from real feedback over 72 creative direction sessions.

## Quick Reference

- **Spec**: 1920x1080 @ 30fps, ~90 seconds, dark theme
- **Stack**: Remotion 4.x, React, TypeScript, TransitionSeries
- **Style**: Apple/Notion commercial — fast, typographic, flat, real components
- **Aesthetic rules**: See [references/aesthetic-rules.md](references/aesthetic-rules.md)
- **Animation patterns**: See [references/animation-patterns.md](references/animation-patterns.md)
- **Scene architecture**: See [references/scene-architecture.md](references/scene-architecture.md)

## Core Principles (Non-Negotiable)

1. **It's a VIDEO, not a UI** — everything 2x larger than web. Hero text 150-200px. Cards fill the screen.
2. **Use REAL components** from the GAIA codebase — never recreate. Import actual components with dummy data.
3. **Fast-paced** — no scene dwells. Cut durations 20-40% shorter than instinct says. Short scenes: 50-100 frames. Long scenes: max 255 frames.
4. **Flat design** — no outlines, no borders, no drop shadows, no glows (except subtle radial blooms on CTA scenes).
5. **No italic text. Ever.** No serif. No emojis — use `gaia-icons` (`@theexperiencecompany/gaia-icons/solid-rounded`).
6. **Snap, don't bounce** — text entrances use `damping: 200` (instant snap). Only cards/icons get bouncy springs.
7. **Seamless transitions** — scenes overlap via TransitionSeries. No dead air between scenes.

## Constants (Always Centralized)

Never hardcode colors, fonts, or spring configs. Use `constants.ts`:

```ts
export const COLORS = {
  bg: "#111111", bgLight: "#111111", secondaryBg: "#1a1a1a",
  surface: "#27272a", primary: "#00bbff", white: "#ffffff",
  textDark: "#ffffff", zinc400: "#a1a1aa", zinc500: "#71717a",
  zinc600: "#a1a1aa", zinc700: "#3f3f46", zinc800: "#27272a", zinc900: "#18181b",
} as const;

export const FONTS = {
  display: '"Aeonik", "Helvetica Neue", Helvetica, sans-serif',
  body: '"Inter", system-ui, sans-serif',
  mono: '"Anonymous Pro", "Cascadia Code", monospace',
} as const;

export const TRANSITIONS = { fast: 8, normal: 12, slow: 15, reveal: 20 } as const;

export const SPRINGS = {
  smooth: { damping: 200 },
  snappy: { damping: 20, stiffness: 200 },
  natural: { damping: 18, stiffness: 120 },
  bouncy: { damping: 8, stiffness: 180 },
  cinematic: { damping: 22, stiffness: 80 },
} as const;
```

## Sound Design

```ts
export const SFX = {
  whoosh: "https://remotion.media/whoosh.wav",   // scene transitions (slide/wipe only)
  whip: "https://remotion.media/whip.wav",       // word beat slams
  uiSwitch: "https://remotion.media/switch.wav", // UI elements appearing
  mouseClick: "https://remotion.media/mouse-click.wav", // typing (sparingly)
} as const;
```

**Rules**: whip for word slams, whoosh for transitions, uiSwitch for cards. Never play click sounds where nothing is clicked.

## Common Pitfalls

1. **Too small** — if not readable on 4K TV from a couch, bigger
2. **Elastic text** — never bouncy springs on text. `damping: 200` only
3. **Emojis** — use `gaia-icons` with `style={{ color: X }}` (not `color` prop)
4. **Broken assets** — always `staticFile("images/...")`. Verify file exists
5. **Wrapper containers** — no boxes around fullscreen content. Direct on `AbsoluteFill`
6. **Grid/dot backgrounds** — never
7. **Scene too long** — 50-100f for text, 100-180f for UI, max 255f
8. **Italic/serif** — never
9. **Borders on cards** — flat only, no `border` property
10. **Dark SVG on dark bg** — `filter: invert(1)`
11. **Duration mismatch** — Root.tsx `durationInFrames` = `sum(scenes) - sum(transitions)`. Recalculate after every change.
12. **Fade between word beats** — use instant hard cuts (`if (frame >= exitFrame) return null`), not fades
