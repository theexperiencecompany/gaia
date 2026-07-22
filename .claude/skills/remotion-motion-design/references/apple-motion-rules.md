# Apple-Grade Motion Rules

Reproducible rules distilled from WWDC motion talks, frame-level breakdowns of Apple keynote films ("Don't Blink"), and reverse-engineered apple.com tokens. Timings in ms and frames @30fps. These compose with GAIA's design language (`design-language.md`) — where they conflict on brand specifics (colors, fonts), GAIA wins; on motion physics and rhythm, these win.

## A. Easing & physics (the single biggest quality lever)

1. **Default entrance easing = strong ease-out**: `cubic-bezier(0.16, 1, 0.3, 1)`. (GAIA's house `cubic-bezier(0.22, 1, 0.36, 1)` is the same family — use GAIA's.)
2. **Never `ease-in` for entrances.** Slow start reads sluggish.
3. **Never linear easing for positional motion** — the #1 amateur tell. Linear IS correct for exactly two things: opacity/color blends, and constant-motion loops (marquees).
4. Elements that MOVE within the frame (not enter/exit) use `ease-in-out`.
5. **Springs: critically damped.** Apple default UI motion ≈ damping ratio 1.0, response 0.3–0.4s. Remotion: `spring({frame, fps, config: {damping: 200}})`. Marketing-video elements never visibly oscillate more than one overshoot. Bounce is for gesture UIs, not product films.
6. **Duration bands**: micro-accent 100–150ms (3–5f) · standard entrance 200–300ms (6–9f) · hero/headline 400–600ms (12–18f) · full-frame transition 500–800ms (15–24f). Nothing UI-scale over ~800ms except camera drift.
7. **Vary durations by element size/travel distance.** Uniform durations across all elements = amateur tell. Bigger elements / longer travel → longer duration (one band step).
8. **Exits ≈ 2/3 the entrance duration**, ease-out, fade-dominant. Entrance 12f → exit 8f.
9. **Animate only `transform` and `opacity`** (+ `filter: blur` sparingly). Never layout properties.
10. **Compress the action**: keyframes clustered so the move happens fast, then spends most of its time settling.

## B. Typography in motion

11. Two sizes per scene, maybe three. **Hero-to-support ratio ≥ 2.6:1** (e.g. 96px headline + 28px tagline). Skip intermediate sizes.
12. **1–7 words on screen. One idea per scene.** A frame must be graspable in 3 seconds.
13. Display type: `letter-spacing: -0.02em` (scale with size), line-height 1.05–1.1. Body: tracking 0, line-height ≥1.47.
14. **The text entrance recipe** ("the Apple reveal"): opacity 0→1 + translateY 12–24px→0 + optional `blur(8px)→0` and/or scale 0.96→1, over 12–18f with the house ease. Scale grows from an anchored origin, not center-symmetric pop.
15. **Stagger, don't chorus.** Multi-element reveals cascade at **2–4f (60–120ms) offsets**, same direction, same easing. Everything-at-once = amateur tell.
16. Optional signature accent (≤1 per video): animate tracking, e.g. letter-spacing −0.06em→−0.02em during a hero reveal.

## C. Color & space

17. Backgrounds are absolutes — near-black or white, never mid-gray, never decorative gradients. (GAIA: `#111111` / `#09090b`.)
18. One accent color max. No drop shadows on text.
19. **Empty space is the layout.** Content occupies the center ~60% of frame. A single centered headline with nothing else is a preferred scene.
20. Bento/summary scenes: asymmetric grid, one dominant tile, 3–4 small tiles; hierarchy enforced by **tile area, not font size**; each tile exactly one idea; animate in with 2–3f stagger, largest first.

## D. Scene structure, shot lengths, rhythm

21. **One idea per scene, hard limit.** The video is a list of claims; each claim gets its own scene.
22. **Scene length bands @30fps**: kinetic-type beat (one word) 6–12f · standard claim scene 60–105f (2–3.5s) · hero reveal/beauty shot 105–150f (3.5–5s). Nothing between 12f and 45f — a scene is either a beat or a statement.
23. **Motion → hold → cut.** Entrance animation finishes in the first ~30–40% of the scene, then the frame HOLDS (only slow camera drift) until the cut. Constant motion the whole scene = AI slop.
24. **Pace: fast–slow–fast.** Alternate rapid sequences with sudden slowdowns; insert a full-stop "breath" scene (long hold, near-empty frame) before the product reveal.
25. Kinetic-type mode: one word per 5–7 frames (~300wpm), one/two-syllable words, one at a time, every swap on a beat subdivision.
26. **Cut on the beat.** `framesPerBeat = fps * 60 / bpm`; quantize every scene boundary to it. Kinetic sections cut every beat/half-bar; statement scenes every 2–4 bars.
27. **Continuation of movement across cuts**: if the frame is moving at the cut, the next shot moves in the same direction at matched speed — carry a velocity vector across Sequence boundaries.
28. **Transition types — use exactly these**:
    - Hard cut on beat (default, ~80% of transitions)
    - Match cut / morph — outgoing and incoming share a shape/position (Apple's signature)
    - Light/flash or pass-through-object wipe — camera pushes into a region that becomes the next scene
    - **Cross-dissolve: never** between statement scenes. No slide-wipes, no spins, no 3D flips.
29. **One slow push-in per statement scene**: scale 1.00→1.03–1.06 over the whole scene — imperceptible drift keeps frames alive. Parallax layers (foreground ~1.5× background).
30. Motion stays 2D except **one deliberate z-space moment per video**.
31. **Motion must be motivated by meaning.** "Faster" moves fast; a number counts up; "thin" compresses. If a movement has no semantic or spatial reason, replace it with a fade.
32. Macro-structure: cold-open hook (fast, kinetic, 10–20% of runtime) → name reveal on black (breath) → 3–5 feature statements → bento summary → closing logo + tagline hold (≥60f).

## E. Hard prohibitions (the amateur tells)

Banned outright: linear position easing · ease-in entrances · simultaneous entrances · uniform durations everywhere · center-symmetric scale-from-zero pops · cross-dissolves between ideas · unmotivated motion · mixed entrance directions within a scene · >7 words on screen · decorative gradients & text drop shadows · Unicode arrows/bullets as graphics · second accent color · visible bounce on non-gestural elements · scenes where something is always moving · cuts off the music grid.

## F. Remotion encodings

```ts
const EASE = Easing.bezier(0.22, 1, 0.36, 1); // GAIA house ease, Apple family
// tween durations: micro 4f, standard 8f, hero 15f, transition 18f
spring({frame, fps, config: {damping: 200}}); // critically damped hero moves

// The reveal
opacity: interpolate(f, [0, 12], [0, 1]),
transform: `translateY(${interpolate(f, [0, 15], [20, 0], {easing: EASE})}px)`,
filter: `blur(${interpolate(f, [0, 10], [8, 0])}px)`,
// children staggered delay = i * 3 frames

// Scene push-in
scale = interpolate(frame, [0, durationInFrames], [1, 1.045]);

// Beat grid
const framesPerBeat = (fps * 60) / bpm; // every Sequence boundary a multiple
```

**Verification pass**: step the render frame-by-frame at scene boundaries and check — every cut on a beat frame; no element mid-tween at a cut unless velocity is matched across it; holds ≥50% of each statement scene.
