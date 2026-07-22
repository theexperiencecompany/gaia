---
name: remotion-motion-design
description: Produce Apple-grade motion design videos for GAIA with Remotion — story-first, beat-synced, fully sound-designed, in GAIA's design language, hardened by an adversarial multi-agent evaluation loop. Use when the user asks for a product video, launch video, promo, brand film, motion design, or any Remotion work. Never render-and-ship in one pass; the evaluation loop is mandatory.
version: 1.0.0
user-invocable: true
argument-hint: "[video idea or brief]"
---

# Remotion Motion Design — GAIA

You are directing a brand film, not generating a video. The bar is "could ship on apple.com." Everything below exists because the default output of an LLM asked to "make a video" is slop: linear easings, silent renders, uniform durations, generic layouts, no story. This skill is the anti-slop machine.

## Non-negotiables

1. **Story before pixels.** No composition code until a beat sheet exists and (when the user is reachable) the director's interview has been asked.
2. **Sound is half the film.** Music + SFX + (usually) VO in every video. A silent render is an unfinished render.
3. **Everything on the beat grid.** Measure the real BPM of the chosen track; every cut lands on `round(N × fps × 60 / bpm)`.
4. **GAIA design language throughout** — fonts, colors, motion fingerprint. See `references/design-language.md`.
5. **Adversarial evaluation before shipping.** Fresh evaluator agents, one lens each, hostile by instruction. Ship gate: every lens ≥8/10. See `references/evaluation-rubric.md`.
6. **Iterate until it passes.** Two failed iterations on the same lens = rebuild the scene, don't nudge values.

## References (read before the corresponding phase)

| File | Read when |
|---|---|
| `references/storytelling.md` | Phase 1 — script, hooks, beat sheets, director's interview questions |
| `references/design-language.md` | Phase 2 — GAIA fonts/colors/motion tokens, asset paths, brand voice |
| `references/apple-motion-rules.md` | Phase 2–3 — scene structure, typography-in-motion, transition grammar, prohibitions |
| `references/motion-craft.md` | Phase 3 — quantified transitions, kinetic type, easing library, rhythm math, anti-slop checklist |
| `references/remotion-technique.md` | Phase 3 — Remotion idioms, springs, TransitionSeries, fonts, render pipeline, determinism |
| `references/audio.md` | Phase 2–4 — verified SFX/music sources, VO (edge-tts + ElevenLabs), mix targets |

## Workflow

### Phase 0 — Setup

Scaffold outside the repo (scratchpad or a dedicated dir): `pnpm add remotion @remotion/cli @remotion/transitions @remotion/media-utils @remotion/fonts @remotion/google-fonts @remotion/noise @remotion/motion-blur @remotion/layout-utils react react-dom @types/react typescript@5` — **TypeScript 5.x, all @remotion/* versions identical**. In GAIA cloud containers, `remotion.config.ts` needs `Config.setBrowserExecutable('/opt/pw-browsers/chromium')` + `Config.setChromeMode('chrome-for-testing')`. Verify with a 10-frame smoke render before real work. Copy brand assets (logo SVG, wordmark, fonts, wallpapers) from `apps/web/public/` and `apps/web/src/app/fonts/editor-new/` into the project's `public/`.

### Phase 1 — Story (read `storytelling.md`)

1. If anything material is unknown, ask the **director's interview** questions (max 4, highest-impact first, via AskUserQuestion). If the user is unreachable, state assumptions explicitly and proceed.
2. Write 10+ hook candidates; pick the sharpest.
3. Pick the narrative structure by audience awareness; write the **beat sheet**: every scene with start/end seconds, on-screen copy (≤6 words/line), VO line, visual, transition type, SFX. The reveal lands by 15–20s on the music drop. One workflow shown deeply. Human stays hero and approver in agent narratives.
4. Write the VO script — short sentences, calm, specific numbers. On-screen text paraphrases VO, never transcribes it.

### Phase 2 — Assets before code

1. **Music first** (it dictates the grid): search per `audio.md`, download 2–3 candidates, listen/inspect, pick one, **measure its real BPM**, then quantize the beat sheet's scene boundaries to whole beats/bars.
2. SFX per the beat sheet's vocabulary table (whoosh/tick/riser/boom/shimmer) from verified sources.
3. VO: generate with edge-tts (free; AndrewMultilingualNeural, rate −5..−10%) or ElevenLabs (`eleven_multilingual_v2`) if `ELEVENLABS_API_KEY` is set. Get word timings (SRT / with-timestamps) and let VO duration drive scene durations where they conflict — J-cut audio across scene changes.
4. Brand assets + fonts loaded via `@remotion/fonts` / `@remotion/google-fonts` (restrict weights).

### Phase 3 — Build (read `apple-motion-rules.md`, `motion-craft.md`, `remotion-technique.md`)

- One file per scene; a `brand/` module for tokens (colors, easings, spring presets — 3–5 easing presets total, never per-scene curves); a `beat.ts` exporting `bpm`, `fpb`, `beat(n)` helpers; total duration computed in one place.
- **Motion design, not UI design**: every scene is type-led — a giant statement (90–150px) as the hero, product components as large supporting evidence (cards ~1000–1300px wide at 1920, inner type ≥28px). No uppercase+letter-spacing labels, no detached section headings, no decorative wallpapers/photos — atmosphere comes from light and motion. See `design-language.md` § Motion design, not UI design.
- Scene grammar: entrance settles in first 30–40% → **hold** (only slow push-in scale 1.00→1.045) → cut on beat. Staggered entrances (2–4f), one focal point, safe areas, 40–60% negative space.
- Transitions: ~80% hard cuts on the grid; match cuts / shared elements / z-pushes at chapter changes only; momentum carried across cuts; never crossfade between ideas.
- Type: house blur-in default, masked line reveals for hero statements, ONE hero effect per video, hold-time formula respected. Serif is banned in video (see design-language.md).
- UI mockups: real product surfaces (GAIA chat cards, WhatsApp thread, inbox) with plausible copy, timestamps, names — zoomed and cropped, never full screenshots with tiny text. Cursors move on smooth beziers and vanish when automation takes over.
- Audio layered in Remotion: music with fade envelope, each SFX in a `<Sequence from={hit}>`, VO ducking music −7..−12 dB via volume callbacks.
- Determinism: pure function of `useCurrentFrame()`; `random(seed)` only; `<Img>`/`<OffthreadVideo>`; fonts via blocking loaders; premount heavy scenes.

### Phase 4 — Render + verify mechanically

- Draft iterations: `npx remotion render Main out/draft.mp4 --frames=...` (jpeg q80).
- Before evaluation: full render + export **boundary triplets** (frames N−2..N+2 at every cut) and a 2fps contact sheet; run `npx remotion ffmpeg -i out.mp4 -af loudnorm=print_format=summary -f null -` for loudness; self-check the mechanical items (cuts on grid, hold ratios, word counts, safe areas) before wasting evaluator passes.
- Final master: `--crf=15 --image-format=png --color-space=bt709 --x264-preset=slow` (add `--scale=2` for 4K deliverables).

### Phase 5 — Adversarial evaluation loop (read `evaluation-rubric.md`)

Spawn parallel hostile evaluator agents — one per lens (transitions/rhythm, typography, layout/whitespace, motion physics/slop tells, brand fidelity, audio, story/virality) — each given the rendered frames/audio evidence, each instructed to refute quality and score 1–10. Collect defects → fix root causes → re-render → re-evaluate changed lenses. Ship only at every-lens ≥8 with zero illusion-breaking defects. Keep an iteration log; fold durable lessons back into this skill's references.

### Phase 6 — Deliver

Ship the MP4 (+ a 9:16 or square recut if requested — recompose layouts, don't letterbox). Report: final duration, music/SFX provenance + licenses, VO voice used, loudness numbers, evaluation scores per lens, and what changed per iteration.
