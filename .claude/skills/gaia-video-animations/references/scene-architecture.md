# Scene Architecture

How to structure Remotion scenes for GAIA product videos.

## Table of Contents

1. [File Structure](#file-structure)
2. [Scene Template](#scene-template)
3. [Composition (GaiaPromo.tsx)](#composition)
4. [Duration Calculation](#duration-calculation)
5. [Scene Types](#scene-types)
6. [Narrative Structure](#narrative-structure)
7. [Component Reuse](#component-reuse)
8. [Transition Whoosh Sync](#transition-whoosh-sync)

---

## File Structure

```
apps/video/src/
├── Root.tsx                 # Registers compositions, sets total durationInFrames
├── GaiaPromo.tsx           # Main TransitionSeries — scene sequencing + SFX
├── constants.ts            # COLORS, FONTS, TRANSITIONS, SPRINGS
├── sfx.ts                  # SFX URLs
├── components/
│   ├── TypingText.tsx      # Typing animation
│   ├── WaveSpinner.tsx     # Loading indicator
│   └── SceneBackground.tsx # Reusable background variants
├── scenes/
│   ├── S01_OpeningStatement.tsx
│   ├── S02_ToolChaos.tsx
│   └── ... (one file per scene, numbered)
└── public/
    ├── images/
    │   ├── icons/          # Integration icons (svg, webp)
    │   │   └── macos/      # macOS app icons
    │   └── logos/          # GAIA logos
    └── sounds/             # Background music tracks
```

## Scene Template

Every scene follows this pattern:

```tsx
import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";

export const S99_SceneName: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Entrance animation
  const enterP = spring({ frame, fps, config: { damping: 200 } });
  const opacity = interpolate(enterP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const y = interpolate(enterP, [0, 1], [20, 0]);

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight }}>
      {/* SFX */}
      <Sequence from={0}>
        <Audio src={SFX.whoosh} volume={0.3} />
      </Sequence>

      {/* Content */}
      <div style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        transform: `translateY(${y}px)`,
        opacity,
      }}>
        <span style={{
          fontFamily: FONTS.display,
          fontSize: 96,
          fontWeight: 700,
          color: COLORS.textDark,
          textTransform: "uppercase",
        }}>
          Scene Content
        </span>
      </div>
    </AbsoluteFill>
  );
};
```

## Composition

`GaiaPromo.tsx` is a flat `TransitionSeries` with alternating Sequences and Transitions:

```tsx
<TransitionSeries>
  {/* Scene */}
  <TransitionSeries.Sequence durationInFrames={55}>
    <S01_OpeningStatement />
  </TransitionSeries.Sequence>

  {/* Transition */}
  <TransitionSeries.Transition
    presentation={fade()}
    timing={linearTiming({ durationInFrames: 4 })}
  />

  {/* Next scene */}
  <TransitionSeries.Sequence durationInFrames={100}>
    <S02_ToolChaos />
  </TransitionSeries.Sequence>

  {/* ... */}
</TransitionSeries>

{/* Global: background music */}
{/* <Audio src={staticFile("sounds/1.mp3")} volume={0.5} loop /> */}

{/* Global: transition whoosh sounds at computed absolute frames */}
{SLIDE_FRAMES.map((frame) => (
  <Sequence key={frame} from={frame}>
    <Audio src={SFX.whoosh} volume={0.25} />
  </Sequence>
))}
```

## Duration Calculation

**Critical formula:**

```
Root durationInFrames = sum(all scene durations) - sum(all transition durations)
```

Example:
- Scene A: 55 frames
- Transition: 4 frames (fade)
- Scene B: 100 frames
- Total: 55 + 100 - 4 = 151 frames

**Absolute frame offsets for whoosh sounds:**

```
abs_start_N = abs_start_(N-1) + duration_(N-1) - transition_duration_(N-1)
```

Store as `SLIDE_FRAMES` array. Only for slide/wipe transitions (fades are silent).

**Must recalculate after every scene addition/removal/duration change.**

## Scene Types

### Text Beat (50-70 frames)
One statement, large text, snap in. Example: S01_OpeningStatement, S21_Completed, S31_NotJustAssistant.

### UI Showcase (100-180 frames)
Real component with animation. Example: S08_ChatResponse, S28_DashboardReveal.

### Animated Sequence (150-255 frames)
Multi-step animation with internal timing. Example: S26_IntegrationBuilder, S22c_TriggerSlots.

### Typography Hero (80-100 frames)
Character cascade or multi-line reveal. Example: S32_ProductivityOS, S29_OneDashboard.

### CTA/Finale (100-120 frames)
Search bar, logo, call to action. Example: S34_SearchBarCTA.

## Narrative Structure

The video follows an 8-act structure. Each new video should follow a similar arc:

| Act | Purpose | Duration | Scenes |
|-----|---------|----------|--------|
| 1. The Hook | Grab attention | ~5s | Bold text beat + visual chaos |
| 2. The Problem | Show pain | ~4s | Icons/tools overwhelm |
| 3. The Solution | Introduce product | ~4s | Logo + tagline |
| 4. The Demo | Show it working | ~20s | Chat → tool calls → result |
| 5. The Magic | Show proactivity | ~8s | Proactive actions + triggers |
| 6. The Reach | Multi-platform | ~10s | Notifications, platforms |
| 7. The Ecosystem | Community/integrations | ~15s | Cards, builder, marketplace |
| 8. The Close | CTA | ~10s | Dashboard → tagline → search bar |

## Component Reuse

Always import real GAIA components. Common ones used in video:

- **Chat bubbles**: Import from `apps/web/src/features/chat/` — match exact styles
- **Tool calls section**: Import or replicate exact component with correct icons
- **Workflow cards**: Use `WorkflowVideoCard` / `WorkflowDraftVideoCard` matching real card
- **Dashboard cards**: Use demo components from landing page
- **Integration sidebar**: Match exact right sidebar from integrations page

When importing isn't possible (Remotion bundle limitations), replicate with:
- Same exact colors from the web app's CSS
- Same border radius
- Same padding/spacing
- Same font sizes
- Same icon library (`gaia-icons`)

**Never approximate. Match exactly.**

## Transition Whoosh Sync

For slide/wipe transitions, compute absolute frame offsets and store them:

```tsx
const SLIDE_FRAMES = [
  283,   // S05→S06   slide from-bottom
  515,   // S07→S08   slide from-bottom
  757,   // S19→S10   wipe  from-left
  // ... etc
] as const;

// Render as global Audio sequences
{SLIDE_FRAMES.map((frame) => (
  <Sequence key={frame} from={frame}>
    <Audio src={SFX.whoosh} volume={0.25} />
  </Sequence>
))}
```

This ensures whoosh plays at the exact moment the transition starts. Comment each entry with `source→target direction` for maintainability.
