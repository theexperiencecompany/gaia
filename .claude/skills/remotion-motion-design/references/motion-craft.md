# The Motion Craft Rulebook

## The film grammar (non-negotiable structure)

These rules exist because their violations are exactly what makes generated films read as "posters with titles":

1. **Kinetic typography is the storytelling engine.** Statements arrive centered, one phrase at a time, replacing each other on the beat — Apple keynote-film style. The signature letterform behavior: per-word (per-char for hero words) blur-in + rise + slight scale settle (1.05→1), whole-phrase tracking contraction (−0.055em→−0.035em) as it lands; exits breathe out (blur up + drift). Build ONE `KineticPhrase` primitive and use it for every statement — a per-scene one-off entrance is a defect.
2. **Titles morph; they don't sit.** A statement lands huge (150–210px), then MORPHS — shrinks and glides into a header position — to hand the stage to evidence below. The morph (`scale` + `translateY` on the same element, transform-origin bottom) IS the transition between "type moment" and "evidence moment." Never a static heading floating above a card.
3. **The film needs a persistent spine.** At least one shared element must live OUTSIDE the scene sequence and persist across every cut (a clock that docks and rolls, an accumulating dock of finished work, a light ramp, a recurring glow). Scene components render content only; connective tissue is global. Without a spine, six scenes = six posters.
4. **Morphing is the seam language.** Prefer transformation over replacement everywhere: cards compress into chips that fly into the next surface, a giant element becomes a small persistent one, digits roll in place. Every seam should answer "what did the last thing BECOME?"
5. **Vary the composition.** Alternate layout structures across beats (offset cards left/right, let a number be the hero without chrome, split type/evidence). Two consecutive scenes with identical layout geometry is a defect; five is slop.
6. **Layout jumps are illusion-breakers.** Any state change inside a surface (typing dots → message text, button → sent state) must reserve its final layout space and crossfade — a single-frame DOM reflow is the loudest amateur tell there is.
7. **Composite accents.** A beat event (approval, send, land) is ONE 10-frame composite — state flip + subtle surface flash (≤4% white) + settle — landing exactly on the beat frame. Never a color swap on the beat plus stray motion 15 frames later.
8. **Counters** decrement on nearly every frame: piecewise `[linear → ease-out]` keyframes (e.g. [0, 0.8, 1] → [47, 8, 3]) — a plain ease-out makes the tail judder at half frame rate.
9. **Typing must be human**: per-character delays with seeded jitter (1.4–3.2f range) and pauses after punctuation (+5f). `setInterval`-even cadence reads robotic. Cursor caret blinks; composer restores its placeholder after send.


Professional motion-graphics editing craft (School of Motion, Carbon/Material motion specs, Emil Kowalski, Stripe/Linear/Vercel breakdowns), quantified for code. Frame counts @30fps. Where a rule conflicts with GAIA brand specifics (e.g. grain — GAIA is clean/flat, skip heavy grain), `design-language.md` wins.

## A. Scene-to-scene transitions

1. **Default to the hard cut, on the beat.** Reserve "fancy" transitions for scene-role changes (new chapter/idea). Every-transition-a-different-effect reads amateur.
2. **Momentum continuity (cut on action):** if an element travels over a 12f move and you cut at frame 6, the incoming shot picks up equivalent motion at frame 7 — same direction, same velocity. Never cut to a static frame from a moving one.
3. **Match cut:** align a shape/position/scale/motion-vector in the last frame of A with the first frame of B (circle logo → circle chart at identical x/y/radius). Zero overlap; the alignment IS the transition.
4. **Morph:** interpolate one shape into another, 12–21f, ease-in-out. For logo reveals and "one continuous thought."
5. **Whip pan: 10 frames total** — offset 5f before the cut and 5f after, both scenes sliding the same direction; directional blur ramping 0 → ~40px → 0, peaking exactly at the cut frame. Ease-in on exit, ease-out on entry.
6. **Invisible cut:** hide the cut behind (a) a foreground object crossing the full frame, (b) a whip pan's blur peak, (c) a pass through darkness, or (d) a z-push into an element that fills the frame. Swap scenes at full occlusion.
7. **Z-depth push-through:** scene A scales 100%→300–800% while fading/blurring over 15–25f; scene B scales 85–90%→100% underneath, ease-out. The camera "flies through" an element (device screen, a letter's counter, a circle).
8. **Shared-element transition** (the Stripe/Linear signature): one persistent element (logo, card, headline) survives the cut and animates to its new position/scale over 15–21f while everything else swaps around it.
9. **Mask/wipe:** animate `clip-path` (inset/circle) 15–24f ease-out-expo; wipe direction matches the incoming scene's dominant motion. Plain crossfade between two busy scenes: never (dissolves are only for time passage/montage).
10. **Background continuity:** keep background constant (or smoothly interpolating) across cuts within a chapter; change background only at chapter boundaries. This alone makes cuts feel like one continuous piece.
11. **J-cut / L-cut for VO:** bring the next scene's audio in 0.5–2s before its video (J) or let audio linger after (L). Start at 1.0s overlap. Never cut audio and video on the same frame in narrated content.

## B. Kinetic typography

12. Animate by the right unit: characters = hero words only; words = sentences; lines = multi-line statements.
13. Per-character stagger: 30–50ms (1–1.5f). 100ms+/char only on ≤2-word heroes.
14. Per-word/element stagger: 50–150ms (1.5–4.5f). Left-to-right = reading guidance; center-outward = pulls eye to a focal word.
15. **Masked line reveal (the premium default):** wrap each line in `overflow: hidden`; translate from y:100% (of line height) to 0 over 15–21f ease-out-expo; lines staggered 80–120ms. No opacity fade needed.
16. **Blur-up reveal** (GAIA's house move): opacity 0→1, blur 12px→0, y+16→0, ~18f ease-out, words staggered 60–100ms. Never combine with bounce.
17. Tracking expansion: letter-spacing −3%→0 over 24–36f ease-out-quint, under an opacity fade. If the viewer sees letters move, it's too much.
18. **Hold-time formula: `hold_s = 0.9 + 0.24 × word_count`**, floor 1.5s for hero lines, max display rate 17 chars/second.
19. Max ~6 words per animated statement. Two clauses = two scenes.
20. **One hero effect per video.** Most text enters with the house reveal; the single most important line gets the elaborate treatment. Restraint is the pro tell.
21. Only animate `transform`, `opacity`, `clip-path`, `filter` on text. Never `font-size`, layout, or per-frame `color`.
22. **Cheap-text ban list:** typewriter on body copy, per-character rotation, bounce on every line, scale-from-0%, no-stagger chorus entrances, reveals slower than reading speed.

## C. The 12 principles, quantified

23. **Anticipation:** before a major move, shift 2–4% opposite for 10–20% of the duration. Hero moves only.
24. **Overshoot: 3–8% past target, ONE bounce** (scale 0→1.05→1.0). Amplitude matches incoming velocity — slow moves get zero overshoot. Multi-bounce reads cartoonish.
25. **Follow-through via lag:** child elements trail their parent by 2–4f. Nothing arrives all at once.
26. **Timing = weight:** chips/badges 150–250ms; full panels 400–700ms. Further/larger → longer.
27. **Arcs:** elements moving in x and y follow a curved path (offset the x/y easings so the path bows). Straight diagonals read mechanical.
28. **Secondary action:** every hero move gets exactly one supporting motion at 20–40% of the hero's amplitude. Never a competing second hero.
29. **Staging:** one focal animation at a time. A simultaneous second mover must be ≤30% of the hero's visual energy.
30. Squash & stretch: ≤3% deformation, playful brands only. Zero for GAIA's premium tone.

## D. Easing library (tokens)

31. **Master rule: fast start, slow settle.** Entrances = ease-out. On-screen repositioning/morphs = ease-in-out. **Ease-in banned** except permanent exits. Linear only for marquees/spinners/progress.
32. Core set:
    - `ease-out-expo` `cubic-bezier(0.16, 1, 0.3, 1)` — hero entrances, masked reveals
    - `ease-out-quint` `cubic-bezier(0.22, 1, 0.36, 1)` — standard entrances (GAIA house ease)
    - `ease-in-out-quint` `cubic-bezier(0.83, 0, 0.17, 1)` — on-screen moves, morphs
    - Material emphasized-decelerate `cubic-bezier(0.05, 0.7, 0.1, 1)` — alternative entrance
33. **Duration hierarchy:** micro 70–150ms · component 240–400ms · scene/panel 400–700ms · hero/camera 800–1200ms. Larger change = longer, always. **Standardize 3–5 presets per project — never invent a new curve per scene.**
34. **Remotion springs:** premium settle `{damping: 200}` (no bounce); tasteful pop `{damping: 12–15, stiffness: 100–170, mass: 1}`. In `springTiming()` set `durationRestThreshold: 0.001` so transitions don't visibly cut off.
35. Perceived speed > duration: front-load the visible change into the first 30–40% (ease-out does this mathematically).

## E. Layout, hierarchy, depth

36. **Safe areas:** all text inside the inner 80% (title safe); critical visuals inside 90%. For 9:16, keep top ~10% and bottom ~12–15% clear.
37. Focal points on rule-of-thirds intersections; off-center subject + copy in the opposing third is the default product layout.
38. **One focal point per scene.** Whatever moves most IS the focal point — only the subject gets the largest motion amplitude.
39. **Negative space is a shape:** 40–60% empty area in product scenes. High contrast + generous whitespace + monochrome foundation is the premium look.
40. **Parallax ratios:** bg 0.5–0.7× mid, fg 1.3–1.5× mid; inter-layer deltas 0.2–0.5. Background layers slower, softer (2–8px blur), desaturated; foreground faster, sharper.
41. **UI abstraction:** either abstract UI into rounded geometric blocks (viewer follows the flow, not the pixels) or zoom deep into ONE real component and crop all noise. Never a full literal screenshot with tiny text.
42. **Cursor choreography:** cursors move on exaggerated smooth beziers (flow-state, not human jitter) and disappear once the action initiates — the UI "reacts automatically."

## F. Rhythm & music sync

43. **BPM→frames:** `fpb = (60 / BPM) × fps`. Compute beat N's frame as `round(N × fpb)` — never round the interval itself or drift compounds.
44. Cut on the downbeat; scene changes on 4/8-bar phrase boundaries; minor animations on beats/half-beats inside the phrase.
45. **Impact frame ≠ start frame:** elements LAND on the beat — start the animation `duration − ~2f` before the beat.
46. Audio-driven animation: amplitude → scale pulse ±2–5% or glow ±10–20%, never large position moves.
47. **Vary the cut rate:** hold 2–4 beats on important content, 1 beat on montage flashes. Constant one-cut-per-beat numbs by bar 4 — break the pattern exactly when the music breaks.
48. VO pacing: scene changes on sentence boundaries with J-cuts; on-screen text paraphrases (3–6 words), never transcribes, the VO.

## G. Color & light

49. **Background gradients drift** — rotate angle or translate stops over 10–30s loops, imperceptibly slow. Static flat bg = slide-deck tell; fast-moving gradient = AI-slop tell. Felt, not watched.
50. **Ban the purple→cyan gradient** and neon-glass cards — the most common AI pattern. Derive gradients from ONE brand hue (two lightness stops, or hue ±15–30°).
51. Vignette: 10–20% opacity radial darkening, large soft falloff. If you can point at it, halve it.
52. Glow/bloom only on genuine light sources, screen/add blend, low opacity. Never bloom text bodies or whole scenes.
53. Depth via light, not borders: separate layers with luminosity, soft shadows, and blur — never outlines.
54. Motion blur ≈ 180° shutter: directional blur proportional to per-frame velocity × 0.5; 90° (crisper) for tight product motion.

## Momentum, verified (hard requirements at every cut)

- **The momentum system must exist in pixels, not intention.** Wrap EVERY scene (not just some) in exit/enter components; a partially applied system reads as freeze→slam→freeze. Verify with frame diffs (see evaluation rubric), not by reading the code.
- **A cut frame must never be empty.** Exit dims at most ~25% and translates — if content fades to zero before the cut, you built a fade-to-black, not a momentum cut, and the frame dies.
- **Exits accelerate (ease-in), entrances decelerate (ease-out), same direction, matched speed.** An exit 3× faster than its entrance makes every beat gasp and restart limp.
- **The hero beat must measurably peak.** At the climax cut: outgoing scene compresses/accelerates INTO it, incoming opens with the film's largest+longest move, light blooms, the loudest audio hits — motion, scale, light, and sound converge on the same frame. If frame-diff energy at the hero beat is lower than an average scene entrance, it is not a hero beat.
- **Held ending ≠ freeze frame.** The close keeps a continuous push-in, a breathing glow, and gives the CTA a real staggered entrance. Three seconds of pixel-identical frames is a JPEG, not a hold.

## H. Anti-slop checklist (reject the render if any are true)

55. Every element enters with the same generic fade-up — entrances must vary by role (mask reveal for text, scale-settle for cards, wipe for panels).
56. Bounce on everything. Overshoot budget: ≤30% of animations, ≤8% amplitude.
57. Purple→cyan gradient, neon glass, or "six identical cards each with icon + heading + two lines."
58. Everything animates simultaneously — no stagger, no focal discipline.
59. Uniform durations (every animation 500ms) — micro vs transition vs hero must be distinguishable.
60. On-screen text violates reading-speed bounds, or transcribes full sentences.
61. Cuts ignore the music grid; impacts land off-beat.
62. Ease-in-out on entrances (hesitant), ease-in anywhere but exits, or default browser `ease` on hero moves.
63. No texture/life: flat static background with no gradient drift or vignette (slide-deck look).
64. All transitions crossfades, or every transition a different gimmick; no shared element or background continuity.
65. Cursor jitters like a human recording, or stays visible during automated flows.
66. **Emotionally flat sameness — no single memorable moment.** Every piece needs one designed "hero beat": the most important 1–2 seconds get the expressive easing, the biggest motion, and the music accent. Everything else defers to it.
