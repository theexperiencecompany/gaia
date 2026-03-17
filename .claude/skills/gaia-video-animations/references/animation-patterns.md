# Animation Patterns

Battle-tested patterns from GAIA's production video. Use these as the foundation for all scenes.

## Table of Contents

1. [Word Beat Slam](#1-word-beat-slam)
2. [Snap Entrance](#2-snap-entrance)
3. [Staggered Reveal](#3-staggered-reveal)
4. [Character Cascade](#4-character-cascade)
5. [Typing Animation](#5-typing-animation)
6. [Slot Machine Carousel](#6-slot-machine-carousel)
7. [Tool Chaos (Icon Cloud)](#7-tool-chaos-icon-cloud)
8. [Card Entrance](#8-card-entrance)
9. [Radial Bloom](#9-radial-bloom)
10. [Transition Types](#10-transition-types)
11. [Sound Sync](#11-sound-sync)
12. [Exit Animations](#12-exit-animations)

---

## 1. Word Beat Slam

One word at a time, instant hard cut, tiny scale punch. The signature opening pattern.

```tsx
const WORDS = [
  { text: "STOP",    startFrame: 0,  exitFrame: 10, color: "#ff4444" },
  { text: "WASTING", startFrame: 10, exitFrame: 20, color: COLORS.textDark },
  { text: "YOUR",    startFrame: 20, exitFrame: 32, color: COLORS.textDark },
  { text: "TIME.",   startFrame: 32, exitFrame: 999, color: COLORS.primary },
];

const Word: React.FC<WordProps> = ({ text, startFrame, exitFrame, color }) => {
  const frame = useCurrentFrame();
  if (frame < startFrame || frame >= exitFrame) return null;

  const elapsed = frame - startFrame;
  const punchT = Math.min(1, elapsed / 4);
  const scale = interpolate(punchT, [0, 0.5, 1], [1.07, 1.01, 1.0]);

  return (
    <div style={{
      fontFamily: FONTS.display,
      fontSize: 200,
      fontWeight: 800,
      color,
      textTransform: "uppercase",
      textAlign: "center",
      transform: `scale(${scale})`,
    }}>
      {text}
    </div>
  );
};
```

**Key**: `return null` at exitFrame = instant hard cut. No fade. Whip SFX per word.

---

## 2. Snap Entrance

For text/headlines. Instant snap, no bounce. translateY + opacity.

```tsx
const p = spring({ frame, fps, config: { damping: 200 } }); // SMOOTH, instant
const opacity = interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
const y = interpolate(p, [0, 1], [20, 0]); // subtle 20px slide up

<div style={{ transform: `translateY(${y}px)`, opacity }}>
  HEADLINE TEXT
</div>
```

**Rule**: Text always uses `damping: 200`. Never bouncy springs on text.

---

## 3. Staggered Reveal

Multiple items appearing in sequence. Cards, icons, list items.

```tsx
const items = ["Email", "Calendar", "GitHub", "Slack"];

{items.map((item, i) => {
  const delay = i * 4; // 4 frames between each (~133ms at 30fps)
  const p = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(p, [0, 1], [30, 0]);

  return (
    <div key={i} style={{ transform: `translateY(${y}px)`, opacity }}>
      {item}
    </div>
  );
})}
```

**Timing**: 3-5 frames between items for tight stagger. 8-10 for relaxed.

---

## 4. Character Cascade

Individual letters animate in with a wave effect. For hero words like "WHAT MATTERS" or "PRODUCTIVITY".

```tsx
{"WHAT MATTERS".split("").map((char, i) => {
  const charP = spring({
    frame: frame - (5 + i * 1.5), // 1.5 frame stagger per char
    fps,
    config: { damping: 18, stiffness: 140 },
  });
  const charY = interpolate(charP, [0, 1], [70, 0]);
  const charOpacity = interpolate(charP, [0, 0.08], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <span key={i} style={{
      display: "inline-block",
      color: COLORS.textDark,
      transform: `translateY(${charY}px)`,
      opacity: charOpacity,
      whiteSpace: "pre", // preserve spaces
    }}>
      {char === " " ? "\u00A0" : char}
    </span>
  );
})}
```

**Key**: Use `\u00A0` (non-breaking space) for space characters. `whiteSpace: "pre"` on spans.

---

## 5. Typing Animation

TypingText component for simulating keyboard input.

```tsx
interface TypingTextProps {
  text: string;
  framesPerChar?: number; // default 1 (FAST)
  delay?: number;
  cursorColor?: string;
  showCursor?: boolean;
  style?: React.CSSProperties;
}

// Usage:
<TypingText
  text="Hey GAIA, pull my Gmail from last 6 hours"
  framesPerChar={1}  // FAST — never use 3, too slow
  delay={10}
  cursorColor={COLORS.primary}
  style={{ fontFamily: FONTS.body, fontSize: 32, color: COLORS.textDark }}
/>
```

**Rule**: `framesPerChar: 1` is the default. 0.5 for very fast typing. Never 3 (too slow).

---

## 6. Slot Machine Carousel

Spring summation for vertical scrolling through items. Used for trigger types.

```tsx
const ITEMS = ["On new email", "On pull request", "On new message", ...];
const ITEM_H = 240;
const TRANSITION_STARTS = [16, 32, 48, 64, 80, 96, 112]; // 16f between each scroll

// Spring summation — each spring fires and scrolls one item
const scrollY = TRANSITION_STARTS.reduce((acc, startFrame) => {
  const p = spring({
    frame: frame - startFrame,
    fps,
    config: { damping: 12, stiffness: 160 },
  });
  return acc - interpolate(p, [0, 1], [0, ITEM_H]);
}, 0);

// Active item styling
const activeIndex = Math.round(-scrollY / ITEM_H);

{ITEMS.map((item, i) => {
  const dist = Math.abs(scrollY + i * ITEM_H) / ITEM_H;
  const itemOpacity = Math.max(0.05, 1 - dist * 0.95);   // inactive = near-invisible
  const blurPx = Math.min(22, dist * 14);                   // inactive = heavily blurred
  const itemScale = Math.max(0.88, 1 - dist * 0.08);       // inactive = slightly smaller

  return (
    <div style={{
      height: ITEM_H,
      opacity: itemOpacity,
      filter: blurPx > 0.5 ? `blur(${blurPx}px)` : undefined,
      transform: `scale(${itemScale})`,
    }}>
      {item}
    </div>
  );
})}
```

**SFX**: `uiSwitch` on each transition start. Selection highlight: `borderTop/Bottom: "2px solid #00bbff"`.

---

## 7. Tool Chaos (Icon Cloud)

Multiple icons flying in from scattered positions, shaking, then collapsing to center.

```tsx
// Entry: bounce in from 2x distance
const entryProgress = spring({
  frame: frame - (index * 3),  // 3f stagger
  fps,
  config: { damping: 8, stiffness: 120 }, // BOUNCY for icons
});
const x = interpolate(entryProgress, [0, 1], [position.x * 2, position.x]);

// Shake after settling
const settledFrame = Math.max(0, frame - entryDelay - 20);
const shake = interpolate(settledFrame % 20, [0, 10, 20], [-3, 3, -3]);

// Collapse at end
const collapseProgress = spring({
  frame: frame - 75,
  fps,
  config: { damping: 200 }, // snap collapse
});
```

**Icons**: 96x96px with `borderRadius: 20`. Use `staticFile("images/icons/macos/...")` for macOS app icons.

---

## 8. Card Entrance

Cards use slightly bouncy spring, unlike text.

```tsx
const p = spring({
  frame: frame - delay,
  fps,
  config: { damping: 22, stiffness: 100 }, // slight overshoot
});
const opacity = interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
const cardY = interpolate(p, [0, 1], [40, 0]);
const cardScale = interpolate(p, [0, 1], [0.94, 1.0]);

<div style={{
  borderRadius: 28,
  background: "#27272a",
  transform: `translateY(${cardY}px) scale(${cardScale})`,
  opacity,
}}>
```

**Key**: Cards can bounce slightly (`damping: 22`). Text cannot.

---

## 9. Radial Bloom

Subtle background glow for emphasis scenes (CTA, hero moments).

```tsx
<div style={{
  position: "absolute",
  inset: 0,
  background: `radial-gradient(ellipse at 50% 55%, ${COLORS.primary}18 0%, transparent 40%)`,
  opacity: interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" }),
  pointerEvents: "none",
}} />
```

**Rule**: Only on CTA/finale scenes. Very subtle (`18` hex = 9% opacity). Never on regular scenes.

---

## 10. Transition Types

Use `TransitionSeries` with these patterns:

| Transition | When to Use | Config |
|-----------|-------------|--------|
| `fade()` | Same context (chat continuation) | `linearTiming({ durationInFrames: 4 })` or `springTiming({ config: { damping: 200 }, durationInFrames: 8 })` |
| `slide({ direction: "from-bottom" })` | New content entering | `springTiming({ config: SPRINGS.natural, durationInFrames: 12 })` |
| `slide({ direction: "from-right" })` | Next chapter / progression | Same as above |
| `wipe({ direction: "from-left" })` | Hard scene change | `springTiming({ config: { damping: 200 }, durationInFrames: 12 })` |
| `slide({ direction: "from-top" })` | Rare, dramatic reveal | Same as above |

**Rule**: Vary direction to avoid monotony. Alternate slide/wipe/fade. Fades are silent (no whoosh). Slides/wipes get whoosh SFX.

---

## 11. Sound Sync

Sync SFX with animation keyframes using `<Sequence>`:

```tsx
// Whip on each word beat
{WORDS.map((word) => (
  <Sequence key={word.startFrame} from={word.startFrame}>
    <Audio src={SFX.whip} volume={0.55} />
  </Sequence>
))}

// uiSwitch when cards pop in
<Sequence from={CARD_DELAY}>
  <Audio src={SFX.uiSwitch} volume={0.22} />
</Sequence>

// Whoosh on scene enter (slide/wipe transitions)
<Sequence from={0}>
  <Audio src={SFX.whoosh} volume={0.3} />
</Sequence>
```

**Volumes**: whip `0.5-0.6`, whoosh `0.25-0.35`, uiSwitch `0.2-0.4`, mouseClick `0.15`.

---

## 12. Exit Animations

Scenes should animate out for seamless transitions:

```tsx
// Calculate exit progress (start exit 15 frames before scene ends)
const exitStart = durationInFrames - 15;
const exitP = spring({
  frame: frame - exitStart,
  fps,
  config: { damping: 200 },
});
const exitOpacity = interpolate(exitP, [0, 1], [1, 0]);
const exitScale = interpolate(exitP, [0, 1], [1, 0.97]);

<AbsoluteFill style={{
  opacity: exitOpacity,
  transform: `scale(${exitScale})`,
}}>
```

**Rule**: Not all scenes need exits. Fade transitions handle it. But static scenes (just text) benefit from a subtle scale-down exit.
