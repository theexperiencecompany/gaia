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

// A Figma-style presence cursor over the live canvas — the headless browser
// renders none of its own. A target stays "live" this long after it arrives;
// steps take seconds of thinking, and a frozen pointer reads as stuck.
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
  // Source art: Figma Cursors.svg (path x 7.33..24.64, y 6.55..24.50). The
  // viewBox pads by the stroke half-width and starts near the tip, so the
  // SVG's top-left is ~the pointer tip that callers place on the action point.
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
        d="M11.89 23.71L7.33 7.72C7.1 6.89 7.96 6.18 8.74 6.55L23.84 13.78C24.64 14.16 24.58 15.32 23.74 15.61L17.53 17.81C17.31 17.89 17.12 18.05 17 18.26L13.73 23.94C13.29 24.7 12.13 24.56 11.89 23.71Z"
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
