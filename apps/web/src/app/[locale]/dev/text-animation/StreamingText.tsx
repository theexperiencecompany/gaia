"use client";

import { useId } from "react";

/**
 * Dependency-free streaming text animation — replicates flowtoken's preset
 * technique (per-segment CSS keyframes). Each segment animates ONCE on mount,
 * so when `text` grows token-by-token only the newly-appended segments animate;
 * already-mounted segments keep their final state. That makes it correct for
 * streaming (O(1) per new word) rather than re-animating the whole string.
 *
 * If we adopt the real `flowtoken` package later this component is the drop-in
 * we'd swap for its `AnimatedMarkdown` (this one is markdown-agnostic plain text).
 */

export type AnimationPreset =
  | "none"
  | "fadeIn"
  | "blurIn"
  | "slideUp"
  | "dropIn"
  | "wave"
  | "typewriter";

export const ANIMATION_PRESETS: AnimationPreset[] = [
  "none",
  "fadeIn",
  "blurIn",
  "slideUp",
  "dropIn",
  "wave",
  "typewriter",
];

// Global keyframes injected once. Names are namespaced so they can't clash.
const KEYFRAMES = `
@keyframes ft-fadeIn { from { opacity: 0 } to { opacity: 1 } }
@keyframes ft-blurIn { from { opacity: 0; filter: blur(6px) } to { opacity: 1; filter: blur(0) } }
@keyframes ft-slideUp { from { opacity: 0; transform: translateY(0.5em) } to { opacity: 1; transform: translateY(0) } }
@keyframes ft-dropIn { from { opacity: 0; transform: translateY(-0.5em) } to { opacity: 1; transform: translateY(0) } }
@keyframes ft-typewriter { from { opacity: 0 } to { opacity: 1 } }
`;

const ANIMATION_NAME: Record<AnimationPreset, string | null> = {
  none: null,
  fadeIn: "ft-fadeIn",
  blurIn: "ft-blurIn",
  slideUp: "ft-slideUp",
  dropIn: "ft-dropIn",
  // wave is slideUp with a per-segment delay cascade (handled below).
  wave: "ft-slideUp",
  // typewriter reveals char-by-char with a small per-char delay.
  typewriter: "ft-typewriter",
};

interface StreamingTextProps {
  text: string;
  sep: "word" | "char";
  animation: AnimationPreset;
  durationSec: number;
  timingFunction: string;
}

/** Split keeping the separators so spacing is preserved. */
function segment(text: string, sep: "word" | "char"): string[] {
  if (sep === "char") return Array.from(text);
  return text.split(/(\s+)/).filter((s) => s.length > 0);
}

export function StreamingText({
  text,
  sep,
  animation,
  durationSec,
  timingFunction,
}: Readonly<StreamingTextProps>) {
  const styleId = useId();
  const name = ANIMATION_NAME[animation];
  // typewriter looks right per-char; force char granularity for it.
  const effectiveSep = animation === "typewriter" ? "char" : sep;
  const segments = segment(text, effectiveSep);
  const staggered = animation === "wave" || animation === "typewriter";

  return (
    <span className="whitespace-pre-wrap">
      <style id={styleId} dangerouslySetInnerHTML={{ __html: KEYFRAMES }} />
      {segments.map((seg, i) => {
        if (seg.trim() === "" && effectiveSep === "word") {
          // whitespace token — render as-is, no animation needed
          // biome-ignore lint/suspicious/noArrayIndexKey: stable streaming order
          return <span key={i}>{seg}</span>;
        }
        return (
          <span
            // Stable index key: as text streams, existing segments keep their
            // key (don't remount → don't re-animate); only new ones animate.
            // biome-ignore lint/suspicious/noArrayIndexKey: stable streaming order
            key={i}
            style={
              name
                ? {
                    display: "inline-block",
                    whiteSpace: "pre",
                    animationName: name,
                    animationDuration: `${durationSec}s`,
                    animationTimingFunction: timingFunction,
                    animationFillMode: "both",
                    animationDelay: staggered ? `${i * 0.04}s` : "0s",
                  }
                : undefined
            }
          >
            {seg}
          </span>
        );
      })}
    </span>
  );
}
