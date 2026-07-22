# Reference Films — Studied Frame-by-Frame

Techniques harvested from premium launch films (fetched and frame-stepped, not imagined). Study new references the same way before every major film.

## How to fetch reference videos (verified method)

```bash
uv tool install yt-dlp                       # → ~/.local/bin/yt-dlp
yt-dlp -o 'ref1.%(ext)s' 'https://x.com/i/status/<ID>'   # plain x.com URL works, no cookies/args
# Frame extraction — the bundled remotion ffmpeg has NO -vf filter support; use output flags:
cd <remotion-project> && npx remotion ffmpeg -y -i ref1.mp4 -r 2 -s 640x360 -c:v png refs/ref1_%03d.png
```
Then Read 20–30 frames per film and write a beat table (time, beat, technique) before borrowing anything.

## The launch-structure template (Harshit/@HarshitVisuals — proven for AI product launches)

**Intro → Statement → Proof → Statement → Proof → Style Range → Outro → Brand Reveal**

- **Start plain. Just introduce the product** ("Meet X. What it is in one line."). Confusion in the first act kills everything after.
- **Claim, then immediately show it happening — real output, no staging.** Then a second claim + proof. "A single claim sounds like marketing; watch it happen twice and it starts to feel like fact."
- Show range with the same output in multiple styles rather than one result.
- Ease into the outro. **Save the brand reveal for LAST — it's the thing people leave with.** (Logo/wordmark is the final held frame, not the opener of the close.)
- The repetition pattern is what people remember, not the pitch.

## Film 1 — "Infinite" fintech launch (30s, dark stage)

- **Dark stage + volumetric light IS the look**: black bg, perspective grid floor, radial spotlight, light pillars/cones — all CSS gradients + perspective transforms.
- **Chrome/metallic type**: gradient brightness sweep travelling across letters; end-card holds a static mid-sweep.
- **Transitions are velocity, not cuts**: camera z-pushes THROUGH oversized text; scene exits via horizontal motion-blur streak (trailing translated+blurred copies); dive INTO a product screenshot as a scene bridge.
- **Comet along a path**: bright dot + fading tail travelling SVG paths, igniting nodes as it passes — one signature device reused 3 ways (grid, circuit, dashed route).
- **Accent-color-per-feature** on a shared hub (rotating wheel; one segment + one panel adopt each feature's color).
- Pacing: ~14 beats/30s (≈2.1s avg), single-word cards ~1.5s, end card holds 5s with subtle grain.

## Film 2 — OpenAI "Codex" (28s, light)

- **Blur is the transition language**: rack-focus in/out on words, zoom-blur bursts, trailing words fall out of focus mid-sentence.
- **Match-cut world-switch**: the same word ("software") in terminal mono → product sans across a hard cut — the cheapest, fastest before/after that exists.
- **Icons live inside sentences**: the logo glyph and a mic icon are grammatical words in the copy. The brand mark participates in language before it's revealed.
- **One deliberate glitch as wit** (`sp)ak` — one wrong glyph, not noise).
- **Macro cinematography of UI**: input pill, cursor, and send button filmed like physical objects at 5–10× with real hover states and an oversized stylized cursor. UI is never a flat screenshot until the deliberate burst montage.
- **Logo choreography earns the end card**: pulse rings → bouncing companion beside the copy → morph into the app icon → wordmark.
- Photographic backdrop appears ONLY at the product/brand moments — the register jump is the reveal.

**Shared DNA of both:** type-on word staggers everywhere; the camera never stops (push/orbit/dive); blur = transition; one accent per beat; UI shown macro or dived-into, never pasted; end card = icon + wordmark + tagline + URL, long hold.

## Apple-design skill (Emil Kowalski) — shipping values

- Default UI spring: **critically damped (1.0), response 0.3–0.4s, zero overshoot.** Bounce (damping ~0.8) ONLY when the gesture itself carried momentum. Apple's shipped pairs: move 1.0/0.4 · rotation 0.8/0.4 · drawer 0.8/0.3.
- Press feedback: `scale(0.97)`, 100ms ease-out, on pointer-DOWN.
- **Spatial consistency**: things exit the way they entered; anchor transform-origin at the trigger; mirror easing on reversals.
- **Hinting**: in-between frames should point at the outcome, not blindly interpolate.
- **Materialize, don't fade**: animate blur radius + scale together so glass arrives as material.
- Tracking is size-specific (display −0.02em/1.05; body ~0) — never one value for all sizes.
- **Multimodal same-frame rule**: visual + sound must land on the SAME frame; feedback only at meaningful moments — "over-feedback trains users to ignore all of it."
- Review process: "play it in slow motion / frame-by-frame to catch what's invisible at full speed."
