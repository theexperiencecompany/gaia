# Adversarial Evaluation Rubric

The render is guilty until proven innocent. Evaluation is done by a **team of hostile reviewer agents** who each get rendered frames (and the audio track) and try to prove the video is slop. A video ships only when it survives all of them. Never evaluate your own video in the same context that built it — spawn fresh evaluator agents with no attachment to the work.

## Protocol

**Quantitative motion evidence (mandatory for the motion lens).** Prose impressions miss slideshows. Compute a full inter-frame luminance-diff map (mean abs diff per consecutive frame pair over the extracted sequence — a short python script over the jpegs) and report: % of frame pairs below 0.05 ("pixel-frozen"), the largest single-frame spikes outside cuts (pops/layout jumps), per-scene mean energy, and whether the hero beat's entrance energy is actually the film's maximum. A film where >35% of pairs are frozen is a slideshow regardless of how good the stills look. Single-frame spikes comparable to scene cuts are pops — illusion-breakers by definition.

**Regression protocol (round 2+).** Re-evaluations receive the full prior defect list and must verdict each one **FIXED / PARTIAL / REGRESSED** with frame evidence before hunting new defects. A fix pass that doesn't re-verify prior defects doesn't count.


1. **Render evidence first.** Export the full MP4 plus:
   - A frame every 0.5s (`npx remotion still` loop or ffmpeg `-vf fps=2`) → contact sheet per scene
   - **Boundary triplets**: for every scene cut at frame N, export N−2, N−1, N, N+1, N+2 — transitions are judged on these, not on prose descriptions
   - Audio: waveform PNG + loudness stats (`ffmpeg -af loudnorm=print_format=summary`, or ebur128) + a listen pass of the mixed track
2. **Spawn evaluators in parallel**, each with ONE lens (below), each explicitly prompted to REFUTE quality: "find every reason this fails; assume it's AI slop until proven otherwise; score harshly."
3. Each evaluator returns: numbered defects (scene + frame range + what rule it violates + concrete fix), and a 1–10 score for their lens.
4. **Ship gate: every lens ≥ 8/10 and zero defects rated "breaks the illusion".** Otherwise: fix, re-render, re-evaluate. Fixes go through the same beat-grid/duration discipline — no ad-hoc nudging.
5. Keep an ITERATION_LOG (scene → defect → fix → result) so later passes don't regress earlier fixes.

## Lens 1 — Transitions & rhythm

- Is every cut on a beat frame? (Check against the beat grid: `round(N × fpb)`.)
- Frame-step every boundary triplet: does motion continue across the cut (direction + velocity) or does the frame die and restart?
- Are ≥70% of transitions hard cuts, with intentional devices (match cut, shared element, z-push, whip) only at chapter changes?
- Any crossfades between statement scenes? Instant fail.
- Does the cut rate vary (holds on important content, fast on montage), or is it a numbing metronome?
- Is there exactly one "hero beat" moment where music, motion, and message peak together — and does the reveal land ON the drop?

## Lens 2 — Typography & readability

- Word count per screen ≤7? One idea per scene?
- Hold times ≥ `0.9 + 0.24 × words` seconds, ≥1.5s for hero lines, ≤17 chars/sec?
- Type scale: hero-to-support ratio ≥2.6:1, only 2–3 sizes per scene?
- Correct fonts per role (display serif only for editorial moments, Inter for UI, mono for timestamps/code)? Correct tracking (negative on display, 0 on body)?
- Text entrances: staggered (not chorus), one hero effect max, no typewriter/bounce/scale-from-zero tells?
- Any orphaned words, bad rags, clipped descenders, subpixel-blurry text?

## Lens 3 — Layout, hierarchy & whitespace

- One focal point per scene — is the thing that moves most the thing that matters most?
- Negative space 40–60% in product scenes; content within title-safe (inner 80%)?
- Do layouts use the brand grid (two-tone cards, 16px+ radius, no borders/shadows) or generic centered-stack-of-stuff?
- Any "six identical cards" layouts, icon+heading+two-lines grids, or hierarchy expressed only via font size instead of area/position?
- Do UI mockups read as REAL product surfaces (plausible copy, timestamps, avatars) or as lorem-ipsum-grade filler?

## Lens 4 — Motion physics & AI-slop tells

Go through the full ban list: linear position easing · ease-in entrances · simultaneous entrances · uniform durations · center-symmetric scale-pops · unmotivated motion · mixed entrance directions in one scene · bounce on non-gestural elements · always-moving scenes (no motion→hold→cut) · missing stagger · missing anticipation/settle on the hero move. Also:
- Does every scene hold still for ≥50% of its duration after the entrance?
- Is motion motivated by meaning (counts count up, "fast" moves fast)?
- Duration hierarchy audible in the motion (micro ≠ standard ≠ hero)?

## Lens 5 — Brand fidelity

- Canvas `#111111`/`#09090b`, single cyan `#00bbff` accent, zinc neutrals only?
- Any second saturated hue, purple→cyan gradient, neon glass? Instant fail.
- House blur-in used as the default entrance? House ease everywhere?
- Fonts exactly PP Editorial New / Inter / Geist Mono? Logo assets correct (SVG glyph, wordmark)?
- Would a GAIA landing-page visitor recognize this as the same brand in 2 seconds?

## Lens 6 — Audio

- Music: does the energy arc track the story (sparse → riser → drop at reveal → groove → exhale under end card)? Is the genre premium (minimal/electronic/piano), not stock-cheese?
- **Is the drop the loudest moment?** Measure momentary loudness around the reveal — the seconds after the drop must out-measure the riser before it. Check duck release timing, riser end alignment, boom attack offset.
- SFX: are entrances/impacts supported by whooshes/ticks/booms at the right frames (±1f)? Are SFX levels −12 to −20 dB below music peaks (felt, not noticed)? Any comedy/cartoon SFX? Instant fail.
- VO (if present): natural pacing, no robotic cadence artifacts, music ducked −6 to −9 dB under speech, J/L-cuts at scene changes (audio never cut on the video frame)?
- Mix: integrated loudness ≈ −14 LUFS, true peak ≤ −1 dBTP, no clipping, clean fade-out (no abrupt end)?
- Sync: cuts and impacts land on beats — verify against the waveform, not by feel.

## Lens 7 — Story & virality

- Does the first 0.5s already contain the hook (no logo intro / music ramp)? Would it stop a scroll?
- Does the video make sense with sound OFF (on-screen text carries the story)?
- Reveal by 15–20s? One workflow shown deeply, not a feature tour?
- Specificity: real numbers, timestamps, plausible names — or vague adjectives?
- For agent narratives: is the human the hero and approver? Is anything cringe (agent doing what humans should do)?
- One CTA, end card held 3–4s, strongest proof near the end?
- The one-sentence takeaway: can each evaluator state it identically? If they differ, the story failed.

## Scoring discipline

- 10 = could ship on apple.com. 8 = professional, minor polish notes. 6 = competent but recognizably generated. 4 = AI slop with effort. Below 4 = restart the scene.
- Evaluators must justify any score ≥8 with the same rigor as a defect — "looks good" is not evidence.
- If two consecutive iterations produce no score improvement on a lens, the fix approach is wrong — change strategy (rebuild the scene) instead of nudging values.
