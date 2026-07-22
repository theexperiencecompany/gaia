# Remotion v4 Cinema-Quality Playbook

Verified against remotion.dev docs (4.0.x line). All `remotion` and `@remotion/*` packages MUST be the exact same version — mismatches cause cryptic breakage.

## Springs & interpolation

```tsx
const value = spring({
  frame, fps,                       // always from useCurrentFrame()/useVideoConfig()
  config: {mass: 1, damping: 10, stiffness: 100, overshootClamping: false},
  delay: 15,                        // frames — preferred over `frame - 15`
  durationInFrames: 40,             // stretch curve to exact length
});
```

Feel presets:
```tsx
const SMOOTH  = {damping: 200};                            // the professional default, no overshoot
const SNAPPY  = {damping: 20, stiffness: 200, mass: 0.5};  // quick with a hint of life
const BOUNCY  = {damping: 8, stiffness: 100, mass: 1};     // playful — rarely for product films
const HEAVY   = {damping: 30, stiffness: 40, mass: 2};     // cinematic slow settle
```

Map spring 0→1 onto properties via `interpolate(driver, [0,1], [from,to])`. Use `measureSpring({fps, config})` to know settle duration for sequencing.

**Critical idiom**: `interpolate` default extrapolation is `extend` → negative opacity/overshoot outside the range. Always pass `extrapolateLeft/Right: 'clamp'`. Multi-keyframe accepts per-segment easing arrays. `{output: 'perceptual-scale'}` makes scale animations feel linear to the eye.

Workhorses: `Easing.out(Easing.cubic)` entrances · `Easing.bezier(0.22,1,0.36,1)` title reveals (GAIA house) · `Easing.inOut(Easing.ease)` camera moves.

## @remotion/transitions

```tsx
<TransitionSeries>
  <TransitionSeries.Sequence durationInFrames={90}><SceneA/></TransitionSeries.Sequence>
  <TransitionSeries.Transition
    presentation={fade()}
    timing={springTiming({config: {damping: 200}, durationInFrames: 30, durationRestThreshold: 0.001})}
  />
  <TransitionSeries.Sequence durationInFrames={120}><SceneB/></TransitionSeries.Sequence>
</TransitionSeries>
```

- **Duration math: transitions overlap** — total = sum(sequences) − sum(transitions). Compute total in ONE place.
- `durationRestThreshold: 0.001` on springTiming or the transition visibly cuts off.
- Built-ins (each from its own subpath): `fade`, `slide`, `wipe`, `flip`, `clockWipe`, `iris`, `none` (for audio-only/custom via `useTransitionProgress()`), plus newer `linearBlur`, `zoomBlur`, `dissolve` etc.
- **Custom presentation** = `{component, props}`; component receives `presentationProgress`, `presentationDirection` (`entering`/`exiting`), `children`. For seamless match-cut feel animate BOTH sides: exiting scales up + blurs out while entering scales 1.2→1, same progress. `clipPath: inset(...)` is the cleanest masked reveal.
- Hard cuts don't need TransitionSeries — plain `<Series>` with beat-quantized durations.

## Audio

```tsx
<Audio
  src={staticFile('music.mp3')}
  volume={(f) => interpolate(f, [0, FADE, dur - FADE, dur], [0, 0.55, 0.55, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}
  trimBefore={2 * fps}   // FRAMES (replaces startFrom)
  trimAfter={30 * fps}
/>
```

- `volume` callback runs per frame; `f` is relative to mount (post-trim). Shape fades exponentially (`Math.pow(linear, 2)`) — linear gain fades sound front-loaded.
- Layer music + SFX + VO as multiple `<Audio>` tags positioned with `<Sequence from={hitFrame}>`; Remotion mixes additively — **no normalization/limiting**, so keep summed peaks < 1.0.
- Practical levels: VO ~1.0, music bed 0.10–0.25 under VO (duck via volume callback keyed to VO segments), 0.4–0.6 without VO, SFX 0.4–0.7. Target ≈ −14 LUFS integrated; pre-normalize sources rather than pushing volume > 1.
- Visualization: `useAudioData(staticFile(...))` (null until loaded) + `visualizeAudio({fps, frame, audioData, numberOfSamples: 16})`.

## Fonts (no FOUT if done right)

- Google fonts: `import {loadFont} from '@remotion/google-fonts/Inter'` at module top level — **always restrict weights + subsets** or renders can time out.
- Local: `@remotion/fonts` `loadFont({family, url: staticFile('x.woff2'), weight, style})` — blocks render until ready.
- `await waitUntilDone()` before `measureText`; pass `validateFontIsLoaded: true` (`@remotion/layout-utils`) or measurements silently use the fallback font.
- `fitText({text, withinWidth, ...})` finds the fontSize that fits a box.

## Text animation idioms

Per-word stagger (canonical):
```tsx
{words.map((word, i) => {
  const p = spring({frame, fps, config: {damping: 200}, delay: i * 3, durationInFrames: 25});
  return <span key={i} style={{display: 'inline-block', opacity: p,
    transform: `translateY(${interpolate(p, [0, 1], [30, 0])}px)`}}>{word}</span>;
})}
```
- Masked line reveal: outer `overflow: hidden`, inner `translateY(100%→0)`; optional slight `rotate(3deg→0)` for editorial feel.
- Blur reveals: fine for renders (`filter: blur`) but keep blurred regions small and round the blur value. Glow = blurred duplicate layer, never `text-shadow` spread animation.
- Splitting must be deterministic; char splits need `whiteSpace: 'pre'`.

## Visual quality

- `<CameraMotionBlur shutterAngle={180} samples={8}>` — true multi-sample blur for fast moves (children must be absolutely positioned; samples multiply render cost). `<Trail>` for echo trails.
- `@remotion/noise`: `noise2D('seed', frame * 0.01, 0) * 15` — deterministic organic drift (handheld camera feel).
- **Render at `--scale=2`** (deviceScaleFactor) — design at 1080p, deliver 4K; the single biggest sharpness win.
- Max-quality recipe: `npx remotion render Main out.mp4 --crf=15 --image-format=png --color-space=bt709 --x264-preset=slow --scale=2`. Iterating: default jpeg q80 + `--frames=0-119` partial renders.
- Avoid `background-image`/`mask-image` with URLs (can screenshot mid-load) — use `<Img>` layers or data URIs.
- 30fps + shutterAngle-180 reads "filmic"; 60fps reads "product-demo crisp." Never hardcode frame counts against an assumed fps — always `seconds × fps`.

## Structure

- `AbsoluteFill` = the layer primitive; later siblings paint on top.
- `<Sequence from durationInFrames>` restarts `useCurrentFrame()` at 0 inside — what makes scene components reusable. `<Series>` auto-stitches; negative `offset` overlaps.
- **Premount heavy scenes**: `<Sequence premountFor={30}>` mounts early, invisible and time-frozen, so assets load before appearing — fixes first-frame pops.
- `calculateMetadata` for dynamic duration (e.g. from VO audio length) and pre-fetched props — better than `delayRender` in components.
- Scene list pattern: `const SCENES = [{Component, duration}...]`; compute total duration (minus transition overlaps) in one place.

## Rendering in this environment (battle-tested)

- System Chromium: `Config.setBrowserExecutable('/opt/pw-browsers/chromium')` + **`Config.setChromeMode('chrome-for-testing')`** (modern Chromium has no old-headless mode; without this the browser fails to launch).
- **Fonts: embed as base64 data-URIs in a CSS file** (`@font-face { src: url(data:font/woff2;base64,...) }`, `font-display: block`) imported by the root — the `@remotion/fonts`/`@remotion/google-fonts` network loaders flake under parallel tabs behind the container proxy (delayRender timeouts on respawned tabs mid-render; Google Fonts fetches also fail on cert). Data-URIs cannot hang. Get woff2s from the repo (`apps/web/src/app/fonts/`) and `@fontsource/*` packages (copy the files out, then remove the dep).
- No system ffmpeg — Remotion bundles it: `npx remotion ffmpeg`, `npx remotion ffprobe`. The bundled build has **no image encoders and a broken null video path** — for audio analysis always pass `-vn` (e.g. `-vn -af loudnorm=... -f null -`); for evaluation frames don't use ffmpeg, render an image sequence: `npx remotion render Silent out/frames --sequence --image-format=jpeg --scale=0.5`.
- Check core count before setting `--concurrency` (cloud containers often have 4; concurrency above cores is a hard error).
- TypeScript must be v5.x (Remotion's webpack loader breaks on TS 6/7: `typescript.sys` undefined).
- **Beat-phase measurement**: BPM alone isn't enough — find a real downbeat near the desired music start (onset flux + autocorrelation at the beat period, pure python on decoded wav works) and set `trimBefore` to that exact time so beat(0) of the film lands on a beat of the track.

## Determinism pitfalls (flicker)

Renders run in multiple parallel tabs; frames render out of order. Every component must be a pure function of `useCurrentFrame()`:
- Banned: CSS `transition`/`animation`/`@keyframes`, `requestAnimationFrame`, `setTimeout`, `Date.now()`, `Math.random()`, animated GIF `<img>` (use `@remotion/gif`), state accumulated across frames.
- `import {random} from 'remotion'` — `random('seed-' + i)` for deterministic randomness.
- Use `<Img>`, `<Audio>`, `<OffthreadVideo>` (never `<Video>` for footage), `<Gif>` — they block the screenshot until loaded.
- Audio drift: express trims in frames from fps; re-encode VFR sources to CFR (`npx remotion ffmpeg -i in.mp4 -vsync cfr -r 30 out.mp4`).

## Tailwind verdict

Tailwind (via `@remotion/tailwind-v4` + webpack override) is fine for static styling, but every animated value must be inline `style={{}}` computed from `useCurrentFrame()` anyway — Tailwind `transition-*`/`animate-*` utilities are exactly the time-based CSS the flicker rules ban. For video projects, **pure inline styles** are simpler and are the recommended default here.
