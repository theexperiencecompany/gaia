"use client";

import { useEffect, useRef, useState } from "react";

/** Where the agent is acting, as viewport fractions in [0,1], plus what it's doing. */
export interface AgentCursorTarget {
  x: number;
  y: number;
  kind: "click" | "type" | "move";
  label?: string;
  /** Changes per action so the ripple/animation re-fires even on the same point. */
  key: number;
}

// A Figma-style presence cursor overlaid on the live canvas: the pointer glides
// to each action's point, a ring ripples on a click, and a tag names what it's
// doing. The headless browser renders no cursor of its own, so this is the only
// thing that says "it's acting here" — it must read as alive, not decorative.
// How long a target stays "live" after it arrives. Steps take seconds and the
// agent spends much of that thinking, so without this the pointer sits frozen
// on the last thing it touched and reads as stuck rather than idle.
const CURSOR_IDLE_MS = 4000;

export function AgentCursor({ target }: { target: AgentCursorTarget | null }) {
  const [rippleKey, setRippleKey] = useState<number | null>(null);
  const [idle, setIdle] = useState(false);
  const lastKey = useRef<number | null>(null);

  useEffect(() => {
    if (!target || target.key === lastKey.current) return;
    lastKey.current = target.key;
    if (target.kind === "click") setRippleKey(target.key);
  }, [target]);

  // Fade out between actions: each new target restarts the timer.
  useEffect(() => {
    if (!target) return undefined;
    setIdle(false);
    const timer = setTimeout(() => setIdle(true), CURSOR_IDLE_MS);
    return () => clearTimeout(timer);
  }, [target]);

  if (!target) return null;
  const left = `${Math.min(100, Math.max(0, target.x * 100))}%`;
  const top = `${Math.min(100, Math.max(0, target.y * 100))}%`;

  return (
    <div className="pointer-events-none absolute inset-0 z-10 overflow-hidden">
      <div
        className={`absolute transition-[left,top,opacity] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] will-change-[left,top] ${
          idle ? "opacity-0" : "opacity-100"
        }`}
        style={{ left, top }}
      >
        {/* Click ripple — remounted per action key so it replays each time. */}
        {rippleKey !== null && (
          <span
            key={rippleKey}
            className="absolute -left-4 -top-4 size-8 animate-ping rounded-full bg-[#00bbff]/40"
            onAnimationEnd={() => setRippleKey(null)}
          />
        )}
        <CursorArrow />
        {/* Name/action tag, Figma-style, offset from the pointer tip. */}
        {target.label && (
          <span className="absolute left-4 top-4 whitespace-nowrap rounded-md bg-[#00bbff] px-1.5 py-0.5 text-[11px] font-medium text-white shadow-sm">
            {target.kind === "type" ? (
              <span className="inline-flex items-center gap-1">
                {target.label}
                <span className="inline-flex gap-0.5">
                  <Dot delay="0ms" />
                  <Dot delay="150ms" />
                  <Dot delay="300ms" />
                </span>
              </span>
            ) : (
              target.label
            )}
          </span>
        )}
      </div>
    </div>
  );
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="inline-block size-1 animate-bounce rounded-full bg-white/90"
      style={{ animationDelay: delay }}
    />
  );
}

/** The agent's pointer — a Figma-style arrow in the browser accent. Shared by
 * the live overlay and the recap so both read as the same cursor, not a dot. */
export function CursorArrow({ className = "" }: { className?: string }) {
  // Source art: Figma Cursors.svg. Its path spans x 7.33..24.64, y 6.55..24.50;
  // the viewBox pads that by the stroke half-width so no edge is clipped, and
  // starts near the tip so the SVG's top-left is ~the pointer tip — callers put
  // that at the action point.
  return (
    <svg
      width="15"
      height="16"
      viewBox="6.5 5.7 18.9 19.6"
      fill="none"
      className={className}
      role="img"
      aria-label="Agent cursor"
    >
      <title>Agent cursor</title>
      <path
        d="M11.8924 23.7113L7.33378 7.71982C7.0984 6.89409 7.95602 6.18106 8.73584 6.55413L23.8385 13.7792C24.6416 14.1634 24.5812 15.3159 23.7425 15.6131L17.5312 17.8139C17.3056 17.8938 17.1164 18.0511 16.9978 18.2574L13.7318 23.9361C13.2908 24.7029 12.1347 24.5616 11.8924 23.7113Z"
        fill="#00bbff"
        stroke="black"
        strokeWidth="1.2"
        strokeLinejoin="round"
        strokeLinecap="round"
        paintOrder="stroke"
      />
    </svg>
  );
}
